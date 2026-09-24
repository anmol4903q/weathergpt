# WeatherGPT Backend — Phase 1

## Run it
```
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Then check:
- http://127.0.0.1:8000/          -> {"service": "WeatherGPT", "status": "running"}
- http://127.0.0.1:8000/health    -> {"status": "ok", ...}
- http://127.0.0.1:8000/docs      -> interactive Swagger UI (free, from FastAPI)

## What's real vs. stubbed
- `app/main.py`, `app/config.py`, `app/api/health.py` — real, tested, working.
- `app/api/{weather,location,alerts,chat,climate,agriculture}.py` — empty routers,
  NOT wired into `main.py`. Fill these in per-phase (Phase 3 = weather, Phase 2 =
  location, etc.) and add `app.include_router(...)` in `main.py` when ready.
- `app/services/*.py` — empty. Business logic goes here, not in the route
  handlers, so it's unit-testable without booting the whole app.
- `app/models/` — empty. Pydantic request/response schemas go here once
  endpoints have a real shape.

## CORS
`CORS_ORIGINS` in `.env` is a comma-separated list. Update it to match wherever
you're actually serving the static frontend from (Live Server port, etc.) —
don't leave it wide open once this stops being local-only.
