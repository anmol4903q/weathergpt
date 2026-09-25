"""
Phase 5A — turns free-text into a structured, validated query.

Gemini's ONLY job here is extraction. It never sees weather data and never
answers the question at this stage. If its output doesn't validate against
our schema, we raise rather than trusting whatever text came back.
"""

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

_ALLOWED_INTENTS = {
    "CURRENT_WEATHER", "FORECAST", "RAIN_QUERY", "ALERT_QUERY",
    "GENERAL_WEATHER", "ACTIVITY_ADVICE", "TRAVEL_WEATHER", "AGRICULTURE_WEATHER",
}


class _GeminiQuerySchema(BaseModel):
    """Schema Gemini fills via structured output. Kept flat/simple — no
    nested unions beyond Optional[str] — to stay inside what the SDK's
    schema translator reliably supports."""
    intent: str
    location_text: str | None = None
    time_reference: str | None = None
    weather_variables: list[str] = []
    activity: str | None = None
    requires_current_weather: bool = False
    requires_hourly_forecast: bool = False
    requires_daily_forecast: bool = False
    requires_alerts: bool = False


class QueryUnderstandingError(Exception):
    """Gemini's extraction call failed or returned unusable output. Callers
    must NOT fall back to parsing the raw question text themselves — fail
    safely instead."""


_SYSTEM_INSTRUCTION = (
    "You extract structured weather-query information from a user's question. "
    "You do NOT answer the question. "
    f"intent must be exactly one of: {', '.join(sorted(_ALLOWED_INTENTS))}. "
    "Set location_text only if the user explicitly names a place; otherwise "
    "leave it null — do not guess a location. "
    "Only set requires_current_weather / requires_hourly_forecast / "
    "requires_daily_forecast / requires_alerts to true for data actually "
    "needed to answer this specific question — do not request everything "
    "by default. requires_alerts should be true whenever safety, risk, "
    "travel, or activity suitability is being asked about, even if the "
    "user didn't say the word 'warning'."
)


async def parse_query(message: str, api_key: str, model: str) -> _GeminiQuerySchema:
    client = genai.Client(api_key=api_key)

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_GeminiQuerySchema,
            ),
        )
    except Exception as exc:
        raise QueryUnderstandingError(f"Gemini query-extraction call failed: {exc}")

    if not response.text:
        raise QueryUnderstandingError("Gemini returned an empty response for query extraction")

    try:
        parsed = _GeminiQuerySchema.model_validate_json(response.text)
    except ValidationError as exc:
        raise QueryUnderstandingError(f"Gemini returned malformed structured output: {exc}")

    if parsed.intent not in _ALLOWED_INTENTS:
        raise QueryUnderstandingError(f"Gemini returned an unrecognized intent: {parsed.intent!r}")

    return parsed
