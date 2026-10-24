"""
Rule-based order message parser — no LLM call. See
docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md section 5.1 for the full flow this
feeds into.

Example message this parses:
  "AP39UX7896, 3 people, 1 Chicken Biryani, 2 Roti"
->
  vehicle_number="AP39UX7896", passenger_count=3,
  items=[{"quantity": 1, "raw_name": "Chicken Biryani"},
         {"quantity": 2, "raw_name": "Roti"}]
"""
import re

# Indian vehicle plate: 2 letters, 1-2 digits, 1-3 letters, 4 digits —
# spacing/case tolerated, normalized away. Same idea as T44's
# normalize_bus_number (scripts/t44_ac_sales_report.py): two spellings of
# the same plate must compare equal.
_VEHICLE_RE = re.compile(r"\b([A-Za-z]{2})\s?(\d{1,2})\s?([A-Za-z]{1,3})\s?(\d{4})\b")

# "3 people" / "3 pax" / "2 driver + 1 helper" style counts. Only driver/
# helper headcount counts here (requirement 3 excludes onboard passengers —
# this is a kitchen order, not a manifest), so "people"/"pax" phrasing is
# treated as that headcount by convention for this group's messages.
_PASSENGER_RE = re.compile(r"\b(\d{1,2})\s*(?:people|pax|persons?|driver|helper)s?\b", re.IGNORECASE)

# Leading quantity on an item line: "2 Roti" -> qty 2, name "Roti".
# No leading number -> qty 1 ("Chicken Biryani" -> qty 1).
_ITEM_LINE_RE = re.compile(r"^\s*(\d+)?\s*[xX]?\s*(.+?)\s*$")


def normalize_vehicle_number(raw: str) -> str:
    """Uppercase, strip whitespace — "ap 39 ux 7896" and "AP39UX7896" must
    compare equal (same reasoning as T44's bus-number normalization)."""
    return re.sub(r"\s+", "", (raw or "")).upper()


def _split_item_lines(remainder: str) -> list[str]:
    # Drivers separate items with commas or newlines interchangeably.
    parts = re.split(r"[,\n]+", remainder)
    return [p.strip() for p in parts if p.strip()]


def parse_order_message(text: str) -> dict:
    """
    Returns { vehicle_number: str|None, passenger_count: int|None,
    items: [{quantity, raw_name}], parse_failed: bool }.

    parse_failed=True means no vehicle number was found at all — this
    almost certainly isn't an order message (e.g. chit-chat in the group),
    per the design doc's explicit "don't even try to review this" case.
    """
    vehicle_match = _VEHICLE_RE.search(text or "")
    if not vehicle_match:
        return {"vehicle_number": None, "passenger_count": None, "items": [], "parse_failed": True}

    vehicle_number = normalize_vehicle_number("".join(vehicle_match.groups()))

    passenger_match = _PASSENGER_RE.search(text)
    passenger_count = int(passenger_match.group(1)) if passenger_match else None

    # Everything after the vehicle number (and the passenger-count phrase,
    # if it's embedded in the same comma-separated run) is candidate item
    # lines. Simplest robust approach: take the text, cut out the vehicle
    # match and passenger match spans, then split what's left on commas/
    # newlines — whatever remains that isn't empty is an item line.
    remainder = text[: vehicle_match.start()] + text[vehicle_match.end() :]
    if passenger_match:
        remainder = remainder[: passenger_match.start()] + remainder[passenger_match.end() :]

    items = []
    for line in _split_item_lines(remainder):
        m = _ITEM_LINE_RE.match(line)
        if not m or not m.group(2):
            continue
        qty = int(m.group(1)) if m.group(1) else 1
        name = m.group(2).strip(" .-")
        if name:
            items.append({"quantity": qty, "raw_name": name})

    return {
        "vehicle_number": vehicle_number,
        "passenger_count": passenger_count,
        "items": items,
        "parse_failed": False,
    }
