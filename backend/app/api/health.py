from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "weathergpt-backend",
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }
