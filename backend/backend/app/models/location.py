from pydantic import BaseModel


class LocationResponse(BaseModel):
    city: str | None = None
    district: str | None = None
    state: str | None = None
    latitude: float
    longitude: float
    raw_display_name: str | None = None
