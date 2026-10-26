"""
LLM-based order message parser — see
docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md for the full design this
implements. One call per message: the LLM reads the raw WhatsApp text AND
the menu catalogue together, and returns the fully structured + menu-
matched order in one shot (bus number, passenger count, every item
resolved against the menu) — same free NVIDIA/OpenRouter chain the
petty-cash tool uses (llm/llm_client.py). No regex, no rule-based matching
stage — this is the only parsing/matching step.
"""
import json
import re

from llm.llm_client import generate

_PROMPT = """You are reading a WhatsApp order message a truck/van driver sent to a restaurant kitchen. Drivers often misspell or phonetically guess item names and format details loosely — use your judgment the way a human kitchen staffer would.

MENU (the ONLY valid items you may match to — never invent an id or name not listed here):
{menu_lines}

MESSAGE:
---
{text}
---

Extract:
- bus_number: the vehicle/bus plate number mentioned (Indian format, e.g. "AP39UX7896"), normalized to uppercase with no spaces. null if none is mentioned at all.
- passenger_count: the driver/helper headcount mentioned near words like "people", "pax", "driver", "helper" (a plain number). null if not mentioned.
- items: one entry per distinct food/drink item mentioned, each with:
  - raw_name: the item exactly as the driver wrote it
  - quantity: the number ordered (default 1 if no number given)
  - matched_item_id: the MENU id this clearly means (even if badly misspelled/phonetic), or null if it doesn't match any menu item
  - match_status: "matched" if exactly one menu item is clearly meant, "ambiguous" if it could plausibly mean more than one distinct menu item, "unmatched" if it doesn't resemble any menu item at all
  - candidates: list of MENU ids it could mean (only when match_status is "ambiguous", else empty list)

Rules:
- Never guess a matched_item_id you're not confident about — use "ambiguous" or "unmatched" instead.
- matched_item_id must be exactly one of the ids listed in MENU above, or null.
- If the message has no bus number at all, it is almost certainly not an order (e.g. casual chat) — set parse_failed to true and leave bus_number/passenger_count null and items empty.

Return ONLY a single JSON object (no markdown, no explanation), shaped exactly as:
{{"parse_failed": false, "bus_number": "...", "passenger_count": 0, "items": [{{"raw_name": "...", "quantity": 1, "matched_item_id": "...", "match_status": "matched", "candidates": []}}]}}

JSON:"""


def _menu_lines(catalogue: list[dict]) -> str:
    return "\n".join(
        f"- id={item['itemid']} name=\"{item['name']}\" aliases: {', '.join(item.get('aliases', [])) or 'none'}"
        for item in catalogue
    )


def _extract_json_object(raw: str) -> dict:
    """
    A reasoning model's leftover chain-of-thought can still contain stray
    braces (same issue hit with the old item-matching fallback's JSON
    arrays) — find every TOP-LEVEL balanced {...} span and try each from
    last to first, accepting the first one that parses into a dict shaped
    like this prompt's expected output.
    """
    cleaned = re.sub(r"<think>.*", "", raw, flags=re.DOTALL)
    cleaned = re.sub(r"```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned).strip()

    candidates, stack = [], []
    for i, ch in enumerate(cleaned):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            if not stack:
                candidates.append(cleaned[start : i + 1])

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "items" in parsed and "parse_failed" in parsed:
            return parsed

    raise ValueError(f"LLM did not return a usable JSON object:\n{raw[:2000]}")


def _normalize_bus_number(raw) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"\s+", "", str(raw)).upper()
    return cleaned or None


async def parse_order_message(text: str, catalogue: list[dict]) -> dict:
    """
    Returns { parse_failed: bool, bus_number: str|None,
    passenger_count: int|None, items: [{ raw_name, quantity,
    matched_item_id, matched_item_name, price, match_status,
    match_confidence, candidates }] }.

    Raises on a malformed/unusable LLM response (bad JSON, wrong shape) —
    the caller must treat that as needs_review, never guess silently.
    """
    prompt = _PROMPT.format(menu_lines=_menu_lines(catalogue), text=text)
    raw = await generate(prompt)
    data = _extract_json_object(raw)

    if data.get("parse_failed"):
        return {"parse_failed": True, "bus_number": None, "passenger_count": None, "items": []}

    by_id = {item["itemid"]: item for item in catalogue}
    items = []
    for raw_item in data.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        raw_name = str(raw_item.get("raw_name") or "").strip()
        if not raw_name:
            continue
        try:
            quantity = int(raw_item.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1

        status = raw_item.get("match_status")
        item_id = raw_item.get("matched_item_id")
        if status == "matched" and item_id in by_id:
            item = by_id[item_id]
            items.append({
                "raw_name": raw_name,
                "quantity": quantity,
                "matched_item_id": item["itemid"],
                "matched_item_name": item["name"],
                "price": item.get("price", 0),
                "match_status": "matched",
                "match_confidence": 0.9,
            })
        elif status == "ambiguous":
            candidate_names = [by_id[c]["name"] for c in (raw_item.get("candidates") or []) if c in by_id]
            items.append({
                "raw_name": raw_name,
                "quantity": quantity,
                "matched_item_id": None,
                "matched_item_name": None,
                "match_status": "ambiguous",
                "match_confidence": None,
                "candidates": candidate_names or [item["name"] for item in catalogue],
            })
        else:
            # Covers "unmatched" and any malformed/unrecognized status —
            # never guess, fall back to the safest outcome (needs_review).
            items.append({
                "raw_name": raw_name,
                "quantity": quantity,
                "matched_item_id": None,
                "matched_item_name": None,
                "match_status": "unmatched",
                "match_confidence": None,
            })

    passenger_count = data.get("passenger_count")
    try:
        passenger_count = int(passenger_count) if passenger_count is not None else None
    except (TypeError, ValueError):
        passenger_count = None

    return {
        "parse_failed": False,
        "bus_number": _normalize_bus_number(data.get("bus_number")),
        "passenger_count": passenger_count,
        "items": items,
    }
