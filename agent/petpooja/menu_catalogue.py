"""
Configurable menu catalogue — see docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md
section 4 for why this is a JSON file and not a Supabase table.

match_item() is the FIRST pass for every item: fast, local, no network
call — exact/alias/token-overlap only, deliberately rule-based so every
decision is explainable. With 35 items x 50 aliases each in
menu_catalogue.json, this resolves the large majority of real driver
messages instantly.

match_items_llm() is the fallback for whatever match_item() can't handle —
only called on the lines it already marked unmatched/ambiguous, so the
full-menu LLM prompt only gets paid for when it's actually needed, not on
every single message. Callers must still fall back to the rule-based
unmatched/ambiguous result if this fails (bad/slow response, timeout) —
see petpooja_captain_order_tool.py.
"""
import asyncio
import json
import os
import re

from llm.llm_client import generate

_CATALOGUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu_catalogue.json")

# How much of a candidate item's own normalized-token set the raw name's
# tokens must cover to "clear the threshold". 1.0 = every one of the
# candidate's words must appear in what the driver typed.
_MATCH_THRESHOLD = 1.0


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


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, singularize a trailing 's' per word —
    same normalization on both the catalogue and the raw driver text so
    they compare on equal footing."""
    text = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    words = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in text.split()]
    return " ".join(words)


def match_item(raw_name: str, catalogue: list[dict]) -> dict:
    """
    One item line -> { raw_name, matched_item_id, matched_item_name,
    match_status: 'matched'|'ambiguous'|'unmatched', match_confidence }.

    Rule (deterministic, no LLM, no fuzzy library):
      1. Exact match against a candidate's normalized name OR any of its
         normalized aliases -> matched immediately (confidence 1.0).
      2. Otherwise, token-overlap: a candidate "clears the threshold" when
         EVERY one of its own name/alias's words appears somewhere in the
         raw text's words (order-independent).
      3. No candidate clears -> unmatched.
      4. More than one candidate clears (and neither subsumes the other) -> ambiguous (never guess which).
    """
    norm_raw = _normalize(raw_name)
    raw_words = set(norm_raw.split())

    exact, cleared = [], []
    for item in catalogue:
        # Catalogue names carry a trailing dietary marker literally in the
        # string (e.g. "Jeera Rice (D)") — strip it before comparing, or a
        # driver typing the plain dish name never exact-matches it and
        # falls through to a generic alias on a DIFFERENT item instead
        # (e.g. "rice" on "Plain Rice" silently swallowing "Jeera rice").
        clean_name = re.sub(r"\s*\([^)]*\)\s*$", "", item["name"])
        names_to_check = [clean_name, *item.get("aliases", [])]
        normalized_names = [_normalize(n) for n in names_to_check]

        if norm_raw in normalized_names:
            exact.append(item)
            continue

        for normalized_name in normalized_names:
            name_words = set(normalized_name.split())
            # A single bare word (e.g. "rice" on "Plain Rice") is too
            # generic to count here — it would trivially clear for ANY
            # dish mentioning that word, hijacking unrelated/off-menu
            # items. It's still eligible via the exact check above; this
            # pass is for genuine multi-word phrase overlap only.
            if len(name_words) > 1 and name_words <= raw_words:
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
    # candidate's words is strictly less specific — drop it if a more
    # specific candidate also cleared, instead of flagging a false ambiguity.
    def is_subsumed(item, others):
        item_words = set(_normalize(item["name"]).split())
        return any(
            other is not item and item_words < set(_normalize(other["name"]).split())
            for other in others
        )

    distinct = [c for c in cleared if not is_subsumed(c, cleared)]
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

MENU (the ONLY valid items — never return an id that is not listed here). `aka` is a plain-English
also-known-as for a menu item whose real name is a regional-language dish name, given because that
name has no spelling resemblance to what a driver might type for the same dish:
{menu_lines}

Drivers misspell or guess phonetically, e.g. "chckn biryni", "chickn bryani" both mean "Chicken Biryani",
"Butter Non" means "Butter Naan", "Paneer Curri" means "Paneer Curry" — match on the misspelled WORDS,
not loosely on topic.

ITEMS TO MATCH, in order:
{item_lines}

Rules:
- A raw name that is a near-identical spelling of exactly one menu item's name or aka — missing a
  letter, an extra/swapped letter, a dropped final vowel, a phonetic respelling — IS that item. Match
  it confidently; being 1-2 letters off from an otherwise unambiguous name is NOT grounds for
  "unmatched". Reserve "unmatched" for when the DISH ITSELF isn't on the menu, never for imperfect
  spelling of a dish that clearly is.
- Match the actual DISH TYPE the raw text names — curry, fry, biryani, and rice are different
  preparations even when they share an ingredient word (e.g. "chicken fried rice" and "chicken biryani"
  both contain "chicken" but are NOT the same dish; "egg curry" and "egg fry" both contain "egg" but are
  NOT the same dish). Never match on a shared ingredient word alone while ignoring a clearly different
  preparation word.
- If a raw name names a dish/preparation that genuinely isn't on this menu at all (not just spelled
  unusually, but actually absent — e.g. "fried rice" when no fried rice exists on the menu), match_status
  is "unmatched" and matched_item_id is null. Never force the closest-sounding menu item onto a
  genuinely different dish just to avoid returning unmatched — but don't use "unmatched" as a shortcut
  for "I'm not 100% sure of the spelling" either.
- If a raw name could plausibly mean more than one distinct menu item, match_status is "ambiguous" and "candidates" lists those item ids.
- matched_item_id must be exactly one of the ids listed in MENU above, or null.

Return ONLY a JSON array (no markdown, no explanation), one object per input line IN THE SAME ORDER:
[{{"raw_name": "<copied exactly from the input line>", "matched_item_id": "<id from MENU or null>", "match_status": "matched" | "ambiguous" | "unmatched", "candidates": ["<id>", ...]}}]

JSON:"""


