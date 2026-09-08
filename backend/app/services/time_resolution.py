"""
Phase 5B — deterministic (NOT AI) resolution of natural-language time
references into a concrete date + period, in IST (Asia/Kolkata).

This is rule-based on purpose: Gemini must never be trusted to compute
"tomorrow" or invent forecast timing — a wrong date here would silently
poison the weather lookup and the final answer. This also lets us flag
dates beyond OpenWeather's forecast horizon before Gemini ever sees them,
instead of asking it to talk about data that doesn't exist.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.chat import ResolvedTime

IST = ZoneInfo("Asia/Kolkata")

# OpenWeather's free 5-day/3-hour forecast rarely covers a clean 5 full
# calendar days from "now" (first/last day are usually partial — see
# weather_service._aggregate_daily). Treat 5 as the safe upper bound.
FORECAST_HORIZON_DAYS = 5

PERIOD_HOUR_RANGES = {
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 24),
}


def resolve_time_reference(time_reference: str | None) -> ResolvedTime:
    now = datetime.now(IST)
    text = (time_reference or "").strip().lower()

    target_date = now.date()
    period: str | None = None
    next_few_hours = False
    note: str | None = None

    if not text:
        note = "No time reference given — assumed today, IST."
    elif "next few hours" in text or "next couple" in text or "next couple of hours" in text:
        next_few_hours = True
        note = "Interpreted as the next few hours from now, IST."
    elif "tomorrow" in text:
        target_date = (now + timedelta(days=1)).date()
        if "morning" in text:
            period = "morning"
        elif "afternoon" in text:
            period = "afternoon"
        elif "evening" in text:
            period = "evening"
        elif "night" in text:
            period = "night"
    elif "tonight" in text:
        period = "night"
    elif "this evening" in text:
        period = "evening"
    elif "this morning" in text:
        period = "morning"
    elif "this afternoon" in text:
        period = "afternoon"
    elif "evening" in text:
        period = "evening"
    elif "morning" in text:
        period = "morning"
    elif "afternoon" in text:
        period = "afternoon"
    elif "today" in text:
        pass  # target_date already today, no period restriction
    else:
        note = f"Unrecognized time phrase '{time_reference}' — assumed today, IST."

    within_horizon = (target_date - now.date()).days < FORECAST_HORIZON_DAYS

    return ResolvedTime(
        relative_expression=time_reference,
        target_date=target_date.isoformat(),
        period=period,
        next_few_hours=next_few_hours,
        note=note,
        within_forecast_horizon=within_horizon,
    )
