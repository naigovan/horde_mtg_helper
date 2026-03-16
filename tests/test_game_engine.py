from app.game_engine import (
    ZONE_BATTLEFIELD,
    ZONE_GRAVEYARD,
    ZONE_LIBRARY,
    card_flags_from_catalog,
    create_game_from_deck,
    mill_cards,
    move_card_to_library_bottom,
    move_card,
    restore_snapshot,
    snapshot_game,
    take_turn,
)
from app.models import CardCatalogEntry, CardInstance, DeckDefinition, GameState


def make_card(card_id: int, name: str, *, type_line: str, is_noncreature_spell: bool = False) -> CardInstance:
    return CardInstance(
        id=card_id,
        deck_definition_id=1,
        instance_uid=f"card-{card_id}",
        card_name=name,
        type_line=type_line,
        current_zone=ZONE_LIBRARY,
        is_creature="Creature" in type_line,
        is_land="Land" in type_line,
        is_noncreature_spell=is_noncreature_spell,
    )


def test_card_flags_from_catalog():
    entry = CardCatalogEntry(name="Zombie", scryfall_id="abc", type_line="Legendary Creature — Zombie")
    flags = card_flags_from_catalog(entry)
    assert flags["is_creature"] is True
    assert flags["is_legendary_creature"] is True


def test_move_card_places_on_battlefield():
    game = GameState(id=1, deck_definition_id=1, library_order=[1], battlefield_ids=[], graveyard_ids=[], exile_ids=[], wave_pending_ids=[])
    card = make_card(1, "Gravecrawler", type_line="Creature — Zombie")
    move_card(game, card, ZONE_BATTLEFIELD)
    assert game.library_order == []
    assert game.battlefield_ids == [1]
    assert card.current_zone == ZONE_BATTLEFIELD


def test_snapshot_restore_round_trip():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[1],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    card = make_card(1, "Ghoul", type_line="Creature — Zombie")
    game.card_instances = [card]
    snapshot = snapshot_game(None, game)
    move_card(game, card, ZONE_GRAVEYARD)
    restore_snapshot(game, snapshot)
    assert game.library_order == [1]
    assert card.current_zone == ZONE_LIBRARY


class DummySession:
    def flush(self):
        return None

    def add(self, _value):
        return None


def test_take_turn_places_creature_on_battlefield():
    game = GameState(
        id=1,
        deck_definition_id=1,
        turn_number=0,
        library_order=[1, 2],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    game.card_instances = [
        make_card(1, "Zombie", type_line="Creature — Zombie"),
        make_card(2, "Dark Ritual", type_line="Instant", is_noncreature_spell=True),
    ]
    result = take_turn(DummySession(), game)
    assert result == 1
    assert game.battlefield_ids == [1]
    assert game.library_order == [2]
    assert game.turn_number == 1


def test_take_turn_places_noncreature_on_battlefield():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[1, 2],
        turn_number=4,
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    game.card_instances = [
        make_card(1, "Dark Ritual", type_line="Instant", is_noncreature_spell=True),
        make_card(2, "Zombie 2", type_line="Creature — Zombie"),
    ]
    take_turn(DummySession(), game)
    assert game.battlefield_ids == [1]
    assert game.library_order == [2]
    assert game.turn_number == 5


def test_take_turn_places_land_on_battlefield():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[1],
        turn_number=1,
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    game.card_instances = [
        make_card(1, "Swamp", type_line="Basic Land - Swamp"),
    ]
    take_turn(DummySession(), game)
    assert game.battlefield_ids == [1]
    assert game.library_order == []
    assert game.turn_number == 2


def test_mill_moves_top_library_card_to_graveyard():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[2, 1],
        battlefield_ids=[3],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    battlefield_card = make_card(3, "Battlefield Zombie", type_line="Creature - Zombie")
    battlefield_card.current_zone = ZONE_BATTLEFIELD
    top_library_card = make_card(2, "Top Card", type_line="Creature - Zombie")
    second_library_card = make_card(1, "Second Card", type_line="Creature - Zombie")
    game.card_instances = [second_library_card, top_library_card, battlefield_card]

    milled = mill_cards(DummySession(), game, 1)

    assert milled == [2]
    assert game.library_order == [1]
    assert game.graveyard_ids == [2]
    assert game.battlefield_ids == [3]
    assert battlefield_card.current_zone == ZONE_BATTLEFIELD


def test_create_game_uses_only_base_deck_cards():
    deck = DeckDefinition(id=1, name="Test Deck", decklist_text="1 Zombie", parsed_items_json=[])
    base_card = make_card(1, "Base Zombie", type_line="Creature - Zombie")
    base_card.game_state_id = None
    old_game_card = make_card(2, "Old Game Zombie", type_line="Creature - Zombie")
    old_game_card.game_state_id = 99
    deck.card_instances = [base_card, old_game_card]

    class CreateSession(DummySession):
        def __init__(self):
            self.values = []
            self.next_id = 100

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1
            self.values.append(value)

    session = CreateSession()
    game = create_game_from_deck(session, deck, name="Run")

    assert len(game.library_order) == 1


def test_create_game_places_commander_in_commander_zone():
    deck = DeckDefinition(id=1, name="Commander Deck", decklist_text="1 Zombie", parsed_items_json=[], commander_name="Wilhelt")
    base_card = make_card(1, "Base Zombie", type_line="Creature - Zombie")
    base_card.game_state_id = None
    commander_card = make_card(2, "Wilhelt", type_line="Legendary Creature - Zombie")
    commander_card.game_state_id = None
    commander_card.is_commander = True
    deck.card_instances = [base_card, commander_card]

    class CreateSession(DummySession):
        def __init__(self):
            self.values = []
            self.next_id = 200

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1
            self.values.append(value)

    game = create_game_from_deck(CreateSession(), deck, name="Run")

    assert len(game.library_order) == 1
    assert len(game.commander_ids) == 1


def test_move_card_to_library_bottom_appends_to_library():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[10, 11],
        battlefield_ids=[3],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    moved_card = make_card(3, "Battlefield Zombie", type_line="Creature - Zombie")
    moved_card.current_zone = ZONE_BATTLEFIELD
    card_10 = make_card(10, "Top Card", type_line="Creature - Zombie")
    card_11 = make_card(11, "Next Card", type_line="Creature - Zombie")
    game.card_instances = [moved_card, card_10, card_11]

    move_card_to_library_bottom(DummySession(), game, 3)

    assert game.library_order == [10, 11, 3]
    assert game.battlefield_ids == []
    assert moved_card.current_zone == ZONE_LIBRARY
