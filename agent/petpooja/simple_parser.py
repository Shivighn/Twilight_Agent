"""
Fast, local, non-LLM structuring pass — tried BEFORE the LLM structuring
call in llm_structure_parser.py. With only ~33 menu items, every real
driver message seen so far follows one of two shapes: one field per line
("Bus num AP31TA 5628" / "1 Chicken Biryani" / ...), or everything
comma-separated on a single line ("AP39UX7896, 3 people, 1 Chicken
Biryani, 2 Roti") — so this resolves the common case instantly, with zero
network calls, for either shape.

try_simple_structure() returns None whenever it isn't CONFIDENT it
understood every field in the message (no bus number found, or a field
that doesn't fit any known shape) — the caller must then fall back to the
slower LLM structuring call, which can use judgment on messages that
don't fit this shape.
"""
import re

_PLATE_RE = re.compile(r"\b[A-Za-z]{2}\s?-?\s?\d{1,2}\s?-?\s?[A-Za-z]{0,3}\s?-?\s?\d{3,4}\b")
_PASSENGER_RE = re.compile(r"(\d+)\s*(?:people|pax|passenger|driver|helper)", re.IGNORECASE)
_ITEM_LINE_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
_NOISE_LINE_RE = re.compile(
    r"^\s*(sr\.?\s*no\.?\s*\d*|hi|hello|hey|thanks?|thank\s*you|please|regards"
    r"|bus\s*(num|no|number)?\.?|veh(?:icle)?\.?\s*(no|number)?\.?)\s*[:.]?\s*$",
    re.IGNORECASE,
)


def _normalize_bus_number(raw: str) -> str:
    return re.sub(r"[\s-]+", "", raw).upper()


def try_simple_structure(text: str) -> dict | None:
    """Same success shape as llm_structure_parser.structure_message()'s
    non-failed return. Returns None (never raises) on anything it isn't
    sure about, so the caller can fall back to the LLM."""
    text = text or ""
    plate_match = _PLATE_RE.search(text)
    if not plate_match:
        return None  # no confident bus number -> let the LLM judge (might not be an order at all)

    bus_number = _normalize_bus_number(plate_match.group(0))
    passenger_count = None
    items = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if plate_match.group(0) in line:
            stripped = line.replace(plate_match.group(0), "").strip(" ,\t")
            if not stripped or _NOISE_LINE_RE.match(stripped):
                continue  # the bus-number line was just a label, nothing else on it

        passenger_match = _PASSENGER_RE.search(stripped)
        if passenger_match:
            passenger_count = int(passenger_match.group(1))
            stripped = (stripped[: passenger_match.start()] + stripped[passenger_match.end() :]).strip(" ,\t")
            if not stripped:
                continue

        if _NOISE_LINE_RE.match(stripped):
            continue

        matched_any = False
        for fragment in stripped.split(","):
            fragment = fragment.strip()
            if not fragment:
                continue
            if _NOISE_LINE_RE.match(fragment):
                continue
            item_match = _ITEM_LINE_RE.match(fragment)
            if not item_match:
                # A field that doesn't fit any known shape -> don't guess, let the LLM read it.
                return None
            items.append({"raw_name": item_match.group(2).strip(), "quantity": int(item_match.group(1))})
            matched_any = True

        if not matched_any:
            return None

    return {"parse_failed": False, "bus_number": bus_number, "passenger_count": passenger_count, "items": items}
