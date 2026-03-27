"""Database setup helpers."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = BASE_DIR / "horde.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH}")


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def run_migrations() -> None:
    """Apply lightweight additive schema changes for the SQLite MVP."""
    inspector = inspect(engine)
    with engine.begin() as connection:
        if "deck_definitions" in inspector.get_table_names():
            deck_columns = {column["name"] for column in inspector.get_columns("deck_definitions")}
            if "commander_name" not in deck_columns:
                connection.execute(text("ALTER TABLE deck_definitions ADD COLUMN commander_name VARCHAR(255)"))

        if "card_instances" in inspector.get_table_names():
            card_columns = {column["name"] for column in inspector.get_columns("card_instances")}
            if "is_commander" not in card_columns:
                connection.execute(text("ALTER TABLE card_instances ADD COLUMN is_commander BOOLEAN DEFAULT 0"))

        if "game_states" in inspector.get_table_names():
            game_columns = {column["name"] for column in inspector.get_columns("game_states")}
            if "commander_ids" not in game_columns:
                connection.execute(text("ALTER TABLE game_states ADD COLUMN commander_ids JSON"))
            if "battlefield_note" not in game_columns:
                connection.execute(text("ALTER TABLE game_states ADD COLUMN battlefield_note TEXT"))


def get_session() -> Session:
    """Yield a database session for request handlers."""
    with SessionLocal() as session:
        yield session
