"""
Terminal 44 average revenue per bus, by night slot, summed across ALL
business dates found in the given Excel (export the last 15 days and you
get the 15-day average in one shot per slot — not broken out day by day).
Independent of the other t44_* scripts — finds its own Excel file, same
as t44_last_15_days_combined_revenue.py.

Avg revenue per bus for a slot = (total revenue across ALL days in that
slot) / (total buses across ALL days in that slot) — a ratio of sums, not
an average of each day's own ratio, so a day with 0 buses in a slot can't
divide-by-zero or skew the result disproportionately.

Revenue excludes Tea/Coffee/Juice orders out of "After 12 AM" (same split
as t44_last_15_days_combined_revenue.py's has_tea_coffee_juice_item) —
that revenue isn't tied to any bus arrival, so mixing it in would inflate
"per bus" for a slot where the buses and the beverage sales aren't
necessarily the same customers. Same exclusions as the other scripts:
Status="Cancelled" and Order No starting with "C" are dropped everywhere.
ALL order types count (no AC-only filter).

Only the 6 night slots are reported — "per bus" is undefined for the 2
daytime slots (7 AM-12 PM, 12 PM-4 PM), which have no bus data at all.

Usage:
    python scripts/t44_avg_revenue_per_bus.py

Drop the Excel in the project root, same as the other scripts — picks the
most recently modified Order_Listing_2026_15Septo5Oct.xlsx automatically.

Output: t44_avg_revenue_per_bus.csv in the project root, one row per
slot (6 rows total).
Columns: Slot, Total Revenue, Total Buses, Avg Revenue per Bus, Operators, Days Counted.
"""
import glob
import os
import sys
from collections import defaultdict
from datetime import timedelta

# Windows terminals default to cp1252, which can't encode ₹ — force UTF-8.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# This script finds its own Excel file — independent of the other scripts.
# Still reuses the bus/Grand-Total loaders below (those aren't "file allocation").
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t44_ac_sales_report import fetch_buses, parse_ampm, group_orders  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_latest_excel():
    """Picks the most recently modified Order_Listing_2026_15Septo5Oct.xlsx in the project root. Never hand-edit this to a literal filename — drop the new file in and it's picked up automatically."""
    files = glob.glob(os.path.join(REPO_ROOT, "Order_Listing_2026_15Septo5Oct.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]  # skip Excel lock files
    if not files:
        sys.exit(f"No Order_Listing_2026_15Septo5Oct.xlsx found in {REPO_ROOT}")
    return max(files, key=os.path.getmtime)


DAY_SLOTS = [
    ("7 AM-12 PM", 7 * 60, 12 * 60),
    ("12 PM-4 PM", 12 * 60, 16 * 60),
]
NIGHT_BUCKETS = [
    ("4-7 PM", 16 * 60, 19 * 60),
    ("7-9 PM", 19 * 60, 21 * 60),
    ("9-10 PM", 21 * 60, 22 * 60),
    ("10-11 PM", 22 * 60, 23 * 60),
    ("11-12 AM", 23 * 60, 24 * 60),
    ("After 12 AM", 0, 16 * 60),  # wraps to next calendar day; DAY_SLOTS claims 7am-4pm first
]

QUALIFY_KEYWORDS = ("tea", "coffee", "chai", "juice", "cappuccino", "latte", "espresso", "lassi")


def has_tea_coffee_juice_item(items_text):
    items = [i.strip() for i in (items_text or "").split(",") if i.strip()]
    return any(any(good in item.lower() for good in QUALIFY_KEYWORDS) for item in items)


def fold_business_date(dt):
    """Before 4 AM belongs to the PREVIOUS business day (same 4 AM cutoff the bus-bay report uses); else same calendar day."""
    return dt.date() - timedelta(days=1) if dt.hour < 4 else dt.date()


def bucket_label(minutes, buckets):
    if minutes is None:
        return None
    return next((lbl for lbl, start, end in buckets if start <= minutes < end), None)


def is_c_prefixed(order_no):
    return isinstance(order_no, str) and order_no.upper().startswith("C")


def main():
    xlsx_path = find_latest_excel()
    print(f"Reading {os.path.basename(xlsx_path)}", file=sys.stderr)
    orders = group_orders(xlsx_path)
    orders = [o for o in orders if o["status"] != "Cancelled" and not is_c_prefixed(o["order_no"])]
    if not orders:
        sys.exit("No orders found (after excluding Cancelled and C-prefixed Order Nos)")

    business_dates = sorted({fold_business_date(o["created"]) for o in orders})
    print(f"Business dates found: {business_dates[0]} to {business_dates[-1]} ({len(business_dates)} day(s))", file=sys.stderr)

    night_sales = defaultdict(float)  # (date, night-bucket label) -> amount, EXCLUDING tea/coffee/juice
    for o in orders:
        bdate = fold_business_date(o["created"])
        minutes = o["created"].hour * 60 + o["created"].minute
        if bucket_label(minutes, DAY_SLOTS):
            continue  # daytime — not bus-linked, skip entirely for this report
        night_label = bucket_label(minutes, NIGHT_BUCKETS)
        if night_label == "After 12 AM" and has_tea_coffee_juice_item(o["items"]):
            continue  # beverage-only, not tied to a bus — excluded from "per bus"
        if night_label:
            night_sales[(bdate, night_label)] += o["amount"]

    buses_by_window = defaultdict(list)  # (date, night-bucket label) -> [operator, ...]
    for bdate in business_dates:
        for b in fetch_buses(bdate):
            label = bucket_label(parse_ampm(b.get("arrival")), NIGHT_BUCKETS)
            if label:
                buses_by_window[(bdate, label)].append(b.get("operator"))

    rows = []  # (slot, total_revenue, total_buses, avg_per_bus, operators, days_counted)
    for label, _, _ in NIGHT_BUCKETS:
        total_revenue = sum(night_sales.get((d, label), 0.0) for d in business_dates)
        ops = [op for d in business_dates for op in buses_by_window.get((d, label), [])]
        op_counts = defaultdict(int)
        for op in ops:
            op_counts[op or "?"] += 1
        breakdown = ", ".join(f"{c} {op}" for op, c in sorted(op_counts.items(), key=lambda kv: -kv[1]))
        avg = total_revenue / len(ops) if ops else 0.0
        rows.append((label, total_revenue, len(ops), avg, breakdown, len(business_dates)))

    out_path = os.path.join(REPO_ROOT, "t44_avg_revenue_per_bus.csv")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("Slot,Total Revenue,Total Buses,Avg Revenue per Bus,Operators,Days Counted\n")
        for label, total_revenue, total_buses, avg, ops, days in rows:
            ops_field = f'"{ops}"' if "," in ops else ops
            f.write(f"{label},{total_revenue:.0f},{total_buses},{avg:.0f},{ops_field},{days}\n")

    print(f"Wrote {out_path} ({len(rows)} rows)", file=sys.stderr)


if __name__ == "__main__":
    main()
