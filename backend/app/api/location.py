import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.models.location import LocationResponse
from app.services.location_service import (
    GeocodingError,
    forward_geocode,
    reverse_geocode,
)

router = APIRouter(prefix="/location", tags=["location"])


def _geocoding_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(status_code=504, detail="Geocoding service timed out")
    if isinstance(exc, httpx.HTTPStatusError):
        body_snippet = exc.response.text[:300]
        return HTTPException(
            status_code=502,
            detail=f"Geocoding service returned {exc.response.status_code}: {body_snippet}",
        )
    if isinstance(exc, GeocodingError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("/reverse", response_model=LocationResponse)
async def reverse_geocode_endpoint(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
):
    """
    GPS coordinates -> place. This is the 'current_location' path — call
    this with the browser's navigator.geolocation output.
    """
    settings = get_settings()
    try:
        result = await reverse_geocode(lat, lon, settings.nominatim_user_agent)
    except (httpx.TimeoutException, httpx.HTTPStatusError, GeocodingError) as exc:
        raise _geocoding_error_response(exc)

    return LocationResponse(**result)


@router.get("/search", response_model=LocationResponse)
async def search_location_endpoint(
    q: str = Query(..., min_length=2, description="Place name, e.g. 'Mumbai'"),
):
    """
    Place name -> coordinates + place. This is the 'query_location' path —
    call this when the user types or asks about a location that is NOT
    where they currently are. Never overwrites current_location.
    """
    settings = get_settings()
    try:
        result = await forward_geocode(q, settings.nominatim_user_agent)
    except (httpx.TimeoutException, httpx.HTTPStatusError, GeocodingError) as exc:
        raise _geocoding_error_response(exc)

    return LocationResponse(**result)
