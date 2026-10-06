"""
Live occupancy + ASP for the buses in 'todaysbuses expectancy.txt' that pass
Jadcherla between TODAY 19:00 and TOMORROW 03:00 — TODAY/TOMORROW/WINDOW are
computed from the current IST date every run, not hardcoded (see below).

Usage:  python todaysOccupancy.py             (live from Redbus)
        python todaysOccupancy.py --offline   (from layouts already saved by fetchStops.js; occupancy as of that save)
        python todaysOccupancy.py --cached    (redo the report from the last live fetch, no Redbus calls)
Output: todaysOccupancy_byBus.csv (one row per bus in your list), todaysOccupancy.csv (every matching Redbus bus)

Redbus hides nearly/fully sold-out buses from *today's* search, so the bus catalogue is built from
today's AND tomorrow's search (all pages, all operator groups like KSRTC/TGSRTC), then each bus's
seat layout is fetched for today.

Occupancy = sold seats / total seats (operator-blocked seats count as sold, Redbus can't tell them apart).
ASP       = average fare of the sold seats.
Sold out  = Redbus returns no layout today -> 100%, fares/stop times taken from tomorrow's layout.
Jadcherla time (est) = Shamshabad + 75 min, or last Hyderabad boarding point + 110 min (KSRTC/TGSRTC list only city stops).
"""
import csv, glob, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import requests

# A spawned child process's stdout isn't a real console, so Python falls
# back to the system codepage (cp1252 on Windows) instead of UTF-8 — that
# can't encode the ≈/❌/✅ characters this script prints. Same fix already
# applied to the other scripts/*.py files in this repo for the same reason.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# India has no DST, so a fixed +5:30 read off UTC is both correct and
# simple (same convention as src/terminal44/dateFormat.js) — avoids
# depending on the system clock's own timezone (a VPS is often UTC).
_IST_TODAY = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
TODAY, TOMORROW = _IST_TODAY.strftime("%d-%b-%Y"), (_IST_TODAY + timedelta(days=1)).strftime("%d-%b-%Y")
_WINDOW_START = datetime(_IST_TODAY.year, _IST_TODAY.month, _IST_TODAY.day, 19, 0)
WINDOW = (_WINDOW_START, _WINDOW_START + timedelta(hours=8))  # 19:00 today -> 03:00 tomorrow
# Exact same value line 241 used to hardcode (TODAY's date + " 03:00") —
# kept as-is, not changed to TOMORROW, see the comment at its use site.
_TODAY_3AM_STR = f"{_IST_TODAY.strftime('%Y-%m-%d')} 03:00"
CITIES = {"Bangalore": 122, "Tirupathi": 71756, "Mysuru": 129, "Coimbatore": 141, "Pondicherry": 233,
          "Chittoor": 653, "Pulivendula": 1322, "Kadiri": 415, "Proddutur": 634, "Madanapalle": 399,
          "Thiruvannamali": 293}
SHAM_TO_JAD = timedelta(minutes=75)
LAST_HYD_BP_TO_JAD = timedelta(minutes=110)  # ponytail: rough highway estimate, calibrate against a real RTC bus
KURNOOL_FROM_JAD = timedelta(minutes=105)
ALIASES ={"tgsrtc": ["tgsrtc", "tsrtc"]}
MATCH_TOLERANCE = timedelta(minutes=75)  # max gap between expected and Redbus time for a check-in match
ROUTE_ALIASES ={"bangalore": "bengaluru", "thatipatri": "tadipatri"}
CACHE = "live_layouts.json"  # last live fetch, so the report can be redone with --cached without hitting Redbus

# Bare headers on purpose: browser-like headers + stale cookie get the connection dropped by Redbus.
HEADERS = {"content-type": "application/json"}
FILTERS = {k: [] for k in ["onlyShow", "dt", "SeaterType", "AcType", "travelsList", "amtList", "bpList", "dpList",
                           "CampaignFilter", "at", "persuasionList", "bpIdentifier", "dpIdentifier", "bcf",
                           "opBusTypeFilterList", "priceRange", "RouteIds", "bpKeys", "dpKeys", "streaksFilter"]}
