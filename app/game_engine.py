"""Core Horde game-state operations."""

from __future__ import annotations

import random
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import ActionLogEntry, CardCatalogEntry, CardInstance, DeckDefinition, GameState


ZONE_LIBRARY = "library"
ZONE_BATTLEFIELD = "battlefield"
ZONE_GRAVEYARD = "graveyard"
ZONE_EXILE = "exile"
ZONE_COMMANDER = "commander"
ZONE_WAVE = "wave"


def create_game_from_deck(
    session: Session,
    deck: DeckDefinition,
    *,
    name: str,
    legendary_damage_mill_to_phased: bool = False,
) -> GameState:
    """Create a fresh game by cloning a deck's card instances."""
    source_cards = [card for card in deck.card_instances if card.game_state_id is None]
    if not source_cards:
        raise ValueError("Deck has no card instances")

    game = GameState(
        deck_definition_id=deck.id,
        name=name,
        wave_policy="single_turn",
        wave_fixed_count=1,
        lands_to_battlefield=False,
        legendary_damage_mill_to_phased=legendary_damage_mill_to_phased,
        library_order=[],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        commander_ids=[],
        wave_pending_ids=[],
    )
    session.add(game)
    session.flush()

    clones: list[CardInstance] = []
    for card in source_cards:
        initial_zone = ZONE_COMMANDER if card.is_commander else ZONE_LIBRARY
        clone = CardInstance(
            deck_definition_id=deck.id,
            catalog_entry_id=card.catalog_entry_id,
            game_state_id=game.id,
            instance_uid=f"{card.instance_uid}-game-{uuid4().hex[:8]}",
            card_name=card.card_name,
            scryfall_id=card.scryfall_id,
            image_url=card.image_url,
            oracle_text=card.oracle_text,
            type_line=card.type_line,
            mana_cost=card.mana_cost,
            current_zone=initial_zone,
            zone_position=0,
            tapped=False,
            rested=False,
            phased_out=False,
            activated_this_turn=False,
            is_token=card.is_token,
            is_land=card.is_land,
            is_creature=card.is_creature,
            is_noncreature_spell=card.is_noncreature_spell,
            is_legendary_creature=card.is_legendary_creature,
            is_commander=card.is_commander,
            counters_json=dict(card.counters_json or {}),
            notes=card.notes,
        )
        clones.append(clone)
        session.add(clone)
    session.flush()

    library_ids = [card.id for card in clones if not card.is_commander]
    commander_ids = [card.id for card in clones if card.is_commander]
    random.shuffle(library_ids)
    game.library_order = library_ids
    game.commander_ids = commander_ids
    _sync_zone_positions(game, clones)
    _log_action(session, game, "game_created", f"Started new game from deck '{deck.name}'.")
    session.flush()
    return game


def shuffle_library(session: Session, game: GameState) -> None:
    """Shuffle the library in place."""
    before = snapshot_game(session, game)
    shuffled = list(game.library_order or [])
    random.shuffle(shuffled)
    game.library_order = shuffled
    _sync_zone_positions(game, game.card_instances)
    _log_action(session, game, "shuffle", "Shuffled library.", before)


def take_turn(session: Session, game: GameState) -> int | None:
    """Process exactly one card from the top of the library."""
    before = snapshot_game(session, game)
    library_order = list(game.library_order or [])
    if not library_order:
        _log_action(session, game, "turn", "Turn clicked but the library is empty.", before)
        return None

    game.turn_number = (game.turn_number or 0) + 1
    card_id = library_order.pop(0)
    game.library_order = list(library_order)
    card = _card_by_id(game, card_id)
    game.wave_pending_ids = []
    move_card(game, card, ZONE_BATTLEFIELD)
    card.rested = True
    card.tapped = False
    message = f"Turn {game.turn_number}: {card.card_name} entered the battlefield."

    _sync_zone_positions(game, game.card_instances)
    _log_action(session, game, "turn", message, before)
    return card_id


def mill_cards(session: Session, game: GameState, count: int, *, from_damage: bool = False) -> list[int]:
    """Mill cards from the top of the library into the graveyard."""
    if count <= 0:
        return []
    before = snapshot_game(session, game)
    milled: list[int] = []
    library_order = list(game.library_order or [])
    for _ in range(min(count, len(library_order))):
        card_id = library_order.pop(0)
        game.library_order = list(library_order)
        card = _card_by_id(game, card_id)
        if from_damage and game.legendary_damage_mill_to_phased and card.is_legendary_creature:
            move_card(game, card, ZONE_BATTLEFIELD)
            card.phased_out = True
            card.rested = True
        else:
            move_card(game, card, ZONE_GRAVEYARD)
        milled.append(card_id)
    _sync_zone_positions(game, game.card_instances)
    verb = "Damage milled" if from_damage else "Milled"
    _log_action(session, game, "mill", f"{verb} {len(milled)} card(s).", before)
    return milled


