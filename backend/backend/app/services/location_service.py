import asyncio
import time

import httpx

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim's usage policy caps automated use at 1 request/second, enforced
# by IP ban if exceeded. This lock + timestamp throttle every outbound call
# this process makes, regardless of how many users hit our API concurrently.
_last_call_lock = asyncio.Lock()
_last_call_time = 0.0
_MIN_INTERVAL_SECONDS = 1.1  # slightly above 1s for safety margin

# Simple in-memory TTL cache. Coordinates and place names don't move, so
# repeat lookups (GPS re-firing on page reload, same city searched twice)
# should never hit the network at all.
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes


class GeocodingError(Exception):
    """Nominatim responded but gave no usable location."""


async def _throttle() -> None:
    global _last_call_time
    async with _last_call_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SECONDS - (now - _last_call_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_time = time.monotonic()


def _cache_get(key: str) -> dict | None:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, data = entry
    if time.monotonic() - ts > _CACHE_TTL_SECONDS:
        del _cache[key]
        return None
    return data


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = (time.monotonic(), data)


def _parse_address(data: dict, lat: float, lon: float) -> dict:
    address = data.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
    )
    district = address.get("state_district") or address.get("county")
    state = address.get("state")
    return {
        "city": city,
        "district": district,
        "state": state,
        "latitude": lat,
        "longitude": lon,
        "raw_display_name": data.get("display_name"),
    }


async def reverse_geocode(lat: float, lon: float, user_agent: str) -> dict:
    """GPS coordinates -> place. Used for 'current location'."""
    cache_key = f"reverse:{round(lat, 4)}:{round(lon, 4)}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10, "addressdetails": 1}
    headers = {"User-Agent": user_agent}

    await _throttle()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(NOMINATIM_REVERSE_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    if "error" in data or "address" not in data:
        raise GeocodingError(data.get("error", "No address found for these coordinates"))

    result = _parse_address(data, lat=lat, lon=lon)
    _cache_set(cache_key, result)
    return result


async def forward_geocode(query: str, user_agent: str) -> dict:
    """Place name (e.g. 'Mumbai') -> coordinates + place. Used for 'query location'."""
    cache_key = f"search:{query.strip().lower()}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 1}
    headers = {"User-Agent": user_agent}

    await _throttle()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(NOMINATIM_SEARCH_URL, params=params, headers=headers)
        response.raise_for_status()
        results = response.json()

    if not results:
        raise GeocodingError(f"No location found for '{query}'")

    top = results[0]
    result = _parse_address(top, lat=float(top["lat"]), lon=float(top["lon"]))
    _cache_set(cache_key, result)
    return result
