"""Game interaction routes."""

from __future__ import annotations

from collections import OrderedDict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.game_engine import (
    clear_rested,
    create_game_from_deck,
    mill_cards,
    move_card_to_library_bottom,
    move_card_to_zone,
    save_game,
    shuffle_library,
    tap_all,
    take_turn,
    toggle_flag,
    undo_last_action,
    untap_all,
)
from app.models import DeckDefinition, GameState


router = APIRouter(prefix="/games")
templates = Jinja2Templates(directory="app/templates")
VISIBLE_ZONE_ORDER = {
    "library": 0,
    "battlefield": 1,
    "graveyard": 2,
    "exile": 3,
    "commander": 4,
}


@router.post("/from-deck/{deck_id}")
def create_game(
    deck_id: int,
    name: str = Form("New Game"),
    legendary_damage_mill_to_phased: bool = Form(False),
    session: Session = Depends(get_session),
):
    """Create a new game from a deck."""
    deck = session.scalar(
        select(DeckDefinition).options(selectinload(DeckDefinition.card_instances)).where(DeckDefinition.id == deck_id)
    )
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    game = create_game_from_deck(
        session,
        deck,
        name=name,
        legendary_damage_mill_to_phased=legendary_damage_mill_to_phased,
    )
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.get("/{game_id}")
def view_game(game_id: int, request: Request, session: Session = Depends(get_session)):
    """Render a saved game."""
    game = _load_game(session, game_id)
    battlefield = [card for card in game.card_instances if card.id in game.battlefield_ids]
    graveyard = [card for card in game.card_instances if card.id in game.graveyard_ids]
    exile = [card for card in game.card_instances if card.id in game.exile_ids]
    commander = [card for card in game.card_instances if card.id in (game.commander_ids or [])]
    cards_by_id = {card.id: card for card in game.card_instances}
    library_tokens_map: OrderedDict[tuple[str, str], dict] = OrderedDict()
    for card_id in game.library_order or []:
        card = cards_by_id.get(card_id)
        if not card or not card.is_token:
            continue
        key = (card.card_name, card.type_line or "")
        if key not in library_tokens_map:
            library_tokens_map[key] = {"card": card, "count": 0}
        library_tokens_map[key]["count"] += 1
    library_tokens = list(library_tokens_map.values())
    return templates.TemplateResponse(
        "game_detail.html",
        {
            "request": request,
            "game": game,
            "battlefield": sorted(battlefield, key=lambda c: c.zone_position),
            "graveyard": sorted(graveyard, key=lambda c: c.zone_position),
            "exile": sorted(exile, key=lambda c: c.zone_position),
            "commander": sorted(commander, key=lambda c: c.zone_position),
            "library_tokens": library_tokens,
            "game_view_state": _build_game_view_state(game),
        },
    )


@router.post("/{game_id}/turn")
def take_turn_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    take_turn(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/shuffle")
def shuffle_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    shuffle_library(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/mill")
def mill_action(game_id: int, count: int = Form(...), as_damage: bool = Form(False), session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    mill_cards(session, game, count, from_damage=as_damage)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/untap-all")
def untap_all_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    untap_all(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/tap-all")
def tap_all_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    tap_all(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/clear-rested")
def clear_rested_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    clear_rested(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/undo")
def undo_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    undo_last_action(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/save")
def save_action(game_id: int, session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    save_game(session, game)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/delete")
def delete_game(game_id: int, session: Session = Depends(get_session)):
    """Delete a saved game and its per-game card copies."""
    game = session.scalar(
        select(GameState)
        .options(selectinload(GameState.card_instances), selectinload(GameState.action_logs))
        .where(GameState.id == game_id)
    )
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    deck_id = game.deck_definition_id
    session.delete(game)
    session.commit()
    return RedirectResponse(url=f"/decks/{deck_id}", status_code=303)


@router.post("/{game_id}/cards/{card_id}/toggle")
def toggle_card_flag(game_id: int, card_id: int, flag_name: str = Form(...), session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    toggle_flag(session, game, card_id, flag_name)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/cards/{card_id}/move")
def move_card_action(game_id: int, card_id: int, destination: str = Form(...), session: Session = Depends(get_session)):
    game = _load_game(session, game_id)
    move_card_to_zone(session, game, card_id, destination)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/cards/{card_id}/library-bottom")
def move_card_library_bottom_action(game_id: int, card_id: int, session: Session = Depends(get_session)):
    """Move a card to the bottom of the library."""
    game = _load_game(session, game_id)
    move_card_to_library_bottom(session, game, card_id)
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


@router.post("/{game_id}/cards/{card_id}/note")
def update_card_note(game_id: int, card_id: int, note: str = Form(""), session: Session = Depends(get_session)):
    """Update a short per-card note for battlefield tracking."""
    game = _load_game(session, game_id)
    card = next((value for value in game.card_instances if value.id == card_id), None)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.notes = (note or "").strip()[:10] or None
    session.commit()
    return RedirectResponse(url=f"/games/{game.id}", status_code=303)


def _load_game(session: Session, game_id: int) -> GameState:
    game = session.scalar(
        select(GameState)
        .options(selectinload(GameState.card_instances), selectinload(GameState.action_logs))
        .where(GameState.id == game_id)
    )
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _build_game_view_state(game: GameState) -> dict:
    """Provide a compact but complete card + zone snapshot for UI animation and tests."""

    library_ids = list(game.library_order or [])
    battlefield_ids = list(game.battlefield_ids or [])
    graveyard_ids = list(game.graveyard_ids or [])
    exile_ids = list(game.exile_ids or [])
    commander_ids = list(game.commander_ids or [])
    cards = sorted(
        game.card_instances,
        key=lambda card: (
            VISIBLE_ZONE_ORDER.get(card.current_zone, 99),
            card.zone_position,
            card.id,
        ),
    )
    return {
        "gameId": game.id,
        "name": game.name,
        "turn": game.turn_number,
        "wave": game.wave_number,
        "latestAction": game.action_logs[-1].message if game.action_logs else None,
        "counts": {
            "library": len(library_ids),
            "battlefield": len(battlefield_ids),
            "graveyard": len(graveyard_ids),
            "exile": len(exile_ids),
            "commander": len(commander_ids),
        },
        "zones": {
            "library": library_ids,
            "battlefield": battlefield_ids,
            "graveyard": graveyard_ids,
            "exile": exile_ids,
            "commander": commander_ids,
        },
        "cards": [
            {
                "id": card.id,
                "name": card.card_name,
                "zone": card.current_zone,
                "zonePosition": card.zone_position,
                "tapped": card.tapped,
                "phasedOut": card.phased_out,
                "isCommander": card.is_commander,
                "isCreature": card.is_creature,
                "isToken": card.is_token,
                "typeLine": card.type_line or "",
                "note": card.notes or "",
            }
            for card in cards
        ],
    }
