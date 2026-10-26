"""
Configurable menu catalogue — see docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md
section 4 for why this is a JSON file and not a Supabase table. Matching
against it happens in llm_order_parser.py, not here — this module is just
the data loader.
"""
import json
import os

_CATALOGUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu_catalogue.json")


class CatalogueUnavailableError(Exception):
    """Raised when menu_catalogue.json is missing or malformed — callers
    must treat every item as needing review, never match against an
    accidentally-empty catalogue (see failure-scenarios table in the design doc)."""


def load_catalogue() -> list[dict]:
    """Reloaded on every call — the catalogue is small and rarely edited,
    so there's no reason to cache it and risk serving a stale copy after
    someone edits the file without restarting the process."""
    try:
        with open(_CATALOGUE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        raise CatalogueUnavailableError(f"Could not load {_CATALOGUE_PATH}: {err}") from err

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise CatalogueUnavailableError(f"{_CATALOGUE_PATH} has no usable 'items' list")
    return items
