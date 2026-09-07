"""
Official IMD weather warnings, sourced from IMD's public CAP (Common
Alerting Protocol) feed — NOT the gated District-wise Warnings REST API,
which requires a gov.in/nic.in-domain email to register for.

Granularity trade-off (documented, not hidden): this feed publishes
state/subdivision-level bulletins with a real geographic polygon, not
per-district IDs. We match the user's point against each alert's polygon
directly instead of pretending district-level precision we don't have.

This is a completely separate source from OpenWeather. Nothing in this
file is allowed to originate from weather_service.py's data — a
WeatherGPT-derived risk assessment is a different feature, built later,
under a different source label.
"""

import time
import xml.etree.ElementTree as ET

import httpx
from shapely.geometry import Point, Polygon

CAP_RSS_URL = "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml"
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

# The feed is bulletin-driven, not continuously regenerated — IMD posts a
# handful of items a day at most. 15 min for the index, 30 min for each
# alert document (an already-published CAP alert's content doesn't change).
_INDEX_TTL_SECONDS = 900
_ALERT_TTL_SECONDS = 1800

_cache: dict[str, tuple[float, object]] = {}


class AlertFeedUnavailable(Exception):
    """The CAP feed index itself could not be fetched or parsed at all.
    This must NEVER be treated as 'no warning' — it means we don't know."""


def _cache_get(key: str, ttl: int):
    entry = _cache.get(key)
    if not entry:
        return None
    ts, data = entry
    if time.monotonic() - ts > ttl:
        del _cache[key]
        return None
    return data


def _cache_set(key: str, data) -> None:
    _cache[key] = (time.monotonic(), data)


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _fetch_feed_index() -> list[dict]:
    """Returns [{'link':..., 'guid':..., 'pubDate':...}, ...]. Raises
    AlertFeedUnavailable on any network/parse failure of the index itself."""
    cached = _cache_get("cap_index", _INDEX_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        text = await _fetch_text(CAP_RSS_URL)
        root = ET.fromstring(text)
    except httpx.TimeoutException as exc:
        raise AlertFeedUnavailable(f"IMD CAP feed timed out: {exc}")
    except httpx.HTTPStatusError as exc:
        raise AlertFeedUnavailable(f"IMD CAP feed returned {exc.response.status_code}")
    except httpx.HTTPError as exc:
        raise AlertFeedUnavailable(f"IMD CAP feed request failed: {exc}")
    except ET.ParseError as exc:
        raise AlertFeedUnavailable(f"IMD CAP feed returned malformed XML: {exc}")

    items = []
    for item in root.findall(".//item"):
        link = item.findtext("link")
        if not link:
            continue
        items.append({
            "link": link.strip(),
            "guid": (item.findtext("guid") or "").strip(),
            "pub_date": (item.findtext("pubDate") or "").strip(),
        })

    _cache_set("cap_index", items)
    return items


def _parse_polygon(polygon_text: str | None) -> list[tuple[float, float]] | None:
    """CAP polygon format: space-separated 'lat,lon' pairs. Returns
    [(lat, lon), ...] or None if missing/malformed/too few points."""
    if not polygon_text:
        return None
    try:
        points = []
        for pair in polygon_text.strip().split():
            lat_str, lon_str = pair.split(",")
            points.append((float(lat_str), float(lon_str)))
        if len(points) < 3:
            return None
        return points
    except (ValueError, AttributeError):
        return None


def _point_in_polygon(lat: float, lon: float, points: list[tuple[float, float]]) -> bool:
    """Shapely uses (x, y) = (lon, lat); CAP polygons are (lat, lon) — the
    conversion below is the one place that ordering flip has to happen."""
    try:
        shapely_coords = [(lon_p, lat_p) for (lat_p, lon_p) in points]
        polygon = Polygon(shapely_coords)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)  # attempt to repair self-intersections
        if polygon.is_empty:
            return False
        return polygon.covers(Point(lon, lat))  # covers() includes the boundary
    except Exception:
        # Any shapely construction error (degenerate/invalid geometry we
        # can't repair) means we can't evaluate this alert's area — skip
        # it rather than crash the whole response over one bad polygon.
        return False


async def _fetch_and_parse_alert(url: str) -> dict | None:
    """Returns a parsed CAP alert dict, or None if this one item couldn't
    be fetched/parsed — callers must skip it and continue, not fail the
    whole request over a single bad alert document."""
    cached = _cache_get(f"cap_doc:{url}", _ALERT_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        text = await _fetch_text(url)
        root = ET.fromstring(text)
    except (httpx.HTTPError, ET.ParseError):
        return None

    info = root.find("cap:info", CAP_NS)
    if info is None:
        return None

    area = info.find("cap:area", CAP_NS)
    area_desc = area.findtext("cap:areaDesc", default="", namespaces=CAP_NS) if area is not None else ""
    polygon_text = area.findtext("cap:polygon", default=None, namespaces=CAP_NS) if area is not None else None
    polygon_points = _parse_polygon(polygon_text)

    parsed = {
        "event": info.findtext("cap:event", default="Unknown", namespaces=CAP_NS),
        "severity": info.findtext("cap:severity", default="Unknown", namespaces=CAP_NS),
        "urgency": info.findtext("cap:urgency", default="Unknown", namespaces=CAP_NS),
        "certainty": info.findtext("cap:certainty", default="Unknown", namespaces=CAP_NS),
        "area_description": area_desc,
        "headline": info.findtext("cap:headline", default="", namespaces=CAP_NS),
        "description": info.findtext("cap:description", default="", namespaces=CAP_NS),
        "instruction": info.findtext("cap:instruction", default=None, namespaces=CAP_NS),
        "onset": info.findtext("cap:onset", default=None, namespaces=CAP_NS),
        "expires": info.findtext("cap:expires", default=None, namespaces=CAP_NS),
        "sent": root.findtext("cap:sent", default=None, namespaces=CAP_NS),
        "polygon_points": polygon_points,  # list[(lat, lon)] or None, kept for matching + response
    }
    _cache_set(f"cap_doc:{url}", parsed)
    return parsed


async def get_active_imd_alerts(lat: float, lon: float) -> dict:
    """
    Returns {"status": "ok"|"no_active_warning", "warnings": [...]}.
    Raises AlertFeedUnavailable if the feed index itself is unreachable —
    callers must surface that as 'unavailable', never as 'no warning'.
    """
    items = await _fetch_feed_index()  # raises AlertFeedUnavailable on failure

    matches = []
    for item in items:
        alert = await _fetch_and_parse_alert(item["link"])
        if alert is None:
            continue  # one bad/unreachable alert doc — skip, don't fail the request
        if not alert["polygon_points"]:
            continue  # no usable geometry to test — can't confirm a match, skip
        if _point_in_polygon(lat, lon, alert["polygon_points"]):
            matches.append({
                "event": alert["event"],
                "severity": alert["severity"],
                "urgency": alert["urgency"],
                "certainty": alert["certainty"],
                "area_description": alert["area_description"],
                "headline": alert["headline"],
                "description": alert["description"],
                "instruction": alert["instruction"],
                "onset": alert["onset"],
                "expires": alert["expires"],
                "sent": alert["sent"],
                "polygon": [[lat_p, lon_p] for (lat_p, lon_p) in alert["polygon_points"]],
            })

    status = "ok" if matches else "no_active_warning"
    return {"status": status, "warnings": matches}
