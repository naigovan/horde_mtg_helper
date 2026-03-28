"""Thin Scryfall client with local SQLite cache support."""

from __future__ import annotations

import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardCatalogEntry


SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
SET_CODE_SUFFIX_PATTERN = re.compile(r"^(?P<name>.+?)\s+\((?P<set>[A-Za-z0-9]+)\)$")


class ScryfallClient:
    """Resolve cards by name and cache essential fields locally."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_card(self, card_name: str) -> CardCatalogEntry:
        """Return cached card info or fetch it from Scryfall."""
        payload = self._resolve_payload(card_name)

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

    def _resolve_payload(self, card_name: str) -> dict[str, Any]:
        """Fetch card data, preferring set-specific matches for decklist-style names."""
        set_match = SET_CODE_SUFFIX_PATTERN.match(card_name.strip())
        if set_match:
            base_name = set_match.group("name").strip()
            set_code = set_match.group("set").strip().lower()
            existing = self._cached_entry_for_printing(base_name, set_code)
            if existing:
                return existing.raw_json
            payload = self._search_exact_printing(base_name, set_code)
            if payload:
                return payload
            card_name = base_name

        existing = self.session.scalar(
            select(CardCatalogEntry).where(CardCatalogEntry.name.ilike(card_name))
        )
        if existing:
            return existing.raw_json

        response = httpx.get(SCRYFALL_NAMED_URL, params={"fuzzy": card_name}, timeout=20.0)
        response.raise_for_status()
        return response.json()

    def _cached_entry_for_printing(self, base_name: str, set_code: str) -> CardCatalogEntry | None:
        """Return a cached exact-set printing if it already exists locally."""
        matches = self.session.scalars(
            select(CardCatalogEntry).where(CardCatalogEntry.name.ilike(base_name))
        ).all()
        for entry in matches:
            raw_json = entry.raw_json or {}
            if str(raw_json.get("set", "")).lower() == set_code:
                return entry
        return None

    @staticmethod
    def _search_exact_printing(base_name: str, set_code: str) -> dict[str, Any] | None:
        """Use Scryfall search for exact-name, exact-set matches such as tokens."""
        response = httpx.get(
            SCRYFALL_SEARCH_URL,
            params={"q": f'!"{base_name}" set:{set_code}'},
            timeout=20.0,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json().get("data") or []
        return data[0] if data else None

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
