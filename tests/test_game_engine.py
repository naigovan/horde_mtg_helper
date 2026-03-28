from app.game_engine import (
    ZONE_BATTLEFIELD,
    ZONE_GRAVEYARD,
    ZONE_LIBRARY,
    ZONE_VANISHED,
    ZONE_WAVE,
    card_flags_from_catalog,
    place_pending_turn,
    create_game_from_deck,
    mill_cards,
    move_card_to_library_bottom,
    move_card,
    move_card_to_zone,
    return_pending_turn,
    restore_snapshot,
    snapshot_game,
    tap_all,
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


def test_take_turn_reveals_until_first_non_token_card():
    game = GameState(
        id=1,
        deck_definition_id=1,
        turn_number=0,
        library_order=[1, 2, 3, 4],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    game.card_instances = [
        CardInstance(
            id=1,
            deck_definition_id=1,
            instance_uid="token-1",
            card_name="Zombie Token",
            type_line="Token Creature — Zombie",
            current_zone=ZONE_LIBRARY,
            is_creature=True,
            is_token=True,
        ),
        CardInstance(
            id=2,
            deck_definition_id=1,
            instance_uid="token-2",
            card_name="Zombie Token 2",
            type_line="Token Creature — Zombie",
            current_zone=ZONE_LIBRARY,
            is_creature=True,
            is_token=True,
        ),
        make_card(3, "Dark Ritual", type_line="Instant", is_noncreature_spell=True),
        make_card(4, "Next Card", type_line="Creature — Zombie"),
    ]
    result = take_turn(DummySession(), game)

    assert result == 1
    assert game.wave_pending_ids == [1, 2, 3]
    assert game.library_order == [4]
    assert game.turn_number == 0
    assert all(game.card_instances[index].current_zone == ZONE_WAVE for index in range(3))
    assert game.card_instances[3].current_zone == ZONE_LIBRARY


def test_take_turn_reveals_single_non_token_card_when_it_is_first():
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

    assert game.wave_pending_ids == [1]
    assert game.library_order == [2]
    assert game.turn_number == 4
    assert game.card_instances[0].current_zone == ZONE_WAVE


def test_place_pending_turn_moves_preview_to_battlefield_and_advances_turn():
    game = GameState(
        id=1,
        deck_definition_id=1,
        turn_number=1,
        library_order=[3],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[1, 2],
    )
    first = make_card(1, "Zombie Token", type_line="Token Creature — Zombie")
    first.current_zone = ZONE_WAVE
    first.is_token = True
    second = make_card(2, "Gravecrawler", type_line="Creature — Zombie")
    second.current_zone = ZONE_WAVE
    third = make_card(3, "Next Card", type_line="Creature — Zombie")
    game.card_instances = [first, second, third]

    placed = place_pending_turn(DummySession(), game)

    assert placed == [1, 2]
    assert game.wave_pending_ids == []
    assert game.battlefield_ids == [1, 2]
    assert game.turn_number == 2
    assert first.current_zone == ZONE_BATTLEFIELD
    assert second.current_zone == ZONE_BATTLEFIELD
    assert first.rested is True
    assert second.rested is True


def test_return_pending_turn_restores_preview_to_library_top_in_order():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[1],
        turn_number=7,
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[2, 3],
    )
    top_library = make_card(1, "Top Card", type_line="Creature — Zombie")
    preview_one = make_card(2, "Zombie Token", type_line="Token Creature — Zombie")
    preview_one.current_zone = ZONE_WAVE
    preview_one.is_token = True
    preview_two = make_card(3, "Dark Ritual", type_line="Instant", is_noncreature_spell=True)
    preview_two.current_zone = ZONE_WAVE
    game.card_instances = [top_library, preview_one, preview_two]

    returned = return_pending_turn(DummySession(), game)

    assert returned == [2, 3]
    assert game.wave_pending_ids == []
    assert game.library_order == [2, 3, 1]
    assert preview_one.current_zone == ZONE_LIBRARY
    assert preview_two.current_zone == ZONE_LIBRARY
    assert preview_one.zone_position == 0
    assert preview_two.zone_position == 1


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


def test_mill_moves_token_to_vanished_by_default():
    game = GameState(
        id=1,
        deck_definition_id=1,
        destroyed_tokens_to_graveyard=False,
        library_order=[2, 1],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        vanished_ids=[],
        wave_pending_ids=[],
    )
    token_card = make_card(2, "Zombie Token", type_line="Token Creature - Zombie")
    token_card.is_token = True
    second_library_card = make_card(1, "Second Card", type_line="Creature - Zombie")
    game.card_instances = [second_library_card, token_card]

    milled = mill_cards(DummySession(), game, 1)

    assert milled == [2]
    assert game.library_order == [1]
    assert game.graveyard_ids == []
    assert game.vanished_ids == [2]
    assert token_card.current_zone == ZONE_VANISHED


def test_mill_moves_token_to_graveyard_when_option_enabled():
    game = GameState(
        id=1,
        deck_definition_id=1,
        destroyed_tokens_to_graveyard=True,
        library_order=[2, 1],
        battlefield_ids=[],
        graveyard_ids=[],
        exile_ids=[],
        vanished_ids=[],
        wave_pending_ids=[],
    )
    token_card = make_card(2, "Zombie Token", type_line="Token Creature - Zombie")
    token_card.is_token = True
    second_library_card = make_card(1, "Second Card", type_line="Creature - Zombie")
    game.card_instances = [second_library_card, token_card]

    milled = mill_cards(DummySession(), game, 1)

    assert milled == [2]
    assert game.library_order == [1]
    assert game.graveyard_ids == [2]
    assert game.vanished_ids == []
    assert token_card.current_zone == ZONE_GRAVEYARD


def test_destroyed_token_moves_to_vanished_by_default():
    game = GameState(
        id=1,
        deck_definition_id=1,
        destroyed_tokens_to_graveyard=False,
        library_order=[],
        battlefield_ids=[1],
        graveyard_ids=[],
        exile_ids=[],
        vanished_ids=[],
        wave_pending_ids=[],
    )
    token = make_card(1, "Zombie Token", type_line="Token Creature - Zombie")
    token.current_zone = ZONE_BATTLEFIELD
    token.is_token = True
    game.card_instances = [token]

    move_card_to_zone(DummySession(), game, 1, ZONE_GRAVEYARD)

    assert game.graveyard_ids == []
    assert game.vanished_ids == [1]
    assert token.current_zone == ZONE_VANISHED


def test_destroyed_token_can_still_go_to_graveyard_when_option_enabled():
    game = GameState(
        id=1,
        deck_definition_id=1,
        destroyed_tokens_to_graveyard=True,
        library_order=[],
        battlefield_ids=[1],
        graveyard_ids=[],
        exile_ids=[],
        vanished_ids=[],
        wave_pending_ids=[],
    )
    token = make_card(1, "Zombie Token", type_line="Token Creature - Zombie")
    token.current_zone = ZONE_BATTLEFIELD
    token.is_token = True
    game.card_instances = [token]

    move_card_to_zone(DummySession(), game, 1, ZONE_GRAVEYARD)

    assert game.graveyard_ids == [1]
    assert game.vanished_ids == []
    assert token.current_zone == ZONE_GRAVEYARD


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


def test_create_game_defaults_destroyed_tokens_to_vanished_mode():
    deck = DeckDefinition(id=1, name="Commander Deck", decklist_text="1 Zombie", parsed_items_json=[])
    base_card = make_card(1, "Base Zombie", type_line="Creature - Zombie")
    base_card.game_state_id = None
    deck.card_instances = [base_card]

    class CreateSession(DummySession):
        def __init__(self):
            self.values = []
            self.next_id = 300

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1
            self.values.append(value)

    game = create_game_from_deck(CreateSession(), deck, name="Run")

    assert game.destroyed_tokens_to_graveyard is False


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


def test_tap_all_taps_all_battlefield_cards():
    game = GameState(
        id=1,
        deck_definition_id=1,
        library_order=[],
        battlefield_ids=[1, 2],
        graveyard_ids=[],
        exile_ids=[],
        wave_pending_ids=[],
    )
    card_one = make_card(1, "Zombie One", type_line="Creature - Zombie")
    card_one.current_zone = ZONE_BATTLEFIELD
    card_two = make_card(2, "Zombie Two", type_line="Creature - Zombie")
    card_two.current_zone = ZONE_BATTLEFIELD
    game.card_instances = [card_one, card_two]

    tap_all(DummySession(), game)

    assert card_one.tapped is True
    assert card_two.tapped is True
