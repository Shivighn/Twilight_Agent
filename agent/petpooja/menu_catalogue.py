"""
Configurable menu catalogue — see docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md
section 4 for why this is a JSON file and not a Supabase table.

match_item() is deliberately rule-based (no fuzzy-matching library, no LLM)
— exact/alias/token-overlap only, every decision explainable and
exhaustively testable. See its docstring for the exact rule.

match_items_llm() is the fallback for what match_item() can't handle:
drivers typing phonetic/misspelled item names ("chckn biryni", "chickn
bryani", "biry" for "Chicken Biryani") that no fixed alias list can
enumerate in advance. It's only called on lines match_item() already
marked unmatched/ambiguous, kept strictly pinned to the catalogue's own
ids (never allowed to invent an item), and callers must still fall back to
the rule-based unmatched/ambiguous result if it fails — see
petpooja_captain_order_tool.py.
"""
import json
import os
import re

from llm.llm_client import generate

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
            "price": chosen.get("price", 0),
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
            "price": chosen.get("price", 0),
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


_LLM_MATCH_PROMPT = """You are matching item names that truck/van drivers typed on WhatsApp — often misspelled or phonetic — to the EXACT items on a restaurant's menu.

MENU (the ONLY valid items — never return an id that is not listed here):
{menu_lines}

Drivers misspell or guess phonetically, e.g. "chckn biryni", "chickn bryani", "chicken biriyani", "biry" can all mean "Chicken Biryani". Use that kind of judgment.

ITEMS TO MATCH, in order:
{item_lines}

Rules:
- If a raw name clearly means exactly one menu item (even badly misspelled), match it.
- If a raw name could plausibly mean more than one distinct menu item, match_status is "ambiguous" and "candidates" lists those item ids.
- If a raw name doesn't resemble any menu item, match_status is "unmatched" and matched_item_id is null. Never force a match.
- matched_item_id must be exactly one of the ids listed in MENU above, or null.

Return ONLY a JSON array (no markdown, no explanation), one object per input line IN THE SAME ORDER:
[{{"raw_name": "<copied exactly from the input line>", "matched_item_id": "<id from MENU or null>", "match_status": "matched" | "ambiguous" | "unmatched", "candidates": ["<id>", ...]}}]

JSON:"""


def _extract_json_array(raw: str, expected_len: int) -> list:
    """
    Pulls the answer JSON array out of a reasoning model's response, which
    may still contain unstripped chain-of-thought text (e.g. an unclosed
    <think> block that ran past the token budget, or prose that echoes
    bits of the prompt before the real answer). A naive "first [ to last
    ]" scan is fooled by any bracket in that leftover text, so instead:
    drop anything after an unclosed <think>, find every TOP-LEVEL
    bracket-balanced [...] span, and try each from last to first (the
    real answer is normally what the model settles on at the end),
    accepting the first one that parses into a list of exactly
    `expected_len` dicts each containing "raw_name".
    """
    cleaned = re.sub(r"<think>.*", "", raw, flags=re.DOTALL)
    cleaned = re.sub(r"```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned).strip()

    candidates, stack = [], []
    for i, ch in enumerate(cleaned):
        if ch == "[":
            stack.append(i)
        elif ch == "]" and stack:
            start = stack.pop()
            if not stack:  # only a fully-closed, top-level span
                candidates.append(cleaned[start : i + 1])

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(parsed, list)
            and len(parsed) == expected_len
            and all(isinstance(x, dict) and "raw_name" in x for x in parsed)
        ):
            return parsed

    raise ValueError(f"LLM did not return a usable {expected_len}-item JSON array:\n{raw[:2000]}")


async def match_items_llm(unresolved: list[dict], catalogue: list[dict]) -> list[dict]:
    """
    Resolves raw item names match_item() marked unmatched/ambiguous, using
    the same free LLM endpoints the petty-cash extractor uses (see
    llm/llm_client.py). `unresolved` is a list of match_item()'s own output
    dicts (so this reads raw_name back off them) and the return shape
    matches match_item()'s — callers overlay these onto the originals by
    index. Raises on any malformed/mismatched LLM response; callers must
    catch and keep the original rule-based result rather than let a bad
    LLM response silently produce a wrong order.
    """
    # Plain "a, b, c" aliases, not a Python list repr — a reasoning model's
    # chain-of-thought tends to echo parts of the prompt back before its
    # answer, and square brackets in the MENU listing collided with
    # _extract_json_array's bracket-matching below (confirmed: produced an
    # 11-item "array" out of the menu listing itself for a single-item ask).
    menu_lines = "\n".join(
        f"- id={item['itemid']} name=\"{item['name']}\" aliases: {', '.join(item.get('aliases', [])) or 'none'}"
        for item in catalogue
    )
    item_lines = "\n".join(f"{i + 1}. {m['raw_name']}" for i, m in enumerate(unresolved))
    prompt = _LLM_MATCH_PROMPT.format(menu_lines=menu_lines, item_lines=item_lines)

    raw = await generate(prompt)
    results = _extract_json_array(raw, expected_len=len(unresolved))

    by_id = {item["itemid"]: item for item in catalogue}
    resolved = []
    for original, result in zip(unresolved, results):
        status = result.get("match_status")
        item_id = result.get("matched_item_id")
        if status == "matched" and item_id in by_id:
            item = by_id[item_id]
            resolved.append({
                "raw_name": original["raw_name"],
                "matched_item_id": item["itemid"],
                "matched_item_name": item["name"],
                "price": item.get("price", 0),
                "match_status": "matched",
                "match_confidence": 0.85,
            })
        elif status == "ambiguous":
            candidate_names = [by_id[c]["name"] for c in (result.get("candidates") or []) if c in by_id]
            resolved.append({
                "raw_name": original["raw_name"],
                "matched_item_id": None,
                "matched_item_name": None,
                "match_status": "ambiguous",
                "match_confidence": None,
                "candidates": candidate_names or [item["name"] for item in catalogue],
            })
        else:
            # Covers "unmatched" and any malformed/unrecognized status — never
            # guess, fall back to the safest outcome (needs_review).
            resolved.append({
                "raw_name": original["raw_name"],
                "matched_item_id": None,
                "matched_item_name": None,
                "match_status": "unmatched",
                "match_confidence": None,
            })
    return resolved
