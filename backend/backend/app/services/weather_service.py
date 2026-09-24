"""
Weather data provider.

Design contract for future provider swaps (e.g. One Call 3.0, or a
different vendor entirely): get_current_weather(), get_hourly_forecast(),
and get_daily_forecast() are the ONLY functions the API layer
(app/api/weather.py) calls, and their return dict shapes are fixed —
they map 1:1 onto app/models/weather.py's Pydantic models. Swapping the
underlying provider means rewriting the body of these functions (and
whatever private helpers they use); it should never require touching
app/api/weather.py or app/models/weather.py.
"""

import time
from collections import Counter

import httpx

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

# Cache to stay well under OWM's free-tier quota (60 calls/min, 1000/day)
# and speed up repeat lookups.
_cache: dict[str, tuple[float, dict]] = {}
_CURRENT_TTL_SECONDS = 600      # 10 min
_FORECAST_TTL_SECONDS = 1800    # 30 min — shared by hourly AND daily, since
                                # both are derived from the same raw call.

# Used to break ties when a day has an equal number of 3-hour blocks
# reporting different conditions (e.g. 4x Clouds, 4x Rain). More severe/
# notable conditions win the tie, since "it rained part of the day" is
# more decision-relevant than "it was cloudy part of the day".
_CONDITION_SEVERITY = [
    "Thunderstorm", "Tornado", "Squall", "Ash", "Snow", "Rain", "Drizzle",
    "Fog", "Sand", "Dust", "Haze", "Smoke", "Mist", "Atmosphere", "Clouds", "Clear",
]


class WeatherAuthError(Exception):
    """API key rejected — likely not activated yet or genuinely invalid."""


class WeatherServiceError(Exception):
    """Any other non-2xx response from OpenWeatherMap."""


def _cache_get(key: str, ttl: int) -> dict | None:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, data = entry
    if time.monotonic() - ts > ttl:
        del _cache[key]
        return None
    return data


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = (time.monotonic(), data)


async def _get(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)

    if response.status_code == 401:
        raise WeatherAuthError(
            "OpenWeatherMap rejected the API key (401). If you just generated "
            "it, it can take up to ~2 hours to activate. If it's been longer, "
            "double-check WEATHER_API_KEY in .env has no extra spaces/quotes."
        )
    if response.status_code != 200:
        raise WeatherServiceError(f"OpenWeatherMap returned {response.status_code}: {response.text[:300]}")

    return response.json()


