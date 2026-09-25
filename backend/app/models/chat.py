from pydantic import BaseModel, Field

from app.models.alerts import ImdWarningItem


class ChatLocationIn(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ChatRequest(BaseModel):
    message: str
    # Sent per-request, never stored server-side as global state — multiple
    # concurrent users must never share or overwrite each other's location.
    current_location: ChatLocationIn


class ParsedWeatherQuery(BaseModel):
    """What Gemini extracts from the user's raw question. Validated before
    anything downstream trusts it."""
    intent: str
    location_text: str | None = None
    time_reference: str | None = None
    weather_variables: list[str] = []
    activity: str | None = None
    requires_current_weather: bool = False
    requires_hourly_forecast: bool = False
    requires_daily_forecast: bool = False
    requires_alerts: bool = False


class ResolvedTime(BaseModel):
    relative_expression: str | None = None
    target_date: str  # ISO date, resolved in Asia/Kolkata
    period: str | None = None  # "morning" | "afternoon" | "evening" | "night" | None
    next_few_hours: bool = False
    note: str | None = None
    within_forecast_horizon: bool = True


class ChatLocationOut(BaseModel):
    name: str | None = None
    latitude: float
    longitude: float
    is_current_location: bool


class WeatherSummary(BaseModel):
    current: dict | None = None
    relevant_forecast: list[dict] | None = None
    daily_summary: dict | None = None


class SourceStatus(BaseModel):
    weather: str        # "available" | "unavailable" | "not_requested"
    imd_alerts: str      # "ok" | "no_active_warning" | "unavailable" | "not_requested"
    ai: str               # "available" | "degraded"


class RiskAssessment(BaseModel):
    """Phase 6 — WeatherGPT's own deterministic risk judgment, never an
    official warning. Only populated for TRAVEL_WEATHER, ACTIVITY_ADVICE,
    and AGRICULTURE_WEATHER intents; None everywhere else."""
    level: str  # "LOW" | "MODERATE" | "HIGH" | "UNKNOWN"
    reasons: list[str] = []


class ChatResponse(BaseModel):
    answer: str
    location: ChatLocationOut
    intent: str
    time_context: ResolvedTime
    weather_summary: WeatherSummary
    official_alerts: list[ImdWarningItem] = []
    source_status: SourceStatus
    risk: RiskAssessment | None = None
