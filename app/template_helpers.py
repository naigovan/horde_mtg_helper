"""Template helpers shared across route modules."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates


STATIC_DIR = Path(__file__).resolve().parent / "static"


def asset_url(request, path: str) -> str:
    """Return a static asset URL with a file-version query string."""
    normalized_path = path.lstrip("/")
    static_url = str(request.url_for("static", path=f"/{normalized_path}"))
    asset_path = STATIC_DIR / normalized_path
    try:
        version = asset_path.stat().st_mtime_ns
    except FileNotFoundError:
        version = 0
    return f"{static_url}?v={version}"


def register_template_helpers(templates: Jinja2Templates) -> None:
    """Expose shared helpers to a Jinja environment."""
    templates.env.globals["asset_url"] = asset_url
