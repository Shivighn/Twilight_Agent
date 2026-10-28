"""
Structures a raw WhatsApp order message into {bus_number, passenger_count,
items: [{quantity, raw_name}]} — no menu involved at all, deliberately, so
this prompt stays small and fast regardless of how big the menu catalogue
grows. Menu-matching happens separately (menu_catalogue.py's match_item()
+ match_items_llm()) — splitting it out this way means every message pays
for one small LLM call, not one call carrying the full menu every time.

Real driver messages are too messy for plain regex here — confirmed by an
actual message containing a stray "Sr.no 712" reference-number line that
isn't an item at all; a human reads that as noise, a fixed regex would
wrongly turn it into a bogus unmatched item. That's exactly the judgment
call an LLM is good at and regex isn't, so this step stays LLM-based even
though matching (the slow, menu-heavy part) moved back to rule-based-first.
"""
import asyncio
import json
import re

from llm.llm_client import generate

_PROMPT = """You are reading a WhatsApp order message a truck/van driver sent to a restaurant kitchen. Drivers format messages however they like — multi-line, with stray reference numbers, greetings, or sender info mixed in.

MESSAGE:
---
{text}
---

Extract:
- bus_number: the vehicle/bus plate number mentioned (Indian format, e.g. "AP39UX7896"), normalized to uppercase with no spaces. null if none is mentioned at all.
- passenger_count: the driver/helper headcount mentioned near words like "people", "pax", "driver", "helper". null if not mentioned.
- items: one entry per line that is ACTUALLY a food/drink order line, each with raw_name (the item text as written) and quantity (the number ordered, default 1 if no number given).

Rules:
- Skip lines that are NOT order items — reference numbers (e.g. "Sr.no 712"), sender names, greetings, thank-yous, etc. Only genuine food/drink lines belong in "items".
- If the message has no bus number at all, it is almost certainly not an order (e.g. casual chat) — set parse_failed to true and leave bus_number/passenger_count null and items empty.

Return ONLY a single JSON object (no markdown, no explanation), shaped exactly as:
{{"parse_failed": false, "bus_number": "...", "passenger_count": 0, "items": [{{"raw_name": "...", "quantity": 1}}]}}

JSON:"""


def _extract_json_object(raw: str) -> dict:
    """Same hardening as the menu-matching prompts — a reasoning model's
    leftover chain-of-thought can contain stray braces, so find every
    TOP-LEVEL balanced {...} span and try each from last to first."""
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


async def structure_message(text: str) -> dict:
    """
    Returns { parse_failed: bool, bus_number: str|None,
    passenger_count: int|None, items: [{raw_name, quantity}] }.

    Raises on a malformed/unusable response or on timeout — the caller
    must treat that as needs_review, never guess and never hang. Capped
    at 40s: the Node gateway's own call to this agent times out at 120s
    (AGENT_SERVICE_TIMEOUT_MS) and shows the driver a generic error with
    no real reply if we run past it — every message needs a real reply,
    fast, every time, even when the free LLM endpoint is having a slow
    moment.
    """
    prompt = _PROMPT.format(text=text)
    raw = await asyncio.wait_for(generate(prompt), timeout=40)
    data = _extract_json_object(raw)

    if data.get("parse_failed"):
        return {"parse_failed": True, "bus_number": None, "passenger_count": None, "items": []}

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
        items.append({"raw_name": raw_name, "quantity": quantity})

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
