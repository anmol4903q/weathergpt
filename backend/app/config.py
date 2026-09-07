from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "WeatherGPT"
    env: str = "development"

    # Comma-separated origins in .env, parsed into a list here.
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"

    weather_api_key: str = ""
    geocoding_api_key: str = ""

    # Nominatim requires an identifying User-Agent on every request, not a key.
    # Format they ask for: <app name>/<version> (<contact>)
    nominatim_user_agent: str = "WeatherGPT-SIH/1.0 (set-a-real-contact@example.com)"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    # Cached so .env is only parsed once per process.
    return Settings()
