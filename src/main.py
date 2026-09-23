"""Application entry point.

The FastAPI application itself lives in src/api/app.py, which is where the
existing backend already was. This module only re-exports it so that both of
these work from the project root:

    python -m uvicorn src.main:app --reload
    python -m uvicorn src.api.app:app --reload

No second application is created; `app` below is the same object.
"""

from src.api.app import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.app:app", host="127.0.0.1", port=8000, reload=True)
