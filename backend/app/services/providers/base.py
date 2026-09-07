from abc import ABC, abstractmethod


class WeatherProvider(ABC):
    """
    Provider interface so weather_service.py — and the API contract the
    frontend consumes — never changes when the underlying data source does.
    Swapping OpenWeather's free tier for One Call 3.0, or a different
    provider entirely, means writing a new class here, nothing else.
    """

    @abstractmethod
    async def fetch_current(self, lat: float, lon: float) -> dict:
        ...

    @abstractmethod
    async def fetch_hourly(self, lat: float, lon: float) -> dict:
        ...

    @abstractmethod
    async def fetch_daily(self, lat: float, lon: float) -> dict:
        ...