def move_card_to_zone(session: Session, game: GameState, card_id: int, destination: str) -> None:
    """Move a card between visible zones."""
    before = snapshot_game(session, game)
    card = _card_by_id(game, card_id)
    move_card(game, card, destination)
    if destination == ZONE_BATTLEFIELD:
        card.rested = True
    _sync_zone_positions(game, game.card_instances)
    _log_action(session, game, "move_card", f"Moved {card.card_name} to {destination}.", before)


def move_card_to_library_bottom(session: Session, game: GameState, card_id: int) -> None:
    """Move a card to the bottom of the library."""
    before = snapshot_game(session, game)
    card = _card_by_id(game, card_id)
    move_card(game, card, ZONE_LIBRARY, to_bottom=True)
    card.rested = False
    card.tapped = False
    card.phased_out = False
    _sync_zone_positions(game, game.card_instances)
    _log_action(session, game, "move_card", f"Moved {card.card_name} to library bottom.", before)


def toggle_flag(session: Session, game: GameState, card_id: int, flag_name: str) -> None:
    """Toggle one boolean card flag."""
    before = snapshot_game(session, game)
    card = _card_by_id(game, card_id)
    value = bool(getattr(card, flag_name))
    setattr(card, flag_name, not value)
    _log_action(session, game, "toggle_flag", f"Toggled {flag_name} for {card.card_name}.", before)


def untap_all(session: Session, game: GameState) -> None:
    """Untap all battlefield permanents."""
    before = snapshot_game(session, game)
    for card in game.card_instances:
        if card.current_zone == ZONE_BATTLEFIELD:
            card.tapped = False
            card.activated_this_turn = False
    _log_action(session, game, "untap_all", "Untapped all battlefield cards.", before)


def clear_rested(session: Session, game: GameState) -> None:
    """Clear rested markers from the battlefield."""
    before = snapshot_game(session, game)
    for card in game.card_instances:
        if card.current_zone == ZONE_BATTLEFIELD:
            card.rested = False
    _log_action(session, game, "clear_rested", "Cleared rested status on battlefield.", before)


def undo_last_action(session: Session, game: GameState) -> bool:
    """Restore the game to the snapshot before the latest logged action."""
    logs = list(game.action_logs)
    if len(logs) <= 1:
        return False
    latest = logs[-1]
    restore_snapshot(game, latest.before_state_json)
    session.delete(latest)
    _sync_zone_positions(game, game.card_instances)
    session.flush()
    return True


def snapshot_game(session: Session | None, game: GameState) -> dict:
    """Capture enough state to support a simple undo feature."""
    if session is not None:
        session.flush()
    return {
        "game": {
            "turn_number": game.turn_number,
            "wave_number": game.wave_number,
            "library_order": list(game.library_order or []),
            "battlefield_ids": list(game.battlefield_ids or []),
            "graveyard_ids": list(game.graveyard_ids or []),
            "exile_ids": list(game.exile_ids or []),
            "commander_ids": list(game.commander_ids or []),
            "wave_pending_ids": list(game.wave_pending_ids or []),
        },
        "cards": {
            card.id: {
                "current_zone": card.current_zone,
                "zone_position": card.zone_position,
                "tapped": card.tapped,
                "rested": card.rested,
                "phased_out": card.phased_out,
                "activated_this_turn": card.activated_this_turn,
            }
            for card in game.card_instances
        },
    }


def restore_snapshot(game: GameState, snapshot: dict) -> None:
    """Restore a game snapshot."""
    payload = snapshot.get("game", {})
    game.turn_number = payload.get("turn_number", 1)
    game.wave_number = payload.get("wave_number", 0)
    game.library_order = list(payload.get("library_order", []) or [])
    game.battlefield_ids = list(payload.get("battlefield_ids", []) or [])
    game.graveyard_ids = list(payload.get("graveyard_ids", []) or [])
    game.exile_ids = list(payload.get("exile_ids", []) or [])
    game.commander_ids = list(payload.get("commander_ids", []) or [])
    game.wave_pending_ids = list(payload.get("wave_pending_ids", []) or [])
    card_payload = snapshot.get("cards", {})
    for card in game.card_instances:
        values = card_payload.get(card.id, {})
        card.current_zone = values.get("current_zone", card.current_zone)
        card.zone_position = values.get("zone_position", card.zone_position)
        card.tapped = values.get("tapped", card.tapped)
        card.rested = values.get("rested", card.rested)
        card.phased_out = values.get("phased_out", card.phased_out)
        card.activated_this_turn = values.get("activated_this_turn", card.activated_this_turn)