def _extract_json_array(raw: str, expected_len: int) -> list:
    """
    Pulls the answer JSON array out of a reasoning model's response, which
    may still contain unstripped chain-of-thought text. Finds every
    TOP-LEVEL bracket-balanced [...] span and tries each from last to
    first, accepting the first one that parses into a list of exactly
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
            if not stack:
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
    the same free LLM endpoints the petty-cash extractor uses. `unresolved`
    is a list of match_item()'s own output dicts (so this reads raw_name
    back off them) and the return shape matches match_item()'s — callers
    overlay these onto the originals by index. Raises on any malformed/
    mismatched/slow response (40s cap — same reasoning as
    llm_structure_parser.py's); callers must catch and keep the original
    rule-based result rather than let a bad/slow LLM response block a reply.

    The prompt deliberately sends id+name+aka, NOT the 1750 misspelling
    aliases: those exist for match_item()'s own exact/subset checks, not
    for the LLM — its job here is exactly the fuzzy spelling judgment
    those aliases were a rule-based stand-in for, and the full alias list
    is large enough (~30KB) to blow past some free providers' per-request
    payload limits for no matching-quality benefit.
    `aka` (menu_catalogue.json) is a SEPARATE, hand-curated plain-English
    descriptor for items whose real name is a regional-language dish name
    an LLM has no lexical way to connect to a driver's English guess —
    e.g. "Kodi Guddu Iguru" literally means egg curry, but shares no
    letters with "egg curri", so without this hint the LLM matched it to
    "Chettinadu Egg Fry" purely because that name contains "Egg" too.
    """
    menu_lines = "\n".join(
        f'- id={item["itemid"]} name="{re.sub(r"\s*\([^)]*\)\s*$", "", item["name"])}"'
        + (f' aka="{item["aka"]}"' if item.get("aka") else "")
        for item in catalogue
    )
    item_lines = "\n".join(f"{i + 1}. {m['raw_name']}" for i, m in enumerate(unresolved))
    prompt = _LLM_MATCH_PROMPT.format(menu_lines=menu_lines, item_lines=item_lines)

    raw = await asyncio.wait_for(generate(prompt), timeout=40)
    results = _extract_json_array(raw, expected_len=len(unresolved))

    by_id = {item["itemid"]: item for item in catalogue}
    resolved = []
    for original, result in zip(unresolved, results):
        status = result.get("match_status")
        # Catalogue itemids are strings, but the LLM's JSON often writes
        # matched_item_id as a bare number (e.g. 702, not "702") — compare
        # as strings or a correct match silently falls through to unmatched.
        item_id = result.get("matched_item_id")
        if item_id is not None:
            item_id = str(item_id)
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
            candidate_ids = [str(c) for c in (result.get("candidates") or [])]
            candidate_names = [by_id[c]["name"] for c in candidate_ids if c in by_id]
            resolved.append({
                "raw_name": original["raw_name"],
                "matched_item_id": None,
                "matched_item_name": None,
                "match_status": "ambiguous",
                "match_confidence": None,
                "candidates": candidate_names or [item["name"] for item in catalogue],
            })
        else:
            resolved.append({
                "raw_name": original["raw_name"],
                "matched_item_id": None,
                "matched_item_name": None,
                "match_status": "unmatched",
                "match_confidence": None,
            })
    return resolved
