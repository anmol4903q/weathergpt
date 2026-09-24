from fastapi import APIRouter, Query

from app.models.alerts import ImdAlertsResponse
from app.services.alert_service import AlertFeedUnavailable, get_active_imd_alerts

router = APIRouter(prefix="/weather", tags=["alerts"])


@router.get("/alerts", response_model=ImdAlertsResponse)
async def alerts_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """
    Official IMD warnings covering this point, from IMD's public CAP feed.

    status="unavailable" means the feed itself couldn't be reached/parsed —
    this is NOT the same as "no warning" and must never be presented as
    such (e.g. to the AI layer or frontend as an all-clear).

    Always returns HTTP 200 with a status field, even on failure — the
    caller needs the structured "unavailable" state, not a generic 5xx.
    """
    try:
        result = await get_active_imd_alerts(lat, lon)
    except AlertFeedUnavailable:
        return ImdAlertsResponse(latitude=lat, longitude=lon, status="unavailable", warnings=[])

    return ImdAlertsResponse(latitude=lat, longitude=lon, status=result["status"], warnings=result["warnings"])