async def get_current_weather(lat: float, lon: float, api_key: str) -> dict:
    cache_key = f"current:{round(lat, 3)}:{round(lon, 3)}"
    cached = _cache_get(cache_key, _CURRENT_TTL_SECONDS)
    if cached:
        return cached

    params = {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"}
    data = await _get(OWM_CURRENT_URL, params)

    weather = data.get("weather", [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})
    rain = data.get("rain", {})

    result = {
        "latitude": lat,
        "longitude": lon,
        "temperature_c": main.get("temp"),
        "feels_like_c": main.get("feels_like"),
        "humidity_pct": main.get("humidity"),
        "wind_speed_ms": wind.get("speed", 0.0),
        "wind_deg": wind.get("deg", 0),
        "visibility_m": data.get("visibility"),
        "pressure_hpa": main.get("pressure"),
        "rain_1h_mm": rain.get("1h", 0.0),
        "condition_main": weather.get("main", "Unknown"),
        "condition_description": weather.get("description", ""),
    }
    _cache_set(cache_key, result)
    return result


async def _fetch_raw_forecast(lat: float, lon: float, api_key: str) -> dict:
    """
    The ONE place that actually calls OWM's 5-day/3-hour endpoint.
    Both get_hourly_forecast() and get_daily_forecast() build off this,
    so requesting both for the same coordinates costs one network call,
    not two.
    """
    cache_key = f"raw_forecast:{round(lat, 3)}:{round(lon, 3)}"
    cached = _cache_get(cache_key, _FORECAST_TTL_SECONDS)
    if cached:
        return cached

    params = {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"}
    data = await _get(OWM_FORECAST_URL, params)
    _cache_set(cache_key, data)
    return data


async def get_hourly_forecast(lat: float, lon: float, api_key: str) -> dict:
    """
    3-hour-step forecast blocks for up to 5 days (OWM free tier).
    NOT true daily/7-day — see get_daily_forecast() for that approximation.
    """
    data = await _fetch_raw_forecast(lat, lon, api_key)

    forecast = []
    for entry in data.get("list", []):
        weather = entry.get("weather", [{}])[0]
        rain = entry.get("rain", {})
        forecast.append({
            "time_utc": entry.get("dt_txt"),
            "temperature_c": entry.get("main", {}).get("temp"),
            "rain_probability_pct": round(entry.get("pop", 0) * 100),
            "rain_3h_mm": rain.get("3h", 0.0),
            "condition_main": weather.get("main", "Unknown"),
            "condition_description": weather.get("description", ""),
        })

    return {"latitude": lat, "longitude": lon, "forecast": forecast}


def _dominant_condition(conditions: list[dict]) -> dict:
    mains = [c.get("main", "Unknown") for c in conditions]
    counts = Counter(mains)
    max_count = max(counts.values())
    tied = [m for m, c in counts.items() if c == max_count]

    if len(tied) == 1:
        winner = tied[0]
    else:
        def severity_rank(name: str) -> int:
            return _CONDITION_SEVERITY.index(name) if name in _CONDITION_SEVERITY else len(_CONDITION_SEVERITY)
        winner = min(tied, key=severity_rank)

    description = next((c.get("description", "") for c in conditions if c.get("main") == winner), "")
    return {"main": winner, "description": description}


def _aggregate_daily(entries: list[dict]) -> list[dict]:
    """
    Group 3-hour OWM forecast blocks into calendar-day summaries.

    Only produces entries for dates actually present in the forecast —
    never pads to 7 days. The first and/or last day will usually be
    PARTIAL (entry_count < 8) since the 5-day window rarely aligns to
    midnight boundaries. Callers should treat entry_count < 8 as
    "incomplete day" data, not a full day's summary.
    """
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []

    for entry in entries:
        dt_txt = entry.get("dt_txt", "")
        date_str = dt_txt.split(" ")[0] if dt_txt else None
        if not date_str:
            continue
        if date_str not in buckets:
            buckets[date_str] = []
            order.append(date_str)
        buckets[date_str].append(entry)

    days = []
    for date_str in order:
        block_entries = buckets[date_str]
        temps_min, temps_max, pops, conditions = [], [], [], []
        total_rain = 0.0

        for e in block_entries:
            main_block = e.get("main", {})
            t_min = main_block.get("temp_min", main_block.get("temp"))
            t_max = main_block.get("temp_max", main_block.get("temp"))
            if t_min is not None:
                temps_min.append(t_min)
            if t_max is not None:
                temps_max.append(t_max)
            total_rain += e.get("rain", {}).get("3h", 0.0)
            pops.append(e.get("pop", 0.0))
            weather_list = e.get("weather", [])
            if weather_list:
                conditions.append(weather_list[0])

        dominant = _dominant_condition(conditions) if conditions else {"main": "Unknown", "description": ""}

        days.append({
            "date": date_str,
            "temp_min_c": min(temps_min) if temps_min else None,
            "temp_max_c": max(temps_max) if temps_max else None,
            "total_rain_mm": round(total_rain, 1),
            # Max, not average: if any 3h block in the day predicts rain,
            # the day-level probability reflects that risk rather than
            # diluting it — safer default for advisory use cases.
            "rain_probability_pct": round(max(pops) * 100) if pops else 0,
            "condition_main": dominant["main"],
            "condition_description": dominant["description"],
            "entry_count": len(block_entries),
        })

    return days


async def get_daily_forecast(lat: float, lon: float, api_key: str) -> dict:
    """
    Approximate daily forecast, aggregated from OWM's free 5-day/3-hour
    endpoint. This is NOT a true 7-day forecast — it covers only whatever
    calendar days fall within the ~5-day window OWM actually returns
    (typically 5-6 dates, with the first/last often partial). True 7-day
    daily data requires OWM's One Call 3.0 API (separate subscription).

    To upgrade later: replace this function's body with a One Call 3.0
    call and mapping — the return shape (and therefore the API contract
    and frontend) does not need to change.
    """
    data = await _fetch_raw_forecast(lat, lon, api_key)
    days = _aggregate_daily(data.get("list", []))

    return {
        "latitude": lat,
        "longitude": lon,
        "days": days,
        "source": "owm_5day_3hour_aggregate",
        "note": (
            "Approximate daily summary aggregated from OpenWeatherMap's free "
            "5-day/3-hour forecast. Covers only the days actually present in "
            "that window (first/last day may be partial — see entry_count "
            "per day, 8 = full day). Not a true 7-day forecast; that needs "
            "OWM One Call 3.0 (separate subscription)."
        ),
    }
