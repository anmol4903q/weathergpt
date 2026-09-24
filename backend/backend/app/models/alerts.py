from pydantic import BaseModel


class ImdWarningItem(BaseModel):
    """
    One CAP alert whose polygon contains the requested point.
    Fields below are IMD's own CAP values, preserved verbatim — never
    remapped or reworded into a different severity scale.
    """
    event: str
    severity: str          # IMD's own CAP severity string, verbatim (e.g. "Severe")
    urgency: str            # IMD's own CAP urgency string, verbatim
    certainty: str          # IMD's own CAP certainty string, verbatim
    area_description: str  # cap:areaDesc, verbatim (state/subdivision-level, NOT a district)
    headline: str
    description: str
    instruction: str | None = None
    onset: str | None = None
    expires: str | None = None
    sent: str | None = None
    polygon: list[list[float]] | None = None  # [[lat, lon], ...] as IMD published it


class ImdAlertsResponse(BaseModel):
    latitude: float
    longitude: float
    source_provider: str = "IMD"
    source_official: bool = True
    # "ok" = feed reached, 1+ alerts matched this point
    # "no_active_warning" = feed reached, reachable and parsed, nothing matched
    # "unavailable" = feed itself could not be reached/parsed — NOT the same as no warning
    status: str
    warnings: list[ImdWarningItem]
    attribution: str = "Source: India Meteorological Department (IMD), via public CAP alert feed"
    granularity_note: str = (
        "IMD's public CAP feed publishes state/subdivision-level bulletins "
        "(e.g. 'ODISHA', 'East Madhya Pradesh'), not per-district warnings. "
        "District-level official data requires IMD's gated API, restricted "
        "to government-domain email registration."
    )
