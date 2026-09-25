"""
Phase 5D/5E — data selection + compact context building.

Calls existing Phase 2-4 service functions DIRECTLY (no internal HTTP to
our own API) and only for the flags the parsed query actually set. Then
trims the result down to what Gemini needs — never a raw provider dump,
never irrelevant forecast entries, never a polygon (frontend gets that
from /weather/alerts directly if it needs it for a map).
"""

from app.models.chat import ResolvedTime
from app.services import alert_service, weather_service
from app.services.alert_service import AlertFeedUnavailable
from app.services.time_resolution import PERIOD_HOUR_RANGES
from app.services.weather_service import WeatherAuthError, WeatherServiceError


def _filter_hourly(forecast_items: list[dict], resolved_time: ResolvedTime) -> list[dict]:
    if not resolved_time.within_forecast_horizon:
        # The requested date is beyond what OWM's forecast covers.
        # Return nothing rather than the wrong day's data.
        return []

    target_date = resolved_time.target_date
    # NOTE: OWM's dt_txt is UTC; target_date was resolved in IST. This is a
    # documented simplification (~5.5h offset imprecision), not a silent bug —
    # a full UTC<->IST conversion layer was out of scope for this phase.
    matches = [f for f in forecast_items if f["time_utc"].startswith(target_date)]

    if resolved_time.period and resolved_time.period in PERIOD_HOUR_RANGES:
        lo, hi = PERIOD_HOUR_RANGES[resolved_time.period]

        def _hour(item: dict) -> int:
            return int(item["time_utc"].split(" ")[1].split(":")[0])

        matches = [f for f in matches if lo <= _hour(f) < hi]

    return matches[:4]  # cap — never send the whole forecast blob


def _pick_day(days: list[dict], target_date: str) -> dict | None:
    for d in days:
        if d["date"] == target_date:
            return d
    return None


async def gather_weather_context(
    parsed, lat: float, lon: float, resolved_time: ResolvedTime, weather_api_key: str
) -> dict:
    result = {
        "current": None,
        "relevant_forecast": [],
        "daily_summary": None,
        "alerts": [],
        "source_status": {"weather": "not_requested", "imd_alerts": "not_requested"},
    }

    def _mark_weather_available():
        if result["source_status"]["weather"] != "unavailable":
            result["source_status"]["weather"] = "available"

    if parsed.requires_current_weather:
        try:
            result["current"] = await weather_service.get_current_weather(lat, lon, weather_api_key)
            _mark_weather_available()
        except (WeatherAuthError, WeatherServiceError):
            result["source_status"]["weather"] = "unavailable"

    if parsed.requires_hourly_forecast:
        try:
            hourly = await weather_service.get_hourly_forecast(lat, lon, weather_api_key)
            result["relevant_forecast"] = _filter_hourly(hourly["forecast"], resolved_time)
            _mark_weather_available()
        except (WeatherAuthError, WeatherServiceError):
            result["source_status"]["weather"] = "unavailable"

    if parsed.requires_daily_forecast:
        try:
            daily = await weather_service.get_daily_forecast(lat, lon, weather_api_key)
            result["daily_summary"] = _pick_day(daily["days"], resolved_time.target_date)
            _mark_weather_available()
        except (WeatherAuthError, WeatherServiceError):
            result["source_status"]["weather"] = "unavailable"

    if parsed.requires_alerts:
        try:
            alerts_result = await alert_service.get_active_imd_alerts(lat, lon)
            result["alerts"] = alerts_result["warnings"]
            result["source_status"]["imd_alerts"] = alerts_result["status"]  # "ok" | "no_active_warning"
        except AlertFeedUnavailable:
            result["source_status"]["imd_alerts"] = "unavailable"

    return result
