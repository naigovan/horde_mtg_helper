"""Deck management routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal, get_session
from app.deck_parser import parse_decklist
from app.game_engine import make_deck_card_instance
from app.models import DeckDefinition, GameState
from app.scryfall_client import ScryfallClient
from app.template_helpers import register_template_helpers


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_template_helpers(templates)


@dataclass(frozen=True)
class ResolvedCatalogCard:
    """Detached card metadata safe to reuse across short-lived sessions."""

    id: int
    scryfall_id: str
    name: str
    image_url: str | None
    oracle_text: str | None
    type_line: str | None
    mana_cost: str | None


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    """Render the home page."""
    return templates.TemplateResponse("index.html", _build_home_context(request, session))


@router.post("/decks")
def create_deck(
    request: Request,
    name: str = Form(...),
    decklist_text: str = Form(...),
    commander_name: str = Form(""),
    session: Session = Depends(get_session),
):
    """Create a saved deck and resolve its cards via Scryfall."""
    try:
        clean_name = name.strip() or "Untitled Horde Deck"
        clean_decklist = decklist_text.strip()
        clean_commander_name = commander_name.strip()
        parsed_items, resolved_items, commander_entry = _resolve_deck_blueprint(
            clean_decklist, clean_commander_name
        )
        deck = DeckDefinition(
            name=clean_name,
            decklist_text=clean_decklist,
            commander_name=clean_commander_name or None,
            parsed_items_json=[item.__dict__ for item in parsed_items],
        )
        session.add(deck)
        session.flush()

        _populate_deck_cards(session, deck, resolved_items, commander_entry)

        session.commit()
        return RedirectResponse(url=f"/decks/{deck.id}", status_code=303)
    except Exception as exc:
        session.rollback()
        context = _build_home_context(request, session)
        context.update(
            {
                "error": str(exc),
                "name": name,
                "decklist_text": decklist_text,
                "commander_name": commander_name,
            }
        )
        return templates.TemplateResponse(
            "index.html", context,
            status_code=400,
        )


@router.get("/decks/{deck_id}")
def view_deck(deck_id: int, request: Request, session: Session = Depends(get_session)):
    """Show one deck and start-game controls."""
    deck = session.scalar(
        select(DeckDefinition)
        .options(selectinload(DeckDefinition.card_instances), selectinload(DeckDefinition.games))
        .where(DeckDefinition.id == deck_id)
    )
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    base_cards = [card for card in deck.card_instances if card.game_state_id is None]
    return templates.TemplateResponse(
        "deck_detail.html",
        {"request": request, "deck": deck, "deck_card_count": len(base_cards)},
    )


@router.get("/decks/{deck_id}/edit")
def edit_deck_form(deck_id: int, request: Request, session: Session = Depends(get_session)):
    """Render the deck edit form."""
    deck = session.scalar(select(DeckDefinition).where(DeckDefinition.id == deck_id))
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return templates.TemplateResponse("deck_edit.html", {"request": request, "deck": deck})


@router.post("/decks/{deck_id}/edit")
def update_deck(
    deck_id: int,
    request: Request,
    name: str = Form(...),
    decklist_text: str = Form(...),
    commander_name: str = Form(""),
    session: Session = Depends(get_session),
):
    """Update a stored deck without changing already saved games."""
    deck = session.scalar(
        select(DeckDefinition).options(selectinload(DeckDefinition.card_instances)).where(DeckDefinition.id == deck_id)
    )
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    try:
        clean_name = name.strip() or "Untitled Horde Deck"
        clean_decklist = decklist_text.strip()
        clean_commander_name = commander_name.strip()
        parsed_items, resolved_items, commander_entry = _resolve_deck_blueprint(
            clean_decklist, clean_commander_name
        )

        deck.name = clean_name
        deck.decklist_text = clean_decklist
        deck.commander_name = clean_commander_name or None
        deck.parsed_items_json = [item.__dict__ for item in parsed_items]

        for card in [value for value in deck.card_instances if value.game_state_id is None]:
            session.delete(card)
        session.flush()

        _populate_deck_cards(session, deck, resolved_items, commander_entry)
        session.commit()
        return RedirectResponse(url=f"/decks/{deck.id}", status_code=303)
    except Exception as exc:
        session.rollback()
        return templates.TemplateResponse(
            "deck_edit.html",
            {"request": request, "deck": deck, "error": str(exc)},
            status_code=400,
        )


@router.post("/decks/{deck_id}/delete")
def delete_deck(deck_id: int, session: Session = Depends(get_session)):
    """Delete a stored deck and all games created from it."""
    deck = session.scalar(
        select(DeckDefinition)
        .options(
            selectinload(DeckDefinition.card_instances),
            selectinload(DeckDefinition.games).selectinload(GameState.card_instances),
            selectinload(DeckDefinition.games).selectinload(GameState.action_logs),
        )
        .where(DeckDefinition.id == deck_id)
    )
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    session.delete(deck)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


def _resolve_deck_blueprint(
    decklist_text: str, commander_name: str
) -> tuple[list, list[tuple[object, ResolvedCatalogCard]], ResolvedCatalogCard | None]:
    """Resolve deck entries before starting the main deck write transaction."""
    parsed_items = parse_decklist(decklist_text)
    resolved_by_name: dict[str, ResolvedCatalogCard] = {}

    def resolve_once(card_name: str) -> ResolvedCatalogCard:
        key = card_name.strip().casefold()
        if key not in resolved_by_name:
            resolved_by_name[key] = _resolve_catalog_card(card_name)
        return resolved_by_name[key]

    resolved_items = [(item, resolve_once(item.card_name)) for item in parsed_items]
    commander_entry = resolve_once(commander_name) if commander_name.strip() else None
    return parsed_items, resolved_items, commander_entry


def _resolve_catalog_card(card_name: str) -> ResolvedCatalogCard:
    """Resolve one card using a short-lived session so SQLite locks are brief."""
    with SessionLocal() as lookup_session:
        client = ScryfallClient(lookup_session)
        try:
            entry = client.resolve_card(card_name)
            lookup_session.commit()
        except Exception:
            lookup_session.rollback()
            raise
        return ResolvedCatalogCard(
            id=entry.id,
            scryfall_id=entry.scryfall_id,
            name=entry.name,
            image_url=entry.image_url,
            oracle_text=entry.oracle_text,
            type_line=entry.type_line,
            mana_cost=entry.mana_cost,
        )


def _populate_deck_cards(
    session: Session,
    deck: DeckDefinition,
    resolved_items: list[tuple[object, ResolvedCatalogCard]],
    commander_entry: ResolvedCatalogCard | None,
) -> None:
    """Store base deck cards plus an optional commander from pre-resolved metadata."""
    for item, entry in resolved_items:
        for copy_number in range(1, item.quantity + 1):
            session.add(make_deck_card_instance(deck, entry, copy_number))

    if commander_entry:
        commander = make_deck_card_instance(deck, commander_entry, 1)
        commander.is_commander = True
        commander.current_zone = "commander"
        session.add(commander)


def _build_home_context(request: Request, session: Session) -> dict:
    """Shared home-page context for normal loads and create-deck errors."""
    decks = session.scalars(
        select(DeckDefinition)
        .options(selectinload(DeckDefinition.card_instances), selectinload(DeckDefinition.games))
        .order_by(DeckDefinition.created_at.desc())
    ).all()
    deck_card_counts = {deck.id: len([card for card in deck.card_instances if card.game_state_id is None]) for deck in decks}
    return {
        "request": request,
        "decks": decks,
        "deck_card_counts": deck_card_counts,
        "saved_game_count": sum(len(deck.games) for deck in decks),
        "commander_deck_count": sum(1 for deck in decks if deck.commander_name),
        "total_card_count": sum(deck_card_counts.values()),
    }
