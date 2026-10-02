from pydantic import BaseModel


class DistrictWarningInfo(BaseModel):
    """Raw fields as published by IMD's WFS layer. Day1..Day5 are the
    numeric codes exactly as returned — never remapped or reinterpreted.
    day1_label..day5_label are IMD's own published code->text mapping
    (reference metadata, supplied by the user as documented ground truth),
    shown ALONGSIDE the raw code, never replacing it."""
    district: str
    obj_id: str
    date: str | None = None
    updated_at: str | None = None
    day1: int
    day2: int
    day3: int
    day4: int
    day5: int
    # IMD's live WFS sends these as integers (e.g. 4), not hex color
    # strings as originally assumed from the documented schema alone.
    # Widened to accept whatever type is actually present — no coercion,
    # no reinterpretation of what the value means.
    day1_color: int | str | None = None
    day2_color: int | str | None = None
    day3_color: int | str | None = None
    day4_color: int | str | None = None
    day5_color: int | str | None = None
    day1_label: str | None = None
    day2_label: str | None = None
    day3_label: str | None = None
    day4_label: str | None = None
    day5_label: str | None = None


class DistrictWarningResponse(BaseModel):
    latitude: float
    longitude: float
    matched: bool
    warning: DistrictWarningInfo | None = None
    note: str = (
        "PROTOTYPE — sourced from IMD's WFS district_warnings_india layer, "
        "not yet wired into /weather/alerts."
    )