FILTERS.update(appliedFilterCount=0, preRouteFilters={})


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_list():
    rows = []
    for b in json.load(open("todaysbuses expectancy.txt", encoding="utf-8")):
        first = norm(b["Operator"].split()[0])  # 'KSM TRAVELS' must match 'KSM ROADWAYS', 'FLIX BUS' -> 'FlixBus'
        route = norm(b.get("Route"))
        rows.append({"bus": b["Bus Number"], "svc": str(b.get("Service Number") or ""), "op": b["Operator"],
                     "route": b.get("Route") or "", "route_key": ROUTE_ALIASES.get(route, route),
                     "keys": ALIASES.get(first, [first]), "checkin": tonight(b.get("Last Check In")),
                     "checkin_raw": b.get("Last Check In") or ""})
    return rows


def tonight(s):
    """'29 Sep 2026, 10:20 PM' -> same clock time inside tonight's window (after noon = 01-Oct, else 02-Oct)."""
    if not s:
        return None
    t = datetime.strptime(s, "%d %b %Y, %I:%M %p")
    day = WINDOW[0].date() if t.hour >= 12 else WINDOW[1].date()
    return datetime.combine(day, t.time())


def bp_time(tm, doj):
    """'23:15' or '00:20 (02-Oct)' -> datetime."""
    m = re.match(r"(\d{1,2}):(\d{2})(?:\s*\((\d{2}-\w{3})\))?", tm or "")
    if not m:
        return None
    day = datetime.strptime(f"{m.group(3)}-2026" if m.group(3) else doj, "%d-%b-%Y")
    return day.replace(hour=int(m.group(1)), minute=int(m.group(2)))


