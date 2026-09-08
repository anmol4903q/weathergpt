"""
Phase 5 orchestrator — the ONLY place that wires query understanding,
location/time resolution, existing Phase 2-4 services, and Gemini together.

current_location is passed in per-call from the request — never stored as
module/global state. Two concurrent users must never be able to see or
overwrite each other's location.
"""

from app.config import get_settings
from app.models.alerts import ImdWarningItem
from app.models.chat import ChatLocationOut, ChatResponse, SourceStatus, WeatherSummary
from app.services import location_service
from app.services.query_understanding import QueryUnderstandingError, parse_query
from app.services.response_generator import ResponseGenerationError, generate_answer
from app.services.time_resolution import resolve_time_reference
from app.services.weather_context import gather_weather_context


async def handle_chat(message: str, current_lat: float, current_lon: float) -> ChatResponse:
    settings = get_settings()

    # --- 1. Query understanding ---
    try:
        parsed = await parse_query(message, settings.gemini_api_key, settings.gemini_model)
    except QueryUnderstandingError:
        return ChatResponse(
            answer=(
                "I couldn't understand that question well enough to look up "
                "weather data safely. Could you rephrase it?"
            ),
            location=ChatLocationOut(
                name=None, latitude=current_lat, longitude=current_lon, is_current_location=True
            ),
            intent="UNKNOWN",
            time_context=resolve_time_reference(None),
            weather_summary=WeatherSummary(),
            official_alerts=[],
            source_status=SourceStatus(weather="not_requested", imd_alerts="not_requested", ai="degraded"),
        )

    # --- 2. Location resolution: query_location vs current_location ---
    # current_lat/current_lon (from the request) are NEVER reassigned below —
    # target_lat/target_lon is a separate variable so current_location can
    # never be silently overwritten by a named query location.
    is_current = True
    location_name: str | None = None
    target_lat, target_lon = current_lat, current_lon

    if parsed.location_text:
        try:
            geocoded = await location_service.forward_geocode(
                parsed.location_text, settings.nominatim_user_agent
            )
            target_lat, target_lon = geocoded["latitude"], geocoded["longitude"]
            location_name = geocoded["city"] or parsed.location_text
            is_current = False
        except Exception:
            # Forward geocode failed — fall back to current_location rather
            # than guessing coordinates for a place we couldn't resolve.
            location_name = None
            is_current = True
    else:
        try:
            reverse = await location_service.reverse_geocode(
                current_lat, current_lon, settings.nominatim_user_agent
            )
            location_name = reverse.get("city")
        except Exception:
            location_name = None  # cosmetic only — coordinates still used below

    # --- 3. Time resolution (deterministic, not Gemini) ---
    resolved_time = resolve_time_reference(parsed.time_reference)

    # --- 4/5/6. Data selection + compact context (existing services, direct calls) ---
    context = await gather_weather_context(
        parsed, target_lat, target_lon, resolved_time, settings.weather_api_key
    )

    trimmed_alerts_for_gemini = [
        {k: v for k, v in a.items() if k != "polygon"} for a in context["alerts"]
    ]
    gemini_context = {
        "location": {"name": location_name, "latitude": target_lat, "longitude": target_lon},
        "question": message,
        "resolved_time": resolved_time.model_dump(),
        "current_weather": context["current"],
        "relevant_forecast": context["relevant_forecast"],
        "daily_summary": context["daily_summary"],
        "official_alerts_status": context["source_status"]["imd_alerts"],
        "official_alerts": trimmed_alerts_for_gemini,
    }

    # --- 7. Gemini grounded answer ---
    ai_status = "available"
    try:
        answer = await generate_answer(
            message, gemini_context, settings.gemini_api_key, settings.gemini_model
        )
    except ResponseGenerationError:
        ai_status = "degraded"
        answer = (
            "I've got the weather data below, but the AI summary isn't "
            "available right now — please check the figures directly."
        )

    # --- 8. Normalize response ---
    official_alerts = [ImdWarningItem(**{**a, "polygon": None}) for a in context["alerts"]]

    return ChatResponse(
        answer=answer,
        location=ChatLocationOut(
            name=location_name, latitude=target_lat, longitude=target_lon, is_current_location=is_current
        ),
        intent=parsed.intent,
        time_context=resolved_time,
        weather_summary=WeatherSummary(
            current=context["current"],
            relevant_forecast=context["relevant_forecast"] or None,
            daily_summary=context["daily_summary"],
        ),
        official_alerts=official_alerts,
        source_status=SourceStatus(
            weather=context["source_status"]["weather"],
            imd_alerts=context["source_status"]["imd_alerts"],
            ai=ai_status,
        ),
    )
