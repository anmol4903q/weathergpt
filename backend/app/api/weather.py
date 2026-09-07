from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.models.weather import CurrentWeatherResponse, DailyForecastResponse, HourlyForecastResponse
from app.services.weather_service import (
    WeatherAuthError,
    WeatherServiceError,
    get_current_weather,
    get_daily_forecast,
    get_hourly_forecast,
)

router = APIRouter(prefix="/weather", tags=["weather"])


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.weather_api_key:
        raise HTTPException(
            status_code=500,
            detail="WEATHER_API_KEY is not set in .env — weather endpoints can't work without it.",
        )
    return settings.weather_api_key


@router.get("/current", response_model=CurrentWeatherResponse)
async def current_weather_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    api_key = _require_api_key()
    try:
        result = await get_current_weather(lat, lon, api_key)
    except WeatherAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return CurrentWeatherResponse(**result)


@router.get("/hourly", response_model=HourlyForecastResponse)
async def hourly_forecast_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """
    3-hour-step forecast blocks for up to 5 days (OWM free tier).
    NOT true daily/7-day — that needs One Call 3.0, a separate subscription.
    """
    api_key = _require_api_key()
    try:
        result = await get_hourly_forecast(lat, lon, api_key)
    except WeatherAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return HourlyForecastResponse(**result)


@router.get("/daily", response_model=DailyForecastResponse)
async def daily_forecast_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """
    Approximate daily forecast aggregated from the 5-day/3-hour data.
    NOT a true 7-day forecast — see response 'note' field and each day's
    entry_count (8 = full day, fewer = partial). Upgrade path: One Call 3.0.
    """
    api_key = _require_api_key()
    try:
        result = await get_daily_forecast(lat, lon, api_key)
    except WeatherAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return DailyForecastResponse(**result)