def search_page(doj, city_id, group_id, offset):
    url = (f"https://www.redbus.in/rpw/api/searchResults?fromCity=124&toCity={city_id}&DOJ={doj}&limit=200"
           f"&offset={offset}&meta=true&groupId={group_id}&sectionId=0&sort=0&sortOrder=0&from=initialLoad&getUuid=true&bT=1")
    time.sleep(1)  # be gentle: bursts get the IP 403'd for a while
    r = requests.post(url, json=FILTERS, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data") or {}


def search(doj, city_id):
    """Every inventory for a route/date: all pages, plus every collapsed operator group."""
    out, groups = [], {0}
    first = True
    while groups:
        gid = groups.pop()
        offset = 0
        while True:
            data = search_page(doj, city_id, gid, offset)
            page = data.get("inventories") or []
            out += page
            if first:
                first = False
                for sec in (data.get("metaData") or {}).get("sections") or []:
                    groups |= {g["operatorId"] for g in sec.get("groups") or []}
            if len(page) < 200:
                break
            offset += 200
    return out


def get_json(url, tries=4):
    """Redbus answers bursts with an empty/HTML body; back off and retry."""
    for n in range(tries):
        try:
            return requests.get(url, headers=HEADERS, timeout=30).json()
        except ValueError:
            if n == tries - 1:
                raise
            time.sleep(2 * (n + 1))


def layout(doj, inv):
    url = f"https://www.redbus.in/rpw/api/seatLayout?doj={doj}&routeId={inv['routeId']}&oid={inv['operatorId']}"
    d = get_json(url)
    p = inv.get("locationSearchParams") or {}
    if not d.get("services") and "BPId" in (d.get("Message") or "") and p.get("bpId"):  # RTC buses need these
        d = get_json(f"{url}&bpid={p['bpId']}&dpid={p['dpId']}")
    return d


def fetch(doj, inv):
    """Today's layout; if sold out, tomorrow's layout shifted back a day and marked 100%."""
    d = layout(doj, inv)
    if d.get("services"):
        return doj, d, False
    # Full buses come back as either 'sold out' or code 300.4 "can't load the seats right now".
    if "sold out" not in (d.get("Message") or "").lower() and d.get("Code") != "300.4":
        return doj, None, False
    # Same day's layout saved earlier by fetchStops.js has the right fares; tomorrow's prices can be far off.
    saved = glob.glob(f"Hyderabad-*/{doj}/{inv['routeId']}_*/*_serviceDetails.json")
    if saved:
        return doj, json.load(open(saved[0], encoding="utf-8")), "saved"
    nxt = (datetime.strptime(doj, "%d-%b-%Y") + timedelta(days=1)).strftime("%d-%b-%Y")
    t = layout(nxt, inv)
    return doj, (t if t.get("services") else None), True


def analyse(doj, d, sold_out):
    # sold_out: False | "saved" (same-day layout saved earlier) | True (tomorrow's layout: parse against
    # tomorrow, then shift back a day).
    shift = timedelta(days=1 if sold_out is True else 0)
    base = (datetime.strptime(doj, "%d-%b-%Y") + shift).strftime("%d-%b-%Y")
    bps = d.get("BPInformationList") or []
    find = lambda *keys: next((bp for bp in bps if any(k in (bp.get("Name") or "").lower() for k in keys)), None)
    t = lambda bp: bp_time(bp and bp["BpTm"], base) and bp_time(bp["BpTm"], base) - shift
    jad_t, sham_t = t(find("jadcherla")), t(find("shamshabad", "shamshad"))
    est = jad_t is None
    if est and sham_t:
        jad_t = sham_t + SHAM_TO_JAD
    elif est and t(find("kurnool")):
        jad_t = t(find("kurnool")) - KURNOOL_FROM_JAD  # beats guessing from Hyd BPs when an operator's BP list is out of order
    elif est:
        times = sorted(x for x in (t(bp) for bp in bps) if x)
        # Only Hyderabad pickups (first 2.5h of BPs); later BPs (Kurnool etc.) are already past Jadcherla.
        hyd = [x for x in times if x <= times[0] + timedelta(hours=2.5)] if times else []
        jad_t = hyd[-1] + LAST_HYD_BP_TO_JAD if hyd else None
    if not jad_t or not (WINDOW[0] <= jad_t <= WINDOW[1]):
        return None

    svc = d["services"][0]
    seats = svc.get("seatlist") or []
    fare = lambda s: s.get("OP") or (s.get("fares") or {}).get("amount") or 0
    sold = seats if sold_out else [s for s in seats if not s.get("IsAvailable")]
    sold_fares = [fare(s) for s in sold if fare(s) > 0]
    all_fares = [fare(s) for s in seats if fare(s) > 0]
    dep = svc.get("depTimeString") or ""
    if sold_out and dep:
        dep = (datetime.strptime(dep, "%Y-%m-%d %H:%M:%S") - shift).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "Travels": svc.get("Travels") or d.get("Travels"), "ServiceId": str(svc.get("serviceId")),
        "Route": f"{d.get('FromCity')}-{d.get('ToCity')}", "BusType": svc.get("busType"), "DepHyd": dep,
        "Shamshabad": sham_t.strftime("%d-%b %H:%M") if sham_t else "N/A",
        "Jadcherla": jad_t.strftime("%d-%b %H:%M") + (" (est)" if est else ""),
        "TotalSeats": len(seats), "Sold": len(sold),
        "Occupancy%": round(100 * len(sold) / len(seats), 1) if seats else "",
        "ASP": round(sum(sold_fares) / len(sold_fares)) if sold_fares else "",
        "MinFare": round(min(all_fares)) if all_fares else "", "MaxFare": round(max(all_fares)) if all_fares else "",
        "Note": {True: "SOLD OUT (fares from next day)", "saved": "SOLD OUT (fares from 30-Sep snapshot)"}.get(sold_out, ""),
        "_jad": jad_t,
    }


def main():
    wanted = load_list()
    keys = {k for w in wanted for k in w["keys"]}
    listed = lambda name: any(k in norm(name) for k in keys)

    if "--offline" in sys.argv:
        layouts = offline_layouts(listed)
    elif "--cached" in sys.argv:
        layouts = json.load(open(CACHE, encoding="utf-8"))
    else:
        layouts = online_layouts(listed)
        if layouts:
            json.dump(layouts, open(CACHE, "w", encoding="utf-8"))

    results = []
    for doj, d, sold_out in layouts:
        r = analyse(doj, d, sold_out)
        # Same physical bus is sold under several routes (e.g. Pondicherry + Chittoor); keep one.
        if r and not any((x["Travels"], x["ServiceId"], x["DepHyd"]) == (r["Travels"], r["ServiceId"], r["DepHyd"]) for x in results):
            results.append(r)
    report(wanted, results)


