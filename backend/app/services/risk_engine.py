"""
Phase 6 — deterministic risk analysis.

This is WeatherGPT's OWN derived assessment, computed from the same
weather/alert data already gathered by weather_context.py. It is never
labeled as, or allowed to be confused with, an official IMD warning —
see response_generator.py's system instruction for how that distinction
is enforced in the final answer.

Design decisions, stated explicitly rather than left as magic numbers:
- Levels are LOW / MODERATE / HIGH / UNKNOWN. UNKNOWN means the specific
  signal needed wasn't available — it is never silently treated as LOW.
- Each contributing factor scores 0 (fine) / 1 (moderate) / 2 (high).
  Overall level = the MAX across factors, not a sum. Rationale: five
  mildly-elevated factors are not equivalent to one severe factor, and
  summing would let minor conditions compound into a false HIGH.
- An official IMD warning ("ok" status with 1+ matches) always forces
  HIGH, regardless of the numeric factors below — an official warning
  existing is inherently more significant than any threshold model here.
- Only applied to intents where a risk judgment is the actual point of
  the question (TRAVEL_WEATHER, ACTIVITY_ADVICE, AGRICULTURE_WEATHER).
  Every other intent gets risk=None — this field is purely additive.
"""

# All thresholds use the exact units the existing services already return:
# rain probability in %, rainfall in mm, wind in m/s, temperature in °C.
RAIN_PROB_MODERATE_PCT = 40
RAIN_PROB_HIGH_PCT = 70
RAIN_MM_MODERATE = 2.0
RAIN_MM_HIGH = 10.0
WIND_MODERATE_MS = 8.0    # ~29 km/h
WIND_HIGH_MS = 14.0       # ~50 km/h
HEAT_MODERATE_C = 35.0
HEAT_HIGH_C = 40.0
HUMIDITY_HIGH_PCT = 85
LOW_VISIBILITY_M = 2000
SEVERE_CONDITIONS = {"Thunderstorm", "Tornado", "Squall"}

_LEVEL_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "UNKNOWN": -1}
_RANK_LEVEL = {0: "LOW", 1: "MODERATE", 2: "HIGH"}


def _extract_signals(context: dict) -> dict:
    """Pulls one representative reading from whichever of current/
    relevant_forecast/daily_summary is actually present, preferring the
    most time-relevant one available. Missing values stay None — callers
    must treat None as "unknown", never as "zero risk"."""
    current = context.get("current") or {}
    forecast = (context.get("relevant_forecast") or [None])[0] or {}
    daily = context.get("daily_summary") or {}

    return {
        "rain_prob_pct": forecast.get("rain_probability_pct", daily.get("rain_probability_pct")),
        "rain_mm": forecast.get("rain_3h_mm", daily.get("total_rain_mm")),
        "wind_ms": current.get("wind_speed_ms"),
        "temp_c": current.get("temperature_c", forecast.get("temperature_c")),
        "humidity_pct": current.get("humidity_pct"),
        "visibility_m": current.get("visibility_m"),
        "condition_main": forecast.get("condition_main", daily.get("condition_main")),
    }


def _score_rain(signals: dict) -> tuple[int, str | None]:
    prob, mm = signals["rain_prob_pct"], signals["rain_mm"]
    if prob is None and mm is None:
        return -1, None
    if (prob is not None and prob >= RAIN_PROB_HIGH_PCT) or (mm is not None and mm >= RAIN_MM_HIGH):
        return 2, f"High rain chance/amount (prob={prob}%, {mm}mm)"
    if (prob is not None and prob >= RAIN_PROB_MODERATE_PCT) or (mm is not None and mm >= RAIN_MM_MODERATE):
        return 1, f"Moderate rain chance/amount (prob={prob}%, {mm}mm)"
    return 0, None


def _score_wind(signals: dict) -> tuple[int, str | None]:
    wind = signals["wind_ms"]
    if wind is None:
        return -1, None
    if wind >= WIND_HIGH_MS:
        return 2, f"High wind speed ({wind} m/s)"
    if wind >= WIND_MODERATE_MS:
        return 1, f"Moderate wind speed ({wind} m/s)"
    return 0, None


