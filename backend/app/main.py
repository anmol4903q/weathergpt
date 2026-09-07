from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, chat, health, location, weather
from app.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(location.router)
app.include_router(weather.router)
app.include_router(alerts.router)
app.include_router(chat.router)

@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "status": "running"}
