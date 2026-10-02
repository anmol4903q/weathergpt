
import json
import re
import time

import httpx
from shapely.geometry import Point, shape

WFS_URL = "https://reactjs.imd.gov.in/geoserver/wfs"
WFS_PARAMS = {
    "callback": "getJson",
    "service": "WFS",
    "version": "1.1.0",
    "request": "GetFeature",
    "typename": "imd:district_warnings_india",
    "srsname": "EPSG:4326",
    "format_options": "callback:getJson",
    "outputFormat": "text/javascript",
}

# Hundreds of district polygons in one payload; this doesn't change faster
# than IMD's own daily warning cycle, so an hour-long cache is conservative
# without being wasteful of either side's bandwidth.
CACHE_TTL_SECONDS = 3600

# IMD's own published code table (as supplied in the task), kept here as
# reference metadata only — never used to alter or fabricate a Day_N value,
# only to attach a human-readable label alongside the raw code.
WARNING_CODE_LABELS = {
    1: "No Warning",
    2: "Heavy Rain",
    3: "Heavy Snow",
    4: "Thunderstorm & Lightning, Squall etc",
    5: "Hailstorm",
    6: "Dust Storm",
    7: "Dust Raising Winds",
    8: "Strong Surface Winds",
    9: "Heat Wave",
    10: "Hot Day",
    11: "Warm Night",
    12: "Cold Wave",
    13: "Cold Day",
    14: "Ground Frost",
    15: "Fog",
    16: "Very Heavy Rain",
    17: "Extremely Heavy Rain",
}

_cache: dict[str, tuple[float, dict]] = {}


class DistrictWarningUnavailable(Exception):
    """WFS fetch, JSONP unwrap, or JSON parse failed. Never silently
    treated as 'no warning' by any caller of this module."""


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


def _strip_jsonp(text: str) -> dict:
    """Input is 'getJson({...})' (possibly with trailing whitespace/semicolon).
    Strips the wrapper safely — validates the callback name rather than
    blindly slicing — and parses the remaining JSON."""
    match = re.match(r"^\s*getJson\s*\((.*)\)\s*;?\s*$", text, re.DOTALL)
    if not match:
        raise DistrictWarningUnavailable(
            "WFS response was not in the expected 'getJson(...)' JSONP wrapper"
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DistrictWarningUnavailable(f"WFS JSONP payload was not valid JSON: {exc}")


async def _fetch_feature_collection() -> dict:
    cached = _cache_get("district_warnings_fc", CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(WFS_URL, params=WFS_PARAMS)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise DistrictWarningUnavailable(f"IMD WFS request timed out: {exc}")
    except httpx.HTTPStatusError as exc:
        raise DistrictWarningUnavailable(f"IMD WFS returned {exc.response.status_code}")
    except httpx.HTTPError as exc:
        raise DistrictWarningUnavailable(f"IMD WFS request failed: {exc}")

    feature_collection = _strip_jsonp(response.text)
    _cache_set("district_warnings_fc", feature_collection)
    return feature_collection


def _feature_contains_point(feature: dict, lat: float, lon: float) -> bool:
    """GeoJSON coordinates are [lon, lat], NOT [lat, lon] — opposite of the
    CAP feed's custom polygon format used elsewhere in this project. Using
    shapely.geometry.shape() on the raw geometry dict handles that
    ordering and the MultiPolygon ring nesting correctly, rather than
    hand-walking the coordinate arrays and risking an axis-order bug."""
    geometry = feature.get("geometry")
    if not geometry:
        return False
    try:
        geom = shape(geometry)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            return False
        return geom.covers(Point(lon, lat))  # Point() takes (x=lon, y=lat)
    except Exception:
        return False  # one malformed feature must not break the whole lookup


def _build_warning_info(feature: dict) -> dict:
    props = feature.get("properties", {})
    day_values = {}
    for i in range(1, 6):
        raw = props.get(f"Day_{i}")
        try:
            code = int(raw)
        except (TypeError, ValueError):
            code = None
        day_values[f"day{i}"] = code
        day_values[f"day{i}_color"] = props.get(f"Day{i}_Color")
        day_values[f"day{i}_label"] = WARNING_CODE_LABELS.get(code) if code is not None else None

    return {
        "district": props.get("District"),
        "obj_id": str(props.get("Obj_id")) if props.get("Obj_id") is not None else None,
        "date": props.get("Date"),
        "updated_at": props.get("updated_at"),
        **day_values,
    }


async def find_district_warning(lat: float, lon: float) -> dict | None:
    """Returns the matched district's warning info dict, or None if no
    district polygon contains this point. Raises DistrictWarningUnavailable
    if the feed itself couldn't be fetched/parsed — that is a different,
    more serious case than "found no match" and callers must not conflate
    them (same discipline as the existing CAP-based alert service)."""
    feature_collection = await _fetch_feature_collection()
    features = feature_collection.get("features", [])

    for feature in features:
        if _feature_contains_point(feature, lat, lon):
            return _build_warning_info(feature)

    return None

