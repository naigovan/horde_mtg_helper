"""Thin Scryfall client with local SQLite cache support."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardCatalogEntry


SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"


class ScryfallClient:
    """Resolve cards by name and cache essential fields locally."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_card(self, card_name: str) -> CardCatalogEntry:
        """Return cached card info or fetch it from Scryfall."""
        existing = self.session.scalar(
            select(CardCatalogEntry).where(CardCatalogEntry.name.ilike(card_name))
        )
        if existing:
            return existing

        response = httpx.get(SCRYFALL_NAMED_URL, params={"fuzzy": card_name}, timeout=20.0)
        response.raise_for_status()
        payload = response.json()

        existing_by_id = self.session.scalar(
            select(CardCatalogEntry).where(CardCatalogEntry.scryfall_id == payload["id"])
        )
        if existing_by_id:
            return existing_by_id

        entry = CardCatalogEntry(
            scryfall_id=payload["id"],
            name=payload["name"],
            image_url=self._extract_image_url(payload),
            oracle_text=payload.get("oracle_text"),
            type_line=payload.get("type_line"),
            mana_cost=payload.get("mana_cost"),
            raw_json=payload,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    @staticmethod
    def _extract_image_url(payload: dict[str, Any]) -> str | None:
        """Pick a display-friendly image URL from normal or double-faced cards."""
        if payload.get("image_uris"):
            return payload["image_uris"].get("normal")
        if payload.get("card_faces"):
            for face in payload["card_faces"]:
                image_uris = face.get("image_uris") or {}
                if image_uris.get("normal"):
                    return image_uris["normal"]
        return None