def offline_layouts(listed):
    """Seat layouts already saved by fetchStops.js (Hyderabad-*/<doj>/*/*.json) -- snapshot from when it ran."""
    out = []
    for doj in (TODAY, TOMORROW):
        for f in glob.glob(f"Hyderabad-*/{doj}/*/*_serviceDetails.json"):
            d = json.load(open(f, encoding="utf-8"))
            if d.get("services") and listed(d["services"][0].get("Travels") or d.get("Travels")):
                out.append((doj, d, False))
    print(f"Offline: {len(out)} saved layouts from listed operators")
    return out


def online_layouts(listed):
    # 1. Catalogue: listed-operator buses from today's + tomorrow's search, one entry per (doj to fetch, routeId).
    jobs = {}
    for doj in (TODAY, TOMORROW):
        for city, cid in CITIES.items():
            try:
                found = search(doj, cid)
            except Exception as e:
                print(f"❌ search {city} {doj}: {e}")
                continue
            hits = [i for i in found if i.get("routeId") and listed(i.get("travelsName"))]
            print(f"{doj} {city}: {len(found)} buses, {len(hits)} from listed operators")
            for i in hits:
                jobs.setdefault((TODAY, i["routeId"]), i)
                # A bus leaving Hyd 02-Oct before 03:00 can still hit Jadcherla inside the window.
                if doj == TOMORROW and i.get("departureTime", "") < _TODAY_3AM_STR:
                    jobs.setdefault((TOMORROW, i["routeId"]), i)
    print(f"\nFetching {len(jobs)} seat layouts...")

    # 2. Seat layouts in parallel.
    out = []
    with ThreadPoolExecutor(4) as pool:
        for fut in [pool.submit(fetch, doj, i) for (doj, _), i in jobs.items()]:
            try:
                doj, d, sold_out = fut.result()
            except Exception as e:
                print(f"❌ layout: {e}")
                continue
            if d:
                out.append((doj, d, sold_out))
    return out


