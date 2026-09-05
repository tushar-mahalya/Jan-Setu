from jan_setu.app import app
from jan_setu.config import get_settings

__all__ = ["app", "run"]


def run() -> None:
    import uvicorn

    # Autoreload spawns a supervisor that re-imports the app on file changes —
    # useful in dev, but never appropriate for the process actually serving
    # traffic. Same "development"/"test" check used elsewhere (e.g.
    # whatsapp/api.py's is_development_environment).
    settings = get_settings()
    reload = settings.environment in {"development", "test"}
    uvicorn.run("jan_setu.main:app", host="0.0.0.0", port=8000, reload=reload)
