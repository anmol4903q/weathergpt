from pydantic import BaseModel


class CurrentWeatherResponse(BaseModel):
    latitude: float
    longitude: float
    temperature_c: float
    feels_like_c: float
    humidity_pct: int
    wind_speed_ms: float
    wind_deg: int
    visibility_m: int | None = None
    pressure_hpa: int
    rain_1h_mm: float = 0.0
    condition_main: str
    condition_description: str


class HourlyForecastItem(BaseModel):
    time_utc: str
    temperature_c: float
    rain_probability_pct: int
    rain_3h_mm: float = 0.0
    condition_main: str
    condition_description: str


class HourlyForecastResponse(BaseModel):
    latitude: float
    longitude: float
    forecast: list[HourlyForecastItem]


class DailyForecastItem(BaseModel):
    date: str
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    total_rain_mm: float = 0.0
    rain_probability_pct: int
    condition_main: str
    condition_description: str
    entry_count: int  # number of 3-hour blocks aggregated; 8 = full day, fewer = partial


class DailyForecastResponse(BaseModel):
    latitude: float
    longitude: float
    days: list[DailyForecastItem]
    source: str
    note: str
