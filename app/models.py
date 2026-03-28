"""Database models for decks, cards, and saved games."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


class TimestampMixin:
    """Common timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeckDefinition(TimestampMixin, Base):
    """A saved Horde deck definition."""

    __tablename__ = "deck_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    decklist_text: Mapped[str] = mapped_column(Text)
    commander_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parsed_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    card_instances: Mapped[list["CardInstance"]] = relationship(
        back_populates="deck_definition", cascade="all, delete-orphan"
    )
    games: Mapped[list["GameState"]] = relationship(
        back_populates="deck_definition", cascade="all, delete-orphan"
    )


class CardCatalogEntry(TimestampMixin, Base):
    """Locally cached Scryfall metadata."""

    __tablename__ = "card_catalog_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    scryfall_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    oracle_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type_line: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mana_cost: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    card_instances: Mapped[list["CardInstance"]] = relationship(back_populates="catalog_entry")


class CardInstance(TimestampMixin, Base):
    """One physical copy of a card inside a deck or game."""

    __tablename__ = "card_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_definition_id: Mapped[int] = mapped_column(ForeignKey("deck_definitions.id"), index=True)
    catalog_entry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("card_catalog_entries.id"), nullable=True)
    game_state_id: Mapped[Optional[int]] = mapped_column(ForeignKey("game_states.id"), nullable=True, index=True)
    instance_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    card_name: Mapped[str] = mapped_column(String(255))
    scryfall_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    oracle_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type_line: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mana_cost: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    current_zone: Mapped[str] = mapped_column(String(32), default="library")
    zone_position: Mapped[int] = mapped_column(Integer, default=0)
    tapped: Mapped[bool] = mapped_column(Boolean, default=False)
    rested: Mapped[bool] = mapped_column(Boolean, default=False)
    phased_out: Mapped[bool] = mapped_column(Boolean, default=False)
    activated_this_turn: Mapped[bool] = mapped_column(Boolean, default=False)
    is_token: Mapped[bool] = mapped_column(Boolean, default=False)
    is_land: Mapped[bool] = mapped_column(Boolean, default=False)
    is_creature: Mapped[bool] = mapped_column(Boolean, default=False)
    is_noncreature_spell: Mapped[bool] = mapped_column(Boolean, default=False)
    is_legendary_creature: Mapped[bool] = mapped_column(Boolean, default=False)
    is_commander: Mapped[bool] = mapped_column(Boolean, default=False)
    counters_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deck_definition: Mapped["DeckDefinition"] = relationship(back_populates="card_instances")
    catalog_entry: Mapped[Optional["CardCatalogEntry"]] = relationship(back_populates="card_instances")
    game_state: Mapped[Optional["GameState"]] = relationship(back_populates="card_instances")


class GameState(TimestampMixin, Base):
    """A saved Horde game and zone ordering."""

    __tablename__ = "game_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_definition_id: Mapped[int] = mapped_column(ForeignKey("deck_definitions.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="Game")
    status: Mapped[str] = mapped_column(String(32), default="active")
    turn_number: Mapped[int] = mapped_column(Integer, default=1)
    wave_number: Mapped[int] = mapped_column(Integer, default=0)
    wave_policy: Mapped[str] = mapped_column(String(64), default="stop_on_noncreature_spell")
    wave_fixed_count: Mapped[int] = mapped_column(Integer, default=3)
    lands_to_battlefield: Mapped[bool] = mapped_column(Boolean, default=True)
    legendary_damage_mill_to_phased: Mapped[bool] = mapped_column(Boolean, default=False)
    destroyed_tokens_to_graveyard: Mapped[bool] = mapped_column(Boolean, default=False)
    library_order: Mapped[list[int]] = mapped_column(JSON, default=list)
    battlefield_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    graveyard_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    exile_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    vanished_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    commander_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    wave_pending_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    battlefield_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deck_definition: Mapped["DeckDefinition"] = relationship(back_populates="games")
    card_instances: Mapped[list["CardInstance"]] = relationship(
        back_populates="game_state", cascade="all, delete-orphan"
    )
    action_logs: Mapped[list["ActionLogEntry"]] = relationship(
        back_populates="game_state", order_by="ActionLogEntry.id", cascade="all, delete-orphan"
    )


class ActionLogEntry(Base):
    """Logged game action with undo snapshot."""

    __tablename__ = "action_log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_state_id: Mapped[int] = mapped_column(ForeignKey("game_states.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    before_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    game_state: Mapped["GameState"] = relationship(back_populates="action_logs")
