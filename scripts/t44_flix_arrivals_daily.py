"""
Daily Terminal 44 Flix arrival tracker — pairwise vehicle check against the
known route roster, same shape as the Terminal_44_OCT_arrivals_*.xlsx files
already being hand-updated.


#
python t44_flix_arrivals_daily.py --date 2026-10-25




Each scheduled route has TWO possible vehicle numbers (the operator swaps
which physical vehicle runs a route day to day). For the target date, each
roster row is checked against that day's real check-ins:
    - only Vehicle-1 showed up  -> "VEH1 (H:MM AM/PM)"
    - only Vehicle-2 showed up  -> "VEH2 (H:MM AM/PM)"
    - both showed up            -> "VEH1 (time); VEH2 (time)"
    - neither showed up         -> "-"
Any vehicle that checked in that day but isn't either pair in any roster
row is appended as a new "(new)" row below, with its own check-in time —
same convention as the existing file's bottom rows.

Check-in data source: the same t44_bus_bay_report Supabase RPC and 4 AM -
next 4 AM IST operational-day window already used by
scripts/t44_ac_sales_report.py and src/t44Buses/index.js — not a new
data source, just reused here.

Usage:
    python scripts/t44_flix_arrivals_daily.py                  (yesterday, IST — today's day isn't over yet)
    python scripts/t44_flix_arrivals_daily.py --date 2026-10-25
    python scripts/t44_flix_arrivals_daily.py --date 2026-10-25 --roster Terminal_44_OCT_arrivals_23.xlsx --out Terminal_44_OCT_arrivals_25.xlsx

Roster source: reads ONLY columns A-G (Line Code, UID, Departure Station,
Arrival Station, Departure Time, Vehicle Number-1, Vehicle Number-2) from
the roster workbook, stopping at the first "(new)" row or the trailing
"Total buses=" row — so it's safe to point --roster at any previous day's
output file; its own date column(s) and new-vehicle rows are ignored, only
the fixed route/pair list is reused. Run this every day pointing --roster
at whichever file was produced the day before (or just keep using the same
base roster file — the route/pair list itself doesn't change day to day).
"""
import argparse

import glob
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import openpyxl
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = timezone(timedelta(hours=5, minutes=30))

ROSTER_HEADERS = [
    "Line Code", "UID", "Departure Station", "Arrival Station",
    "Departure Time", "Vehicle Number-1", "Vehicle Number-1",
]


def read_env(key):
    """Minimal .env reader — avoids adding python-dotenv for two values
    (same approach as t44_ac_sales_report.py)."""
    env_path = os.path.join(REPO_ROOT, ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return None


def normalize_bus_number(bus_number):
    """Upper-case, strip spaces/tabs/NBSP — two bus numbers that only
    differ by whitespace or case count as the SAME bus (same rule
    t44_ac_sales_report.py uses)."""
    if not bus_number:
        return ""
    return re.sub(r"[ \t\xa0]", "", bus_number).upper()


def parse_ampm(time_str):
    """'8:15 PM' -> minutes since midnight, or None if unparseable."""
    m = re.match(r"^(\d{1,2}):(\d{2})\s(AM|PM)$", time_str or "")
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3) == "PM":
        h += 12
    return h * 60 + int(m.group(2))


