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
import re

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

_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# "in N hours" is only treated as a same-day, no-date-shift nudge below
# this threshold — beyond it we compute an actual target date/period
# instead of just flagging next_few_hours, since e.g. "in 20 hours" is
# very likely a different calendar day.
_IN_HOURS_NEXT_FEW_CUTOFF = 6


def _period_for_hour(hour: int) -> str:
    for period, (lo, hi) in PERIOD_HOUR_RANGES.items():
        if lo <= hour < hi:
            return period
    return "night"  # covers 0-6 and the 21-24 wraparound edge


def _period_hour_range(text: str) -> str | None:
    if "morning" in text:
        return "morning"
    if "afternoon" in text:
        return "afternoon"
    if "evening" in text:
        return "evening"
    if "night" in text:
        return "night"
    return None


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
    elif (in_hours_match := re.search(r"\bin (\d+)\s*hours?\b", text)):
        n = int(in_hours_match.group(1))
        target_dt = now + timedelta(hours=n)
        if n <= _IN_HOURS_NEXT_FEW_CUTOFF and target_dt.date() == now.date():
            next_few_hours = True
            note = f"Interpreted as roughly {n} hour(s) from now, IST."
        else:
            target_date = target_dt.date()
            period = _period_for_hour(target_dt.hour)
            note = f"Interpreted as {n} hour(s) from now ({target_dt.strftime('%Y-%m-%d %H:%M')} IST)."
    elif "this weekend" in text or "the weekend" in text:
        # Deterministic: if today is already Sat/Sun, "this weekend" means
        # today; otherwise the upcoming Saturday.
        days_to_saturday = (5 - now.weekday()) % 7
        target_date = (now + timedelta(days=days_to_saturday)).date()
        note = "Interpreted 'this weekend' as the upcoming Saturday, IST."
    elif (weekday_match := re.search(r"\bnext (" + "|".join(_WEEKDAY_NAMES) + r")\b", text)):
        target_weekday = _WEEKDAY_NAMES[weekday_match.group(1)]
        # "next <weekday>" means the next occurrence strictly after today,
        # including a full 7 days if today happens to be that weekday.
        days_ahead = (target_weekday - now.weekday()) % 7
        days_ahead = days_ahead if days_ahead > 0 else 7
        target_date = (now + timedelta(days=days_ahead)).date()
        period = _period_hour_range(text)
        note = f"Interpreted as next {weekday_match.group(1).capitalize()}, IST."
    elif "tomorrow" in text:
        target_date = (now + timedelta(days=1)).date()
        period = _period_hour_range(text)
    elif "tonight" in text:
        period = "night"
    elif "this evening" in text:
        period = "evening"
    elif "this morning" in text:
        period = "morning"
    elif "this afternoon" in text:
        period = "afternoon"
    elif (period := _period_hour_range(text)) is not None:
        pass  # today, restricted to the matched period
    elif "today" in text or "now" in text or "currently" in text:
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
