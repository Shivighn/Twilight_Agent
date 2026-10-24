"""
Configurable menu catalogue — see docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md
section 4 for why this is a JSON file and not a Supabase table.

Matching is deliberately rule-based (no fuzzy-matching library, no LLM) —
every decision is explainable and exhaustively testable. See match_item()'s
docstring for the exact rule.
"""
import json
import os
import re

_CATALOGUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu_catalogue.json")

# How much of a candidate item's own normalized-token set the raw name's
# tokens must cover to "clear the threshold". 1.0 = every one of the
# candidate's words must appear in what the driver typed.
_MATCH_THRESHOLD = 1.0


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, singularize a trailing 's' per word —
    same normalization on both the catalogue and the raw driver text so
    they compare on equal footing."""
    text = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    words = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in text.split()]
    return " ".join(words)


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


def match_item(raw_name: str, catalogue: list[dict]) -> dict:
    """
    One item line -> { raw_name, matched_item_id, matched_item_name,
    match_status: 'matched'|'ambiguous'|'unmatched', match_confidence }.

    Rule (deterministic, no fuzzy library):
      1. Exact match against a candidate's normalized name OR any of its
         normalized aliases -> matched immediately (confidence 1.0).
      2. Otherwise, token-overlap: a candidate "clears the threshold" when
         EVERY one of its own name/alias's words appears somewhere in the
         raw text's words (order-independent) — e.g. raw "chicken biryani
         family" clears "Chicken Biryani Family Pack"'s alias "chicken
         biryani family" but NOT plain "Chicken Biryani" (that candidate's
         words are a subset of the raw text too, so BOTH can clear at once
         -> ambiguous, by design: "family" is exactly the distinguishing
         word a human would also need to notice).
      3. No candidate clears -> unmatched.
      4. More than one candidate clears -> ambiguous (never guess which).
    """
    norm_raw = _normalize(raw_name)
    raw_words = set(norm_raw.split())

    exact, cleared = [], []
    for item in catalogue:
        names_to_check = [item["name"], *item.get("aliases", [])]
        normalized_names = [_normalize(n) for n in names_to_check]

        if norm_raw in normalized_names:
            exact.append(item)
            continue

        for normalized_name in normalized_names:
            name_words = set(normalized_name.split())
            if name_words and name_words <= raw_words:  # every candidate word present in raw text
                cleared.append(item)
                break

    if exact:
        chosen = exact[0]
        return {
            "raw_name": raw_name,
            "matched_item_id": chosen["itemid"],
            "matched_item_name": chosen["name"],
            "match_status": "matched",
            "match_confidence": 1.0,
        }

    # A cleared candidate whose own words are a SUBSET of another cleared
    # candidate's words is strictly less specific (e.g. "Chicken Biryani" is
    # a subset of "Chicken Biryani Family Pack") — drop it if a more
    # specific candidate also cleared, instead of flagging a false ambiguity.
    def is_subsumed(item, others):
        item_words = set(_normalize(item["name"]).split())
        return any(
            other is not item and item_words < set(_normalize(other["name"]).split())
            for other in others
        )

    distinct = [c for c in cleared if not is_subsumed(c, cleared)]
    # Multiple distinct candidates clearing (not one subsuming the other) -> genuinely ambiguous.
    distinct = list({c["itemid"]: c for c in distinct}.values())

    if len(distinct) == 1:
        chosen = distinct[0]
        return {
            "raw_name": raw_name,
            "matched_item_id": chosen["itemid"],
            "matched_item_name": chosen["name"],
            "match_status": "matched",
            "match_confidence": _MATCH_THRESHOLD,
        }
    if len(distinct) > 1:
        return {
            "raw_name": raw_name,
            "matched_item_id": None,
            "matched_item_name": None,
            "match_status": "ambiguous",
            "match_confidence": None,
            "candidates": [c["name"] for c in distinct],
        }
    return {
        "raw_name": raw_name,
        "matched_item_id": None,
        "matched_item_name": None,
        "match_status": "unmatched",
        "match_confidence": None,
    }
