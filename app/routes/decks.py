"""Deck management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.deck_parser import parse_decklist
from app.game_engine import make_deck_card_instance
from app.models import DeckDefinition, GameState
from app.scryfall_client import ScryfallClient
from app.template_helpers import register_template_helpers


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_template_helpers(templates)


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
        parsed_items = parse_decklist(decklist_text)
        deck = DeckDefinition(
            name=name.strip() or "Untitled Horde Deck",
            decklist_text=decklist_text.strip(),
            commander_name=commander_name.strip() or None,
            parsed_items_json=[item.__dict__ for item in parsed_items],
        )
        session.add(deck)
        session.flush()

        _populate_deck_cards(session, deck, decklist_text, commander_name)

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
        deck.name = name.strip() or "Untitled Horde Deck"
        deck.decklist_text = decklist_text.strip()
        deck.commander_name = commander_name.strip() or None
        parsed_items = parse_decklist(deck.decklist_text)
        deck.parsed_items_json = [item.__dict__ for item in parsed_items]

        for card in [value for value in deck.card_instances if value.game_state_id is None]:
            session.delete(card)
        session.flush()

        _populate_deck_cards(session, deck, deck.decklist_text, commander_name)
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


def _populate_deck_cards(session: Session, deck: DeckDefinition, decklist_text: str, commander_name: str) -> None:
    """Resolve and store base deck cards plus an optional commander."""
    parsed_items = parse_decklist(decklist_text)
    client = ScryfallClient(session)
    for item in parsed_items:
        entry = client.resolve_card(item.card_name)
        for copy_number in range(1, item.quantity + 1):
            session.add(make_deck_card_instance(deck, entry, copy_number))

    if commander_name.strip():
        commander_entry = client.resolve_card(commander_name.strip())
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
