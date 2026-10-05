"""
Terminal 44 combined report: AC-billing sales + bus check-ins, per date and
per time window.

Usage:
    python scripts/t44_ac_sales_report.py

No date configuration needed — the date range is read straight from the
Excel's own 'Created' column (earliest business date to latest). Optional
override: python scripts/t44_ac_sales_report.py [YYYY-MM-DD] [YYYY-MM-DD].

Reusability: just drop a newer "Order Listing" export (Petpooja's
`Order_Listing_*.xlsx` file) into the project root and re-run — the script
always picks the most recently modified one, no filename/column edits needed.

Columns confirmed by inspecting Order_Listing_2026_09_29_01_53_11.xlsx
(header row 5, 0-indexed row 4):
    'Sub Order Type' -> AC / Dine In / Drivers filter
    'Grand Total (₹)' -> billing amount used for "Total AC Sales"
    'Created'         -> "28 Sep 2026 23:51:54" (billing date/time)
    'Status'          -> 'Printed' / 'Cancelled' / None
        Cancelled orders are excluded from sales — a cancelled order isn't
        real revenue. Rows with no Status (no 'Created' timestamp either)
        are skipped as incomplete.
There is no bus/service number column in this sheet; bus check-in data
comes from the same Supabase RPC (t44_bus_bay_report) the Terminal 44
WhatsApp report already uses, matched to the same date/window logic.
"""
import glob
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import openpyxl
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = timezone(timedelta(hours=5, minutes=30))

# Same 5 windows as the WhatsApp T44 bus report (src/t44Buses/index.js),
# keyed by minutes-since-midnight so "After 12 AM" can wrap past midnight.
WINDOWS = [
    ("7:30 PM - 9:00 PM", 19 * 60 + 30, 21 * 60),
    ("9:00 PM - 10:00 PM", 21 * 60, 22 * 60),
    ("10:00 PM - 11:00 PM", 22 * 60, 23 * 60),
    ("11:00 PM - 12:00 AM", 23 * 60, 24 * 60),
    ("12:00 AM onwards", 0, 19 * 60 + 30),  # wraps to next calendar day, capped at 4 AM below
]