def fetch_buses(date_):
    """Same operational-day window as t44_ac_sales_report.py: that day
    04:00 IST -> next day 04:00 IST, via the t44_bus_bay_report RPC."""
    supabase_url = read_env("SUPABASE_URL")
    service_key = read_env("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in .env")

    day_start = datetime(date_.year, date_.month, date_.day, 4, 0, tzinfo=IST)
    next_day_end = day_start + timedelta(days=1)
    resp = requests.post(
        f"{supabase_url}/rest/v1/rpc/t44_bus_bay_report",
        json={"p_from": day_start.isoformat(), "p_to": next_day_end.isoformat()},
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def is_flix(operator):
    """Terminal 44 serves many operators (KSRTC, TGSRTC, IntrCity, several
    private travels, ...) — the roster here is Flix-only, so anything else
    must be filtered out before roster-matching/new-vehicle detection,
    otherwise every other operator's bus shows up as a false '(new)' row."""
    return "flix" in (operator or "").lower()


def build_arrivals_map(buses):
    """normalized bus_number -> earliest 'H:MM AM/PM' check-in string that
    day, Flix buses only. The RPC already returns rows ordered by arrival
    time (see today_expectancy_lookup.sql's convention), so the first
    occurrence of a bus number is its earliest check-in; a later duplicate
    (re-check-in) is intentionally ignored rather than overwriting the first."""
    arrivals = {}
    for b in buses:
        if not is_flix(b.get("operator")):
            continue
        key = normalize_bus_number(b.get("bus_number"))
        if key and key not in arrivals and parse_ampm(b.get("arrival")) is not None:
            arrivals[key] = b.get("arrival")
    return arrivals


def find_default_roster():
    # Matches any naming variant: "..._23.xlsx", "... (2).xlsx" (Windows'
    # auto-rename on a re-download), or a bare "...arrivals.xlsx" — not
    # just an underscore-plus-day suffix.
    files = glob.glob(os.path.join(REPO_ROOT, "Terminal_44_OCT_arrivals*.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    if not files:
        sys.exit("No Terminal_44_OCT_arrivals*.xlsx found to use as --roster — pass one explicitly")
    return max(files, key=os.path.getmtime)


def load_roster(xlsx_path):
    """Returns list of dicts, one per scheduled route row:
    {line_code, uid, dep_station, arr_station, dep_time, veh1, veh2}.
    Stops at the first '(new)' row or the trailing 'Total buses=' row —
    only columns A-G are read, any existing date column(s) are ignored."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(min_row=2, max_col=7, values_only=True)
    roster = []
    for r in rows:
        line_code = r[0]
        if line_code is None or line_code == "(new)":
            break
        roster.append({
            "line_code": line_code, "uid": r[1], "dep_station": r[2],
            "arr_station": r[3], "dep_time": r[4], "veh1": r[5], "veh2": r[6],
        })
    if not roster:
        sys.exit(f"No roster rows found in {xlsx_path} — expected route rows starting at row 2")
    return roster


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: yesterday, IST — today's check-ins aren't complete until the day is over)")
    parser.add_argument("--roster", help="Workbook to read the route/pair roster from (default: newest Terminal_44_OCT_arrivals*.xlsx)")
    parser.add_argument("--out", help="Output .xlsx path (default: Terminal_44_OCT_arrivals_<day>.xlsx)")
    args = parser.parse_args()

    target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(IST).date() - timedelta(days=1)
    roster_path = args.roster or find_default_roster()
    out_path = args.out or os.path.join(REPO_ROOT, f"Terminal_44_OCT_arrivals_{target_date.day}.xlsx")

    print(f"Roster: {os.path.basename(roster_path)}")
    roster = load_roster(roster_path)
    print(f"Target date: {target_date} ({len(roster)} scheduled route rows)")

    buses = fetch_buses(target_date)
    arrivals = build_arrivals_map(buses)
    print(f"Fetched {len(buses)} check-ins total, {len(arrivals)} distinct Flix buses, for {target_date}")

    date_col_header = target_date.strftime("%d %b").lstrip("0")  # '25 Oct', no leading zero (matches existing files)
    claimed = set()
    out_rows = []  # (line_code, uid, dep_station, arr_station, dep_time, veh1, veh2, date_cell)

    for row in roster:
        veh1_norm, veh2_norm = normalize_bus_number(row["veh1"]), normalize_bus_number(row["veh2"])
        hits = []
        if veh1_norm and veh1_norm in arrivals:
            hits.append((row["veh1"], arrivals[veh1_norm]))
            claimed.add(veh1_norm)
        if veh2_norm and veh2_norm in arrivals:
            hits.append((row["veh2"], arrivals[veh2_norm]))
            claimed.add(veh2_norm)
        cell = "; ".join(f"{veh} ({time})" for veh, time in hits) if hits else "-"
        out_rows.append((row["line_code"], row["uid"], row["dep_station"], row["arr_station"],
                          row["dep_time"], row["veh1"], row["veh2"], cell))

    new_vehicle_count = 0
    for key, time in arrivals.items():
        if key in claimed:
            continue
        # Recover a presentable (non-normalized) form for display — the
        # original casing/spacing from whichever check-in row matched this key.
        original = next((b.get("bus_number") for b in buses if is_flix(b.get("operator")) and normalize_bus_number(b.get("bus_number")) == key), key)
        out_rows.append(("(new)", None, None, None, None, original, None, f"{original} ({time})"))
        new_vehicle_count += 1

    total_arrived = sum(1 for r in out_rows if r[7] != "-")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(ROSTER_HEADERS + [date_col_header])
    for r in out_rows:
        ws.append(list(r))
    ws.append([None, None, None, None, None, None, None, f"Total buses={total_arrived} "])

    wb.save(out_path)
    print(f"{new_vehicle_count} new (unlisted) vehicle(s) checked in today")
    print(f"Total buses arrived: {total_arrived} / {len(roster)} scheduled routes")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
