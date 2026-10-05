"""
Terminal 44 full-day combined revenue report, written to CSV, for every
business date found in the given Excel (export the last 15 days and you
get 15 days of rows — the script doesn't hardcode "15", it just processes
whatever dates are in the file, same as the other scripts here).

Same slot structure as t44_allsotsrevenue_combinedmsg.py: 3 daytime revenue
slots (no bus data) + 6 night slots (bus count + revenue), ALL order types
count (no AC-only filter), same exclusions (Status="Cancelled", Order No
starting with "C").

New in this one: within "After 12 AM", an order that MENTIONS tea/coffee/
juice anywhere in its Items gets pulled out into its own
"Tea/Coffee/Juice (post 12)" row instead of counting in "After 12 AM" —
so "After 12 AM" becomes everything else in that window, and the
beverage-related revenue is visible on its own line, per the handwritten
layout this was modeled on. Confirmed against real data (3 Oct business
day, Order_Listing_2026_10_05_11_36_23.xlsx): a single combo/counter item
named "Juice,Milkshakes,Icecreams,Softdrinksand Cigaretts" (₹6,095) is
counted here, in Tea/Coffee/Juice, not in After 12 AM — by request, even
though that one item also mentions milkshakes/icecream/cigarettes.

Usage:
    python scripts/t44_last_15_days_combined_revenue.py

Drop the Excel in the project root, same as the other scripts — picks the
most recently modified Order_Listing_2026_15Septo5Oct.xlsx automatically.

Output: t44_last_15_days_combined_revenue.csv in the project root.
Columns: Date, Slot, Amount, Buses, Operators (Buses/Operators are blank
for the 3 daytime slots, the Tea/Coffee/Juice line, and the Total line —
only the 6 night windows have bus data). One "Total" row per date = the
full day's revenue (daytime + night + Tea/Coffee/Juice all included).
"""
import glob
import os
import sys
from collections import defaultdict
from datetime import timedelta

# Windows terminals default to cp1252, which can't encode ₹ — force UTF-8.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# This script finds its own Excel file — independent of t44_ac_sales_report.py.
# Still reuses its bus/Grand-Total loaders below (those aren't "file allocation").
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t44_ac_sales_report import fetch_buses, parse_ampm, group_orders  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_latest_excel():
    """file upload kro"""
    files = glob.glob(os.path.join(REPO_ROOT, "Order_Listing_2026_15Septo5Oct.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]  # skip Excel lock files
    if not files:
        sys.exit(f"No Order_Listing_2026_15Septo5Oct.xlsx found in {REPO_ROOT}")
    return max(files, key=os.path.getmtime)


DAY_SLOTS = [
    ("7 AM-12 PM", 7 * 60, 12 * 60),
    ("12 PM-4 PM", 12 * 60, 16 * 60),
    ("4 PM-6 PM", 16 * 60, 18 * 60),
]
NIGHT_BUCKETS = [
    ("6-8 PM", 18 * 60, 20 * 60),
    ("8-9 PM", 20 * 60, 21 * 60),
    ("9-10 PM", 21 * 60, 22 * 60),
    ("10-11 PM", 22 * 60, 23 * 60),
    ("11-12 AM", 23 * 60, 24 * 60),
    ("After 12 AM", 0, 18 * 60),  # wraps to next calendar day; DAY_SLOTS claims 7am+ first
]
TCJ_LABEL = "Tea/Coffee/Juice (post 12)"

# ponytail: keyword heuristic on the free-text Items column, not a real
# category field — expand if a new drink name slips through wrong. By
# request, ANY item mentioning one of these counts the WHOLE order as
# Tea/Coffee/Juice, even if that item also mentions other things (e.g. a
# combo/counter SKU like "Juice,Milkshakes,Icecreams,Softdrinksand
# Cigaretts" counts, because it says "Juice") — confirmed against real
# data, see module docstring.
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

    day_sales = defaultdict(float)     # (date, day-slot label) -> amount
    night_sales = defaultdict(float)   # (date, night-bucket label) -> amount, EXCLUDING tea/coffee/juice-only orders
    tcj_sales = defaultdict(float)     # date -> tea/coffee/juice-only amount (post-12 window only)

    for o in orders:
        bdate = fold_business_date(o["created"])
        minutes = o["created"].hour * 60 + o["created"].minute
        day_label = bucket_label(minutes, DAY_SLOTS)
        if day_label:
            day_sales[(bdate, day_label)] += o["amount"]
            continue
        night_label = bucket_label(minutes, NIGHT_BUCKETS)
        if night_label == "After 12 AM" and has_tea_coffee_juice_item(o["items"]):
            tcj_sales[bdate] += o["amount"]
        elif night_label:
            night_sales[(bdate, night_label)] += o["amount"]

    rows = []  # (date, slot, amount, buses, operators)
    for bdate in business_dates:
        buses = fetch_buses(bdate)
        buses_by_window = defaultdict(list)
        for b in buses:
            label = bucket_label(parse_ampm(b.get("arrival")), NIGHT_BUCKETS)
            if label:
                buses_by_window[label].append(b.get("operator"))

        day_total = 0.0
        for label, _, _ in DAY_SLOTS:
            amt = day_sales.get((bdate, label), 0.0)
            day_total += amt
            rows.append((bdate, label, amt, "", ""))

        for label, _, _ in NIGHT_BUCKETS:
            ops = buses_by_window.get(label, [])
            op_counts = defaultdict(int)
            for op in ops:
                op_counts[op or "?"] += 1
            breakdown = ", ".join(f"{c} {op}" for op, c in sorted(op_counts.items(), key=lambda kv: -kv[1]))
            amt = night_sales.get((bdate, label), 0.0)
            day_total += amt
            rows.append((bdate, label, amt, len(ops), breakdown))

        tcj_amt = tcj_sales.get(bdate, 0.0)
        day_total += tcj_amt
        rows.append((bdate, TCJ_LABEL, tcj_amt, "", ""))
        rows.append((bdate, "Total", day_total, "", ""))

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "t44_last_15_days_combined_revenue.csv")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("Date,Slot,Amount,Buses,Operators\n")
        for bdate, slot, amt, buses_n, ops in rows:
            ops_field = f'"{ops}"' if "," in ops else ops
            f.write(f"{bdate.strftime('%d %b %Y')},{slot},{amt:.0f},{buses_n},{ops_field}\n")

    print(f"Wrote {out_path} ({len(rows)} rows, {len(business_dates)} day(s))", file=sys.stderr)


if __name__ == "__main__":
    main()