def _score_heat(signals: dict) -> tuple[int, str | None]:
    temp = signals["temp_c"]
    if temp is None:
        return -1, None
    if temp >= HEAT_HIGH_C:
        return 2, f"High temperature ({temp}°C)"
    if temp >= HEAT_MODERATE_C:
        return 1, f"Elevated temperature ({temp}°C)"
    return 0, None


def _score_severe_condition(signals: dict) -> tuple[int, str | None]:
    cond = signals["condition_main"]
    if cond is None:
        return -1, None
    if cond in SEVERE_CONDITIONS:
        return 2, f"Severe condition forecast: {cond}"
    return 0, None


def _score_visibility(signals: dict) -> tuple[int, str | None]:
    vis = signals["visibility_m"]
    if vis is None:
        return -1, None
    if vis < LOW_VISIBILITY_M:
        return 1, f"Reduced visibility ({vis}m)"
    return 0, None


def _score_humidity(signals: dict) -> tuple[int, str | None]:
    hum = signals["humidity_pct"]
    if hum is None:
        return -1, None
    if hum >= HUMIDITY_HIGH_PCT:
        return 1, f"High humidity ({hum}%)"
    return 0, None


def _combine(factor_results: list[tuple[int, str | None]], alerts: list[dict], alerts_status: str) -> dict:
    usable = [(score, reason) for score, reason in factor_results if score >= 0]
    reasons = [reason for score, reason in usable if reason]

    if alerts_status == "ok" and alerts:
        # Official warning always wins, regardless of computed factors.
        events = ", ".join(sorted({a.get("event", "warning") for a in alerts}))
        return {"level": "HIGH", "reasons": [f"Official IMD warning active: {events}"] + reasons}

    if not usable:
        # No underlying signal at all — never guess LOW by default.
        return {"level": "UNKNOWN", "reasons": ["Not enough weather data was available to assess risk."]}

    max_score = max(score for score, _ in usable)
    level = _RANK_LEVEL[max_score]

    if alerts_status == "unavailable":
        reasons = reasons + ["Official warning status could not be checked — this assessment does not account for it."]

    return {"level": level, "reasons": reasons or [f"No significant risk factors identified ({level})."]}


def assess_travel_risk(context: dict) -> dict:
    """Travel: rain, wind, visibility, severe conditions, official warnings."""
    signals = _extract_signals(context)
    factors = [_score_rain(signals), _score_wind(signals), _score_visibility(signals), _score_severe_condition(signals)]
    return _combine(factors, context.get("alerts") or [], context["source_status"].get("imd_alerts", "not_requested"))


def assess_activity_risk(context: dict) -> dict:
    """Outdoor activity: rain, thunderstorm/lightning, heat, wind, official warnings."""
    signals = _extract_signals(context)
    factors = [_score_rain(signals), _score_severe_condition(signals), _score_heat(signals), _score_wind(signals)]
    return _combine(factors, context.get("alerts") or [], context["source_status"].get("imd_alerts", "not_requested"))


def assess_agriculture_risk(context: dict) -> dict:
    """Agriculture: rain, wind, humidity, temperature. Official warnings
    still escalate (e.g. a cyclone warning matters for farm safety too),
    but agriculture-specific factors (humidity) are NOT applied to travel
    or activity questions — different intents, different rule sets."""
    signals = _extract_signals(context)
    factors = [_score_rain(signals), _score_wind(signals), _score_humidity(signals), _score_heat(signals)]
    return _combine(factors, context.get("alerts") or [], context["source_status"].get("imd_alerts", "not_requested"))


_INTENT_ASSESSORS = {
    "TRAVEL_WEATHER": assess_travel_risk,
    "ACTIVITY_ADVICE": assess_activity_risk,
    "AGRICULTURE_WEATHER": assess_agriculture_risk,
}


def compute_risk(intent: str, context: dict) -> dict | None:
    """Returns {"level", "reasons"} for risk-relevant intents, or None
    for every other intent — risk is additive, not forced onto questions
    that were never asking for a judgment call."""
    assessor = _INTENT_ASSESSORS.get(intent)
    if assessor is None:
        return None
    return assessor(context)
