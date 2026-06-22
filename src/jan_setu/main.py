from jan_setu.app import app

__all__ = ["app", "run"]


def run() -> None:
    import uvicorn

    uvicorn.run("jan_setu.main:app", host="0.0.0.0", port=8000, reload=True)
