"""
Backfill scripts/output: one SQL INSERT per business date found in the given
Excel, into the `terminal_daily_sales_report` table — same numbers/shape as
the live WhatsApp combined report (t44_allsotsrevenue_combinedmsg.py), just
written to a .sql file instead of printed, and looped over every date in
the sheet instead of "today" only.

Usage:
    python scripts/t44_backfill_daily_sales_report.py [path/to/Order_Listing.xlsx]

With no argument, picks the most recently modified Order_Listing_*.xlsx in
the project root (same convention as the other t44 scripts). Pass an
explicit path to backfill from an older/archived export instead.

Output: t44_daily_sales_backfill.sql in the project root — one INSERT INTO
terminal_daily_sales_report (...) VALUES (...) per business date, matching
the exact columns/format already seen in a live row from that table:
    report_date, bus_count, total_sales, day_total, night_total, tcj_total,
    order_count, slots (jsonb), message, generated_at, created_at
`idx` (the serial PK) is never inserted — left to the table's own default.
Per standing instruction, this script only WRITES the .sql file; running it
against the database is a separate, manual step done by the user themselves
(psql, or paste into the Supabase SQL editor).
"""
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t44_ac_sales_report import fetch_buses, parse_ampm, normalize_bus_number  # noqa: E402
from t44_allsotsrevenue_combinedmsg import (  # noqa: E402
    DAY_SLOTS,
    NIGHT_BUCKETS,
    TCJ_LABEL,
    assign_bus_slot,
    bucket_label,
    fold_business_date,
    has_tea_coffee_juice_item,
    indian_format,
    load_orders,
    minutes_since_6pm,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_latest_excel():
    files = glob.glob(os.path.join(REPO_ROOT, "Order_Listing_*.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    if not files:
        sys.exit(f"No Order_Listing_*.xlsx found in {REPO_ROOT}")
    return max(files, key=os.path.getmtime)


def sql_str(value):
    """Single-quote a string for SQL, doubling any embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def build_report(bdate, orders_for_day):
    day_sales = defaultdict(float)
    night_sales = defaultdict(float)
    tcj_total = 0.0
    for created, amount, _sub_order_type, items in orders_for_day:
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

    buses = fetch_buses(bdate)
    buses_by_window = defaultdict(list)
    for b in buses:
        label = assign_bus_slot(b.get("arrival"), b.get("departure"), NIGHT_BUCKETS)
        if label:
            buses_by_window[label].append((b.get("operator"), normalize_bus_number(b.get("bus_number"))))

    bus_count = len({normalize_bus_number(b.get("bus_number")) for b in buses})
    day_total = sum(day_sales.values())
    night_total = sum(night_sales.values())
    total_sales = day_total + night_total + tcj_total

    slots = []
    lines = [f"{bdate.strftime('%d %b')}, {bus_count} buses stopped at T-44, Total Sales = ₹{indian_format(total_sales)}"]

    for label, _, _ in DAY_SLOTS:
        amt = day_sales.get(label, 0.0)
        slots.append({"kind": "day", "buses": None, "label": label, "amount": round(amt), "breakdown": []})
        lines.append(f"{label}: ₹{amt:.0f}")

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
        breakdown = sorted(op_counts.items(), key=lambda kv: -kv[1])
        amt = night_sales.get(label, 0.0)
        slots.append({
            "kind": "night",
            "buses": distinct_count,
            "label": label,
            "amount": round(amt),
            "breakdown": [{"count": c, "operator": op} for op, c in breakdown],
        })
        bus_word = "bus" if distinct_count == 1 else "buses"
        breakdown_str = ", ".join(f"{c} {op}" for op, c in breakdown)
        line = f"{label}: {distinct_count} {bus_word}, ₹{amt:.0f}"
        if breakdown_str:
            line += f" ({breakdown_str})"
        lines.append(line)

    slots.append({"kind": "tcj", "buses": None, "label": TCJ_LABEL, "amount": round(tcj_total), "breakdown": []})
    lines.append(f"{TCJ_LABEL}: ₹{tcj_total:.0f}")

    message = "\n\n".join(lines)
    return {
        "report_date": bdate,
        "bus_count": bus_count,
        "total_sales": total_sales,
        "day_total": day_total,
        "night_total": night_total,
        "tcj_total": tcj_total,
        "order_count": len(orders_for_day),
        "slots": slots,
        "message": message,
    }


def main():
    xlsx_path = sys.argv[1] if len(sys.argv) > 1 else find_latest_excel()
    print(f"Reading {os.path.basename(xlsx_path)}", file=sys.stderr)
    orders = load_orders(xlsx_path)
    if not orders:
        sys.exit("No orders found (after excluding Cancelled and C-prefixed Order Nos)")

    orders_by_date = defaultdict(list)
    for o in orders:
        orders_by_date[fold_business_date(o[0])].append(o)
    business_dates = sorted(orders_by_date)
    print(f"Business dates found: {business_dates[0]} to {business_dates[-1]} ({len(business_dates)} day(s))", file=sys.stderr)

    now_iso = datetime.now(timezone.utc).isoformat()
    out_path = os.path.join(REPO_ROOT, "t44_daily_sales_backfill.sql")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- Backfill for terminal_daily_sales_report — generated by t44_backfill_daily_sales_report.py\n")
        f.write("-- Run this yourself (psql / Supabase SQL editor) — not executed automatically.\n\n")
        for bdate in business_dates:
            report = build_report(bdate, orders_by_date[bdate])
            slots_json = json.dumps(report["slots"], ensure_ascii=False)
            f.write(
                "INSERT INTO terminal_daily_sales_report "
                "(report_date, bus_count, total_sales, day_total, night_total, tcj_total, order_count, slots, message, generated_at, created_at)\n"
                "VALUES (\n"
                f"  {sql_str(report['report_date'].isoformat())}::date,\n"
                f"  {report['bus_count']},\n"
                f"  {report['total_sales']:.2f},\n"
                f"  {report['day_total']:.2f},\n"
                f"  {report['night_total']:.2f},\n"
                f"  {report['tcj_total']:.2f},\n"
                f"  {report['order_count']},\n"
                f"  {sql_str(slots_json)}::jsonb,\n"
                f"  {sql_str(report['message'])},\n"
                f"  {sql_str(now_iso)}::timestamptz,\n"
                f"  {sql_str(now_iso)}::timestamptz\n"
                ");\n\n"
            )
    print(f"Wrote {out_path} ({len(business_dates)} INSERT statement(s))", file=sys.stderr)


if __name__ == "__main__":
    main()
