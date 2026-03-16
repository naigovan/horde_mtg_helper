"""Helpers for parsing plain-text decklists."""

from __future__ import annotations

import re
from dataclasses import dataclass


LINE_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")


@dataclass
class ParsedDeckItem:
    """A parsed decklist line."""

    quantity: int
    card_name: str


def parse_decklist(decklist_text: str) -> list[ParsedDeckItem]:
    """Parse a decklist where each line begins with a quantity."""
    items: list[ParsedDeckItem] = []
    for line_number, raw_line in enumerate(decklist_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            raise ValueError(f"Invalid decklist line {line_number}: {raw_line}")
        quantity = int(match.group(1))
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive on line {line_number}")
        items.append(ParsedDeckItem(quantity=quantity, card_name=match.group(2)))
    if not items:
        raise ValueError("Decklist is empty")
    return items
