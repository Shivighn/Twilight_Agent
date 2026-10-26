"""
Terminal 44 Flix arrival tracker — DATE RANGE version. Same pairwise
roster-vs-check-in logic as t44_flix_arrivals_daily.py, but produces ONE
combined workbook with a separate date column for every day in the range,
instead of running the daily script once per day by hand.

New (unlisted) vehicles are tracked across the WHOLE range as a single
set: a vehicle that's new on day 5 gets one row, with "-" for every day
before it first showed up and its own "VEH (time)"/"-" per day from then
on (filled for every day it actually checked in, "-" otherwise) — it does
NOT get folded into the fixed 33-route roster for later days.

Usage:
    python scripts/t44_flix_arrivals_range.py 1 23
        -> days 1 to 23 of the current IST month (inclusive)
    python scripts/t44_flix_arrivals_range.py 1 23 --month 2026-10
    python scripts/t44_flix_arrivals_range.py 1 23 --roster "Terminal_44_OCT_arrivals (2).xlsx" --out Terminal_44_OCT_arrivals_1_to_23.xlsx
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta

import openpyxl

from t44_flix_arrivals_daily import (
    REPO_ROOT, IST, ROSTER_HEADERS, normalize_bus_number, fetch_buses,
    build_arrivals_map, is_flix, find_default_roster, load_roster,
)


def daterange(start_day, end_day, year, month):
    d = date(year, month, start_day)
    end = date(year, month, end_day)
    while d <= end:
        yield d
        d += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("start_day", type=int, help="First day of the month to include (e.g. 1)")
    parser.add_argument("end_day", type=int, help="Last day of the month to include, inclusive (e.g. 23)")
    parser.add_argument("--month", help="YYYY-MM (default: current month, IST)")
    parser.add_argument("--roster", help="Workbook to read the route/pair roster from (default: newest Terminal_44_OCT_arrivals*.xlsx)")
    parser.add_argument("--out", help="Output .xlsx path (default: Terminal_44_OCT_arrivals_<start>_to_<end>.xlsx)")
    args = parser.parse_args()

    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
    else:
        now = datetime.now(IST)
        year, month = now.year, now.month

    if args.start_day > args.end_day:
        sys.exit(f"start_day ({args.start_day}) must be <= end_day ({args.end_day})")

    roster_path = args.roster or find_default_roster()
    out_path = args.out or os.path.join(REPO_ROOT, f"Terminal_44_OCT_arrivals_{args.start_day}_to_{args.end_day}.xlsx")

    print(f"Roster: {os.path.basename(roster_path)}")
    roster = load_roster(roster_path)
    dates = list(daterange(args.start_day, args.end_day, year, month))
    print(f"Range: {dates[0]} to {dates[-1]} ({len(dates)} day(s)), {len(roster)} scheduled route rows")

    # Per-day arrivals map, and the running set/order of new vehicles seen
    # anywhere in the range (first-seen order, so new rows read chronologically).
    per_day_arrivals = {}
    new_vehicle_order = []  # normalized keys, first-seen order
    new_vehicle_original = {}  # normalized key -> original display casing
    roster_claimed_keys = {normalize_bus_number(r["veh1"]) for r in roster} | {normalize_bus_number(r["veh2"]) for r in roster}

    for d in dates:
        buses = fetch_buses(d)
        arrivals = build_arrivals_map(buses)
        per_day_arrivals[d] = arrivals
        print(f"  {d}: {len(arrivals)} distinct Flix buses")
        for key, time in arrivals.items():
            if key in roster_claimed_keys:
                continue
            if key not in new_vehicle_original:
                original = next((b.get("bus_number") for b in buses
                                  if is_flix(b.get("operator")) and normalize_bus_number(b.get("bus_number")) == key), key)
                new_vehicle_original[key] = original
                new_vehicle_order.append(key)

    date_headers = [d.strftime("%d %b").lstrip("0") for d in dates]

    out_rows = []
    for row in roster:
        veh1_norm, veh2_norm = normalize_bus_number(row["veh1"]), normalize_bus_number(row["veh2"])
        cells = []
        for d in dates:
            arrivals = per_day_arrivals[d]
            hits = []
            if veh1_norm and veh1_norm in arrivals:
                hits.append((row["veh1"], arrivals[veh1_norm]))
            if veh2_norm and veh2_norm in arrivals:
                hits.append((row["veh2"], arrivals[veh2_norm]))
            cells.append("; ".join(f"{veh} ({time})" for veh, time in hits) if hits else "-")
        out_rows.append((row["line_code"], row["uid"], row["dep_station"], row["arr_station"],
                          row["dep_time"], row["veh1"], row["veh2"], *cells))

    for key in new_vehicle_order:
        original = new_vehicle_original[key]
        cells = [f"{original} ({per_day_arrivals[d][key]})" if key in per_day_arrivals[d] else "-" for d in dates]
        out_rows.append(("(new)", None, None, None, None, original, None, *cells))

    totals = [sum(1 for r in out_rows if r[7 + i] != "-") for i in range(len(dates))]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(ROSTER_HEADERS + date_headers)
    for r in out_rows:
        ws.append(list(r))
    ws.append([None, None, None, None, None, None, None] + [f"Total buses={t} " for t in totals])

    wb.save(out_path)
    print(f"{len(new_vehicle_order)} new (unlisted) vehicle(s) seen across the range")
    print(f"Wrote {out_path} ({len(dates)} date column(s))")


if __name__ == "__main__":
    main()
