"""
Phase 5A — turns free-text into a structured, validated query.

The AI's ONLY job here is extraction. It never sees weather data and never
answers the question at this stage. If its output doesn't validate against
our schema, we raise rather than trusting whatever text came back.

Provider: Groq (migrated from Gemini). Uses Groq's structured-output mode
(response_format={"type": "json_schema", ...}) so the result is still
schema-constrained at the API level, then re-validated by Pydantic here —
belt and suspenders, since a provider migration is exactly the kind of
change that should not be trusted on faith.
"""

from groq import AsyncGroq
from pydantic import ValidationError

from app.models.chat import ParsedWeatherQuery

_ALLOWED_INTENTS = {
    "CURRENT_WEATHER", "FORECAST", "RAIN_QUERY", "ALERT_QUERY",
    "GENERAL_WEATHER", "ACTIVITY_ADVICE", "TRAVEL_WEATHER", "AGRICULTURE_WEATHER",
}


class QueryUnderstandingError(Exception):
    """Groq's extraction call failed or returned unusable output. Callers
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


def _strict_json_schema() -> dict:
    """Groq's strict structured-output mode requires every property to be
    listed in 'required' (even the optional ones — 'optional' is expressed
    via a nullable type, not omission) and additionalProperties: False.
    Pydantic's own model_json_schema() doesn't produce that shape by
    default, so it's patched here rather than hand-written twice."""
    schema = ParsedWeatherQuery.model_json_schema()
    schema["required"] = list(schema["properties"].keys())
    schema["additionalProperties"] = False
    return schema


async def parse_query(message: str, api_key: str, model: str) -> ParsedWeatherQuery:
    client = AsyncGroq(api_key=api_key)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
                {"role": "user", "content": message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "parsed_weather_query",
                    "strict": True,
                    "schema": _strict_json_schema(),
                },
            },
        )
    except Exception as exc:
        raise QueryUnderstandingError(f"Groq query-extraction call failed: {exc}")

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise QueryUnderstandingError("Groq returned an empty response for query extraction")

    try:
        parsed = ParsedWeatherQuery.model_validate_json(content)
    except ValidationError as exc:
        raise QueryUnderstandingError(f"Groq returned malformed structured output: {exc}")

    if parsed.intent not in _ALLOWED_INTENTS:
        raise QueryUnderstandingError(f"Groq returned an unrecognized intent: {parsed.intent!r}")

    return parsed
