from app.deck_parser import parse_decklist


def test_parse_decklist_handles_basic_lines():
    items = parse_decklist("4 Gravecrawler\n2 Dark Ritual\n20 Swamp")
    assert [(item.quantity, item.card_name) for item in items] == [
        (4, "Gravecrawler"),
        (2, "Dark Ritual"),
        (20, "Swamp"),
    ]


def test_parse_decklist_rejects_invalid_line():
    try:
        parse_decklist("Gravecrawler")
    except ValueError as exc:
        assert "Invalid decklist line" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