def report(wanted, results):
    # 3. Tie each list row to its bus: exact service number first; otherwise it could be any
    #    window bus of that operator on that route not already claimed by an exact match (marked '?').
    for r in results:
        r["ListBusNumbers"] = []
    op_of = lambda w: [r for r in results if any(k in norm(r["Travels"]) for k in w["keys"])
                       and w["route_key"] in norm(r["Route"].split("-", 1)[-1])]
    exact_of = {w["bus"]: [r for r in op_of(w) if w["svc"] and r["ServiceId"] == w["svc"]] for w in wanted}
    claimed = {id(r) for rs in exact_of.values() for r in rs}

    # Restaurant check-in vs Redbus Jadcherla time, calibrated on the exact service-number matches.
    gaps = sorted((w["checkin"] - rs[0]["_jad"]) for w in wanted for rs in [exact_of[w["bus"]]] if rs and w["checkin"])
    offset = gaps[len(gaps) // 2] if gaps else timedelta(0)
    print(f"Restaurant check-in ≈ Redbus Jadcherla time {offset.total_seconds() / 60:+.0f} min (median of {len(gaps)} exact matches)")

    # Everyone else: closest Redbus bus of same operator+route to (check-in - offset), one bus per list row.
    pairs = sorted(((abs(w["checkin"] - offset - r["_jad"]), i, w["bus"], r)
                    for i, w in enumerate(wanted) if not exact_of[w["bus"]] and w["checkin"]
                    for r in op_of(w) if id(r) not in claimed), key=lambda p: p[:2])
    timed = {}
    for diff, _, bus, r in pairs:
        if diff <= MATCH_TOLERANCE and bus not in timed and id(r) not in claimed:
            timed[bus] = (r, diff)
            claimed.add(id(r))

    by_bus = []
    for w in wanted:
        exact = exact_of[w["bus"]]
        if exact:
            rs, how = exact, "exact service no."
        elif w["bus"] in timed:
            r, diff = timed[w["bus"]]
            rs, how = [r], f"by check-in time (±{diff.total_seconds() / 60:.0f} min)"
        else:
            rs = [r for r in op_of(w) if id(r) not in claimed]
            how = f"avg of {len(rs)} buses of operator on route (none near check-in time)" if rs else "NOT FOUND on Redbus in window"
        for r in rs:
            r["ListBusNumbers"].append(w["bus"] + ("" if len(rs) == 1 else "?"))
        s, t = sum(r["Sold"] for r in rs), sum(r["TotalSeats"] for r in rs)
        if not rs or not (0 < t < 50):  # only a clean "sold/total" with total <50 is trusted — anything else (no match, or several buses averaged into an inflated total) skips the row entirely
            continue
        a = [r["ASP"] for r in rs if r["ASP"] != ""]
        by_bus.append({
            "Bus Number": w["bus"], "Operator": w["op"], "Route": w["route"],
            "Dep Hyd": rs[0]["DepHyd"][11:16] if len(rs) == 1 else "",
            "Jadcherla": rs[0]["Jadcherla"] if len(rs) == 1 else "",
            "Seats sold": f"{s}/{t}" if rs else "",
            "ASP": round(sum(a) / len(a)) if a else "",
        })
    by_bus.sort(key=lambda b: b["Dep Hyd"])  # ascending by Hyderabad departure time ("HH:MM", zero-padded, sorts correctly as text)

    if not results:
        print("\n❌ Nothing fetched (Redbus 403 = rate-limited, retry in a few minutes). Previous CSV left untouched.")
        return
    results.sort(key=lambda r: r["_jad"])
    cols = ["ListBusNumbers", "Travels", "ServiceId", "Route", "BusType", "DepHyd", "Shamshabad", "Jadcherla",
            "TotalSeats", "Sold", "Occupancy%", "ASP", "MinFare", "MaxFare", "Note"]
    with open("todaysOccupancy.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow({**r, "ListBusNumbers": " ".join(r["ListBusNumbers"])})

    out_name = "todaysOccupancy_byBus.csv"
    try:
        f = open(out_name, "w", newline="", encoding="utf-8")
    except PermissionError:  # open in Excel
        out_name = f"todaysOccupancy_byBus_{datetime.now():%H%M}.csv"
        f = open(out_name, "w", newline="", encoding="utf-8")
    with f:
        w = csv.DictWriter(f, list(by_bus[0]))
        w.writeheader()
        w.writerows(by_bus)
    print(f"\nYOUR BUSES -> {out_name}")
    for b in by_bus:
        print(f"   {b['Bus Number']:11} {b['Operator']:18} {b['Route']:10} "
              f"{b['Jadcherla']:20} Seats {b['Seats sold']:<8} ₹{b['ASP']}")

    print(f"\n✅ {len(results)} buses in window -> todaysOccupancy.csv  ('?' = operator match only, no service number match)")
    if results:
        sold = sum(r["Sold"] for r in results); total = sum(r["TotalSeats"] for r in results)
        asps = [r["ASP"] for r in results if r["ASP"] != ""]
        print(f"Overall occupancy {100 * sold / total:.1f}%  |  mean ASP ₹{sum(asps) / len(asps):.0f}")
        print("\nBy operator:")
        by_op = {}
        for r in results:
            by_op.setdefault(r["Travels"], []).append(r)
        for op, rs in sorted(by_op.items()):
            s, t = sum(r["Sold"] for r in rs), sum(r["TotalSeats"] for r in rs)
            a = [r["ASP"] for r in rs if r["ASP"] != ""]
            print(f"   {op:35} {len(rs):3} buses  {100 * s / t:5.1f}%  ASP ₹{sum(a) / len(a):.0f}" if a else f"   {op:35} {len(rs):3} buses")


if __name__ == "__main__":
    main()
