"""FastAPI app entry point."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.db import Base, engine, run_migrations
from app.routes import decks, games


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    Base.metadata.create_all(bind=engine)
    run_migrations()

    app = FastAPI(title="MTG Horde Assistant")

    @app.middleware("http")
    async def disable_static_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.include_router(decks.router)
    app.include_router(games.router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    return app


app = create_app()