def read_env(key):
    """Minimal .env reader — avoids adding python-dotenv for two values."""
    env_path = os.path.join(REPO_ROOT, ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return None


def find_latest_excel():
    files = glob.glob(os.path.join(REPO_ROOT, "Order_Listing_2026_Oct3to5.xlsx.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]  # skip Excel lock files
    if not files:
        sys.exit(f"No Order_Listing_*.xlsx found in {REPO_ROOT}")
    return max(files, key=os.path.getmtime)


def group_orders(xlsx_path):
    """
    Returns list of dicts {order_no, created: datetime, status, sub_order_type, amount, items}
    — one per ORDER, not per row. A split/part-payment order's real amount is NOT
    on its main row: Petpooja writes the main row's own Grand Total as 0 and puts
    each payment method's share (UPI/Cash/Not Paid) on separate CONTINUATION rows
    right after it, which repeat the same Order No but leave Created/Status/Sub
    Order Type blank. A naive per-row read (the old load_ac_orders) skipped those
    blank-Created rows entirely, silently counting every split-payment order as
    ₹0 — confirmed against real data (Order_Listing_2026_10_02_11_36_37.xlsx):
    the correct grouped total for 1 Oct was ₹231,750, a plain per-row read with
    the same filters gave ₹202,352. This groups by Order No so continuation
    rows' amounts land back on their parent order instead of being dropped.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(min_row=5, values_only=True)
    header = next(rows)
    col = {name: i for i, name in enumerate(header)}
    for required in ("Order No.", "Sub Order Type", "Grand Total (₹)", "Created", "Status", "Items"):
        if required not in col:
            sys.exit(f"Expected column {required!r} not found — sheet layout changed. Header: {header}")

    orders = []
    current = None
    for r in rows:
        amount = float(r[col["Grand Total (₹)"]] or 0)
        if r[col["Created"]]:
            if current:
                orders.append(current)
            current = {
                "order_no": r[col["Order No."]],
                "created": datetime.strptime(r[col["Created"]], "%d %b %Y %H:%M:%S"),
                "status": r[col["Status"]],
                "sub_order_type": r[col["Sub Order Type"]],
                "amount": amount,
                "items": r[col["Items"]] or "",
            }
        elif current is not None and r[col["Order No."]] == current["order_no"]:
            current["amount"] += amount  # continuation row — same order, extra payment-method split
    if current:
        orders.append(current)
    return orders


def load_ac_orders(xlsx_path):
    """Returns list of (created: datetime, amount: float) for non-cancelled AC orders, with split-payment amounts merged (see group_orders)."""
    orders = group_orders(xlsx_path)
    return [
        (o["created"], o["amount"])
        for o in orders
        if o["sub_order_type"] == "AC" and o["status"] != "Cancelled"
    ]


def business_date_and_window(dt):
    """
    A timestamp before 7:30 PM belongs to the PREVIOUS business day's
    "12:00 AM onwards" window (capped at 4 AM, same as the bus report);
    anything from 7:30 PM onward belongs to that calendar day.
    """
    minutes = dt.hour * 60 + dt.minute
    if minutes < 4 * 60:
        return dt.date() - timedelta(days=1), "12:00 AM onwards"
    if minutes < 19 * 60 + 30:
        return None, None  # outside every window (4 AM - 7:30 PM) — not reported
    for label, start, end in WINDOWS[:-1]:
        if start <= minutes < end:
            return dt.date(), label
    return dt.date(), "12:00 AM onwards"


def bucket_sales(orders, dates):
    sales = defaultdict(float)  # (date, window_label) -> amount
    for created, amount in orders:
        bdate, label = business_date_and_window(created)
        if bdate in dates:
            sales[(bdate, label)] += amount
    return sales


def fetch_buses(date_):
    """Same window contract as windowForDate() in src/t44Buses/index.js: that day 06:00 IST -> next day 04:00 IST."""
    supabase_url = read_env("SUPABASE_URL")
    service_key = read_env("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in .env")

    day_start = datetime(date_.year, date_.month, date_.day, 6, 0, tzinfo=IST)
    next_day_end = day_start + timedelta(days=1, hours=-2)  # next day 04:00 IST
    resp = requests.post(
        f"{supabase_url}/rest/v1/rpc/t44_bus_bay_report",
        json={"p_from": day_start.isoformat(), "p_to": next_day_end.isoformat()},
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_ampm(time_str):
    """'8:15 PM' -> minutes since midnight, or None if unparseable."""
    m = re.match(r"^(\d{1,2}):(\d{2})\s(AM|PM)$", time_str or "")
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3) == "PM":
        h += 12
    return h * 60 + int(m.group(2))


def bucket_buses(buses):
    """{(window_label): [(operator, bus_number, arrival_str), ...]} for one date's bus list, keyed by CHECK-IN (arrival) time — same as the WhatsApp report."""
    out = defaultdict(list)
    for b in buses:
        minutes = parse_ampm(b.get("arrival"))
        if minutes is None:
            continue
        label = next((lbl for lbl, start, end in WINDOWS if start <= minutes < end), None)
        if label:
            out[label].append((b.get("operator"), b.get("bus_number"), b.get("arrival")))
    return out


def csv_field(value):
    s = "" if value is None else str(value)
    if any(c in s for c in (",", '"', "\n")):
        return '"' + s.replace('"', '""') + '"'
    return s


def parse_date_arg(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    xlsx_path = find_latest_excel()
    print(f"Reading {os.path.basename(xlsx_path)}")
    orders = load_ac_orders(xlsx_path)

    if len(sys.argv) >= 3:
        start, end = parse_date_arg(sys.argv[1]), parse_date_arg(sys.argv[2])
    elif len(sys.argv) == 2:
        start = end = parse_date_arg(sys.argv[1])
    else:
        # No args -> read the range straight from the Excel itself (earliest
        # to latest business date among the AC orders just loaded).
        business_dates = {business_date_and_window(created)[0] for created, _ in orders}
        business_dates.discard(None)
        if not business_dates:
            sys.exit("No AC orders with a usable Created date found in the Excel")
        start, end = min(business_dates), max(business_dates)

    dates = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    print(f"Date range: {start} to {end} ({len(dates)} day(s))")

    sales = bucket_sales(orders, set(dates))

    out_rows = []
    for date_ in dates:
        print(f"Fetching bus check-ins for {date_} ...")
        buses = fetch_buses(date_)
        buses_by_window = bucket_buses(buses)
        for label, _, _ in WINDOWS:
            bus_list = buses_by_window.get(label, [])
            amount = sales.get((date_, label), 0.0)
            counts = defaultdict(int)
            for op, _, _ in bus_list:
                counts[op or "?"] += 1
            operator_summary = ", ".join(
                f"{op} - {c}" for op, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            )
            out_rows.append(
                [date_.strftime("%d %b %Y"), label, f"{amount:.2f}", len(bus_list), operator_summary]
            )

    out_path = os.path.join(REPO_ROOT, "t44_ac_sales_report.csv")
    headers = ["Date", "Time Window", "Total AC Sales", "Number of Buses Checked In", "Operator Summary"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(",".join(csv_field(h) for h in headers) + "\n")
        for row in out_rows:
            f.write(",".join(csv_field(v) for v in row) + "\n")

    print(f"Wrote {out_path} ({len(out_rows)} rows)")


if __name__ == "__main__":
    main()
