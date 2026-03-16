"""FastAPI app entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import Base, engine, run_migrations
from app.routes import decks, games


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    Base.metadata.create_all(bind=engine)
    run_migrations()

    app = FastAPI(title="MTG Horde Assistant")
    app.include_router(decks.router)
    app.include_router(games.router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    return app


app = create_app()