def card_flags_from_catalog(entry: CardCatalogEntry) -> dict[str, bool]:
    """Map Scryfall type data into MVP card flags."""
    type_line = entry.type_line or ""
    return {
        "is_token": "Token" in type_line or entry.name.lower() == "token",
        "is_land": "Land" in type_line,
        "is_creature": "Creature" in type_line,
        "is_noncreature_spell": "Instant" in type_line or "Sorcery" in type_line,
        "is_legendary_creature": "Legendary" in type_line and "Creature" in type_line,
    }


def make_deck_card_instance(deck: DeckDefinition, entry: CardCatalogEntry, copy_number: int) -> CardInstance:
    """Create one stored deck card instance from cached Scryfall data."""
    flags = card_flags_from_catalog(entry)
    return CardInstance(
        deck_definition_id=deck.id,
        catalog_entry_id=entry.id,
        instance_uid=f"deck-{deck.id}-{entry.scryfall_id}-{copy_number}-{uuid4().hex[:8]}",
        card_name=entry.name,
        scryfall_id=entry.scryfall_id,
        image_url=entry.image_url,
        oracle_text=entry.oracle_text,
        type_line=entry.type_line,
        mana_cost=entry.mana_cost,
        current_zone=ZONE_LIBRARY,
        is_token=flags["is_token"],
        is_land=flags["is_land"],
        is_creature=flags["is_creature"],
        is_noncreature_spell=flags["is_noncreature_spell"],
        is_legendary_creature=flags["is_legendary_creature"],
    )


def move_card(game: GameState, card: CardInstance, destination: str, *, to_bottom: bool = False) -> None:
    """Update zone collections and the card zone field."""
    for zone_list_name in ("library_order", "battlefield_ids", "graveyard_ids", "exile_ids", "commander_ids", "wave_pending_ids"):
        zone_list = list(getattr(game, zone_list_name) or [])
        if card.id in zone_list:
            zone_list = [value for value in zone_list if value != card.id]
            setattr(game, zone_list_name, zone_list)

    if destination == ZONE_LIBRARY:
        if to_bottom:
            game.library_order = list(game.library_order or []) + [card.id]
        else:
            game.library_order = [card.id] + list(game.library_order or [])
    elif destination == ZONE_BATTLEFIELD:
        game.battlefield_ids = list(game.battlefield_ids or []) + [card.id]
    elif destination == ZONE_GRAVEYARD:
        game.graveyard_ids = list(game.graveyard_ids or []) + [card.id]
    elif destination == ZONE_EXILE:
        game.exile_ids = list(game.exile_ids or []) + [card.id]
    elif destination == ZONE_COMMANDER:
        game.commander_ids = list(game.commander_ids or []) + [card.id]
    elif destination == ZONE_WAVE:
        game.wave_pending_ids = list(game.wave_pending_ids or []) + [card.id]

    card.current_zone = destination


def _sync_zone_positions(game: GameState, cards: list[CardInstance]) -> None:
    lookup = {card.id: card for card in cards}
    for zone_name in ("library_order", "battlefield_ids", "graveyard_ids", "exile_ids", "commander_ids", "wave_pending_ids"):
        for position, card_id in enumerate(getattr(game, zone_name) or []):
            lookup[card_id].zone_position = position


def _card_by_id(game: GameState, card_id: int) -> CardInstance:
    for card in game.card_instances:
        if card.id == card_id:
            return card
    raise ValueError(f"Card id {card_id} not found in game")


def _log_action(session: Session, game: GameState, action_type: str, message: str, before: dict | None = None) -> None:
    session.add(
        ActionLogEntry(
            game_state_id=game.id,
            action_type=action_type,
            message=message,
            before_state_json=before or snapshot_game(session, game),
        )
    )


def save_game(session: Session, game: GameState) -> None:
    """Log an explicit save action even though game state is already persisted."""
    before = snapshot_game(session, game)
    _log_action(session, game, "save_game", "Saved game.", before)
