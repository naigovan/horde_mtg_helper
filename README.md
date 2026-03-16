# MTG Horde Assistant

Small local web app for running the Horde side of a Magic: The Gathering Horde Magic game. It is a board-state helper, not a full MTG rules engine.

## Features

- Paste and parse a Horde decklist
- Resolve unique cards through Scryfall and cache metadata in SQLite
- Create per-copy card instances for each deck
- Start, save, and resume Horde games
- Shuffle, mill, track waves, and manage battlefield state
- Undo the last logged action with a snapshot-based restore

## Tech Stack

- Python
- FastAPI
- Jinja2 templates
- Minimal vanilla JavaScript
- SQLite
- SQLAlchemy
- Scryfall API

## Project Structure

- `app/main.py`: FastAPI app setup
- `app/db.py`: SQLite engine and session helpers
- `app/models.py`: SQLAlchemy models
- `app/deck_parser.py`: decklist parsing
- `app/scryfall_client.py`: Scryfall resolution and cache
- `app/game_engine.py`: Horde game rules and state mutations
- `app/routes/`: deck and game routes
- `app/templates/`: server-rendered HTML
- `app/static/`: CSS and light JS
- `tests/`: parser and engine tests

## Run Locally

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
uvicorn app.main:app --reload
```

4. Open `http://127.0.0.1:8000`

The SQLite database will be created at `horde.db` in the project root.

## Run With Docker

Build and run the app directly:

```bash
docker build -t mtg-horde .
docker run -d --name mtg-horde \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -e DATABASE_URL=sqlite:////app/data/horde.db \
  mtg-horde
```

Or use Compose:

```bash
docker compose up -d --build
```

The container listens on port `8000`, so you can point Nginx at `http://127.0.0.1:8000` on the Docker host, or at the Compose service if Nginx is on the same Docker network.

Example Nginx upstream:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

The SQLite file is stored in `./data/horde.db` on the host when using the provided Docker commands.

## MVP Rules Supported

- Horde has no hand and infinite mana
- Waves reveal from the top of the library
- Configurable wave policy:
  - stop on first non-creature spell
  - stop after token streak
  - fixed reveal count
- Creatures and optional lands go directly to battlefield
- Instants and sorceries enter a manual wave-resolution panel
- Damage to Horde can mill cards directly
- Optional legendary damage-mill rule can phase a legendary creature onto the battlefield
- Horde permanents can be tapped, rested, phased, exiled, moved to graveyard, or returned to top of library

## MVP Limitations

- No full stack or rules engine
- No automatic card effect resolution
- No multiplayer or networking
- Card matching relies on Scryfall availability when a card is first seen
- Undo is single-step and snapshot-based rather than a full event-sourced history
- Counters and notes are modelled but not fully surfaced in the UI yet

## Next Steps

- Add deck editing and card-level cache refresh
- Add notes/counters editing in the battlefield UI
- Add better wave summaries and triggered ability reminders
- Add search/filter tools for large battlefields and graveyards
- Add settings UI for more Horde house rules
