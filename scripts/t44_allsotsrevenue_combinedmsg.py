"""
Terminal 44 full-day combined WhatsApp message: 3 daytime revenue slots
(no bus data) + 6 evening/night bus-stoppage windows (bus count + revenue),
in one message. ALL order types (AC, Dine In, Drivers) count everywhere —
there is no AC-only filter in this report, by request.

Usage:
    python scripts/t44_allsotsrevenue_combinedmsg.py

Just drop the Excel in the project root, same as the other two scripts —
picks the most recently modified Order_Listing_2026_10_06_12_14_42.xlsx automatically.

Excluded everywhere in this report, per request:
  - Status = "Cancelled" (not real revenue)
  - Order No starting with "C" (e.g. "C757") — a separate order sequence
    (seen in Order_Listing_2026_10_02_11_36_37.xlsx: 62 such rows, all
    "Dine In (D ...)" tables)

Daytime slots (Grand Total summed, any Sub Order Type):
    7 AM-12 PM, 12 PM-4 PM, 4 PM-6 PM ("snacks" is just this slot's
    nickname — there's no actual "Snacks" field in the Excel, confirmed
    with the user — it sums the same way as the other two daytime slots).
Evening/night slots (bus count + revenue, any Sub Order Type):
    6-8 PM, 8-9 PM, 9-10 PM, 10-11 PM, 11-12 AM, After 12 AM
All slots always print, even at ₹0 / 0 buses — none are skipped.

Each bus is assigned to whichever slot holds the MAJORITY of its check-in-
to-checkout duration, not just its check-in instant — see assign_bus_slot.
A bus in at 6:45, out at 7:45 (15 min left in "6-8 PM", 45 min into what
would be the next hour) counts as having spent most of its time past the
hour mark; one in at 7:55, out at 8:15 counts under "8-9 PM" (15 min there
vs 5 min left in "6-8 PM"). Revenue (order) bucketing is unaffected — an
order is a single instant, not a duration, so it still looks up its
Created time as a point.

Within "After 12 AM", an order that MENTIONS tea/coffee/juice anywhere in
its Items is carved out into its own "Tea/Coffee/Juice (post 12)" line
instead of counting in "After 12 AM" — same rule as
t44_last_15_days_combined_revenue.py, just applied to yesterday's single
day here instead of every date in the file.
"""
import glob
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# Windows terminals default to cp1252, which can't encode ₹ — force UTF-8
# so this doesn't crash on the last line before printing the message.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# This script finds its own Excel file — independent of t44_ac_sales_report.py.
# Still reuses its bus/Grand-Total loaders below (those aren't "file allocation").
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t44_ac_sales_report import fetch_buses, parse_ampm, group_orders, normalize_bus_number, count_distinct_buses  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_latest_excel():
    """Picks the most recently modified Order_Listing_*.xlsx in the project root. Never hand-edit this to a literal filename — drop the new file in and it's picked up automatically."""
    files = glob.glob(os.path.join(REPO_ROOT, "Order_Listing_*.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]  # skip Excel lock files
    if not files:
        sys.exit(f"No Order_Listing_*.xlsx found in {REPO_ROOT}")
    return max(files, key=os.path.getmtime)


DAY_SLOTS = [
    ("7 AM-12 PM", 7 * 60, 12 * 60),
    ("12 PM-4 PM", 12 * 60, 16 * 60),
    ("4 PM-6 PM", 16 * 60, 18 * 60),
]
# Plain hourly boundaries, on a "minutes since 6 PM" scale (see
# minutes_since_6pm) instead of minutes-since-midnight — that makes the
# midnight wrap a non-issue (no duplicate "After 12 AM" tuples needed) and
# lets the SAME ranges serve both revenue point-lookups and bus duration-
# overlap below.
#   6-8 PM:      0 -  120 (6:00 PM  -  8:00 PM)
#   8-9 PM:    120 -  180 (8:00 PM  -  9:00 PM)
#   9-10 PM:   180 -  240 (9:00 PM  - 10:00 PM)
#   10-11 PM:  240 -  300 (10:00 PM - 11:00 PM)
#   11-12 AM:  300 -  360 (11:00 PM - 12:00 AM)
#   After 12 AM: 360 - 600 (12:00 AM - 4:00 AM)
NIGHT_BUCKETS = [
    ("6-8 PM", 0, 120),
    ("8-9 PM", 120, 180),
    ("9-10 PM", 180, 240),
    ("10-11 PM", 240, 300),
    ("11-12 AM", 300, 360),
    ("After 12 AM", 360, 600),
]


def minutes_since_6pm(raw_minutes):
    """Wall-clock minutes-since-midnight (0-1439) -> minutes since 6 PM, wrapping post-midnight hours (0:xx-5:xx) onto the END of the same night instead of back to its own start — so NIGHT_BUCKETS never needs to wrap across midnight itself."""
    six_pm = 18 * 60
    return raw_minutes - six_pm if raw_minutes >= six_pm else raw_minutes + (24 * 60 - six_pm)
TCJ_LABEL = "Tea/Coffee/Juice"

# ponytail: keyword heuristic on the free-text Items column, not a real
# category field — expand if a new drink name slips through wrong. ANY
# item mentioning one of these counts the WHOLE order as Tea/Coffee/Juice,
# even if that item also mentions other things (e.g. a combo/counter SKU
# like "Juice,Milkshakes,Icecreams,Softdrinksand Cigaretts" counts,
# because it says "Juice") — same rule as t44_last_15_days_combined_revenue.py.
QUALIFY_KEYWORDS = ("tea", "coffee", "chai", "juice")


def has_tea_coffee_juice_item(items_text):
    items = [i.strip() for i in (items_text or "").split(",") if i.strip()]
    return any(any(good in item.lower() for good in QUALIFY_KEYWORDS) for item in items)


def load_orders(xlsx_path):
    """
    Returns list of (created: datetime, amount: float, sub_order_type: str,
    items: str) for every non-cancelled order whose Order No does NOT start
    with "C". Does NOT filter to AC only — every order type counts, both
    daytime and night. Uses group_orders() (t44_ac_sales_report.py) so a
    split/part-payment order's amount — spread across continuation rows in
    the raw sheet — is correctly merged back onto its order instead of
    read as ₹0.
    """
    orders = group_orders(xlsx_path)
    return [
        (o["created"], o["amount"], o["sub_order_type"], o["items"])
        for o in orders
        if o["status"] != "Cancelled" and not (isinstance(o["order_no"], str) and o["order_no"].upper().startswith("C"))
    ]


def fold_business_date(dt):
    """Before 4 AM belongs to the PREVIOUS business day (same 4 AM cutoff the bus-bay report uses); else same calendar day."""
    return dt.date() - timedelta(days=1) if dt.hour < 4 else dt.date()


def indian_format(n):
    """1234567 -> "12,34,567" (lakh/crore grouping: last 3 digits, then pairs)."""
    s = str(int(round(n)))
    if len(s) <= 3:
        return s
    last3, rest = s[-3:], s[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return ",".join(parts) + "," + last3


def bucket_label(minutes, buckets):
    if minutes is None:
        return None
    return next((lbl for lbl, start, end in buckets if start <= minutes < end), None)


def assign_bus_slot(arrival_str, departure_str, buckets):
    """
    Assigns a bus to whichever NIGHT_BUCKETS slot holds the MAJORITY of its
    check-in-to-checkout duration — not just its check-in instant. Replaces
    the earlier 10-minute-buffer approach.

    Picking the slot with the single largest overlap is equivalent to "the
    slot with >=66% of the duration" whenever one exists (two slots can't
    both hold a majority of the same total), and gives a sensible, always-
    deterministic fallback on the rare case nothing reaches 66% (e.g. an
    unusually long stop split close to evenly across 3+ slots) — so no
    separate percentage check is needed.

        6:45-7:45 -> 15 min in "6-8 PM" vs ... both halves are inside the
        same 2-hour "6-8 PM" bucket here, so that pair doesn't cross a real
        boundary; a bus spanning a REAL one, e.g. 7:55-8:15 (5 min left of
        "6-8 PM", 15 min into "8-9 PM"), is assigned "8-9 PM".

    Returns None if either time is unparseable or checkout isn't after check-in.
    """
    arrival = parse_ampm(arrival_str)
    departure = parse_ampm(departure_str)
    if arrival is None or departure is None:
        return None
    start, end = minutes_since_6pm(arrival), minutes_since_6pm(departure)
    if end <= start:  # malformed/zero-length after the 6 PM-anchored conversion — skip rather than guess
        return None
    best_label, best_overlap = None, 0
    for label, b_start, b_end in buckets:
        overlap = max(0, min(end, b_end) - max(start, b_start))
        if overlap > best_overlap:
            best_label, best_overlap = label, overlap
    return best_label


def main():
    xlsx_path = find_latest_excel()
    print(f"Reading {os.path.basename(xlsx_path)}", file=sys.stderr)
    orders = load_orders(xlsx_path)
    if not orders:
        sys.exit("No orders found in the Excel (after excluding Cancelled and C-prefixed Order Nos)")

    # One file = one business day (per the stated workflow) — pick the date
    # most orders fold to, so a stray sliver from an adjacent day can't
    # hijack the report date.
    counts = defaultdict(int)
    for created, _, _, _ in orders:
        counts[fold_business_date(created)] += 1
    report_date = max(counts, key=counts.get)
    print(f"Report date: {report_date}", file=sys.stderr)

    day_sales = defaultdict(float)  # day-slot label -> amount (ALL orders)
    night_sales = defaultdict(float)  # night-bucket label -> amount, EXCLUDING tea/coffee/juice orders
    tcj_total = 0.0  # tea/coffee/juice-only amount, carved out of "After 12 AM"
    for created, amount, sub_order_type, items in orders:
        if fold_business_date(created) != report_date:
            continue
        minutes = created.hour * 60 + created.minute
        day_label = bucket_label(minutes, DAY_SLOTS)
        if day_label:
            day_sales[day_label] += amount
            continue
        night_label = bucket_label(minutes_since_6pm(minutes), NIGHT_BUCKETS)
        if night_label == "After 12 AM" and has_tea_coffee_juice_item(items):
            tcj_total += amount
        elif night_label:
            night_sales[night_label] += amount

    buses = fetch_buses(report_date)
    buses_by_window = defaultdict(list)
    for b in buses:
        label = assign_bus_slot(b.get("arrival"), b.get("departure"), NIGHT_BUCKETS)
        if label:
            buses_by_window[label].append((b.get("operator"), normalize_bus_number(b.get("bus_number"))))

    total_sales = sum(day_sales.values()) + sum(night_sales.values()) + tcj_total
    bus_count = count_distinct_buses(buses)
    lines = [f"{report_date.strftime('%d %b')}, {bus_count} buses stopped at T-44, Total Sales = ₹{indian_format(total_sales)}"]

    for label, _, _ in DAY_SLOTS:
        lines.append(f"{label}: ₹{day_sales.get(label, 0.0):.0f}")

    for label, _, _ in NIGHT_BUCKETS:
        entries = buses_by_window.get(label, [])
        seen = set()
        op_counts = defaultdict(int)
        for op, bus_no in entries:
            if bus_no in seen:
                continue
            seen.add(bus_no)
            op_counts[op or "?"] += 1
        distinct_count = len(seen)
        breakdown = ", ".join(f"{c} {op}" for op, c in sorted(op_counts.items(), key=lambda kv: -kv[1]))
        bus_word = "bus" if distinct_count == 1 else "buses"
        line = f"{label}: {distinct_count} {bus_word}, ₹{night_sales.get(label, 0.0):.0f}"
        if breakdown:
            line += f" ({breakdown})"
        lines.append(line)

    lines.append(f"{TCJ_LABEL}: ₹{tcj_total:.0f}")

    message = "\n\n".join(lines)
    print()
    print(message)
    print()
    print(f"(Daytime total: ₹{sum(day_sales.values()):.0f}, Night total: ₹{sum(night_sales.values()):.0f}, Tea/Coffee/Juice: ₹{tcj_total:.0f})", file=sys.stderr)


if __name__ == "__main__":
    main()
