"""
Daily Redbus snapshot for FlixBus, Zingbus and IntrCity: every bus of theirs from Hyderabad that passes
our restaurant (Shamshabad + 50 min) between 19:00 today and 03:00 tomorrow (IST) and has a rest stop,
with occupancy and ASP.

Usage:  python3 opsOccupancy.py                  (tonight, IST)
        python3 opsOccupancy.py 22-Oct-2026      (a specific night)
        python3 opsOccupancy.py --ops flix,zing  (other operators; matches part of the Redbus operator name)
Needs:  pip install requests pillow
Output: reports/<YYYY-MM-DD>_buses.csv    one row per bus (Flix, IntrCity, Zing groups)
        reports/<YYYY-MM-DD>_slots.png    bus count per hourly restaurant-time slot per operator
        (reports/ is created next to this script, whatever folder you run it from)

Cron (12:00 IST every day):
    CRON_TZ=Asia/Kolkata
    0 12 * * * /opt/redbus/venv/bin/python /opt/redbus/opsOccupancy.py >> /opt/redbus/cron.log 2>&1

Occupancy = sold seats / total seats (operator-blocked seats count as sold).
ASP       = average fare of the sold seats.
Sold out  = Redbus hides it -> 100%, fares from next day's layout (approximate).
Jadcherla (est) = Shamshabad + 75 min, or last Hyderabad pickup + 110 min, when Jadcherla isn't a listed stop.
"""
import csv, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

IST = ZoneInfo("Asia/Kolkata")
_day = next((datetime.strptime(a, "%d-%b-%Y") for a in sys.argv[1:] if re.fullmatch(r"\d{2}-\w{3}-\d{4}", a)),
            datetime.now(IST).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0))
TODAY, TOMORROW = _day.strftime("%d-%b-%Y"), (_day + timedelta(days=1)).strftime("%d-%b-%Y")
WINDOW = (_day.replace(hour=19), _day + timedelta(days=1, hours=3))
OPS = (sys.argv[sys.argv.index("--ops") + 1] if "--ops" in sys.argv else "flix,intrcity,zing").split(",")  # also the output order

CITIES = {"Bangalore": 122, "Tirupathi": 71756, "Mysuru": 129, "Coimbatore": 141, "Pondicherry": 233,
          "Chittoor": 653, "Pulivendula": 1322, "Kadiri": 415, "Proddutur": 634, "Madanapalle": 399,
          "Thiruvannamali": 293}
SHAM_TO_JAD = timedelta(minutes=75)
LAST_HYD_BP_TO_JAD = timedelta(minutes=110)  # ponytail: rough highway estimate
KURNOOL_FROM_JAD = timedelta(minutes=105)
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")  # next to the script, from any cwd
SHAM_TO_REST = timedelta(minutes=50)  # Shamshabad -> our restaurant
# Redbus 'isRestStop' flag: buses without it are dropped, except operators that never publish it
# (FlixBus: flag always empty on Redbus, yet its buses do check in at the restaurant).
PITSTOP_NOT_PUBLISHED = ["flix"]
SLOTS = ["7-8pm", "8-9pm", "9-10pm", "10-11pm", "11-12am", "12am+"]  # by restaurant time; 12am+ = 00:00-03:00
DISPLAY_ORDER = ["flix", "zing", "intrcity"]  # terminal + slot image order
LABELS = {"flix": "Flix", "zing": "Zing", "intrcity": "Intrcity"}

# Bare headers on purpose: browser-like headers + stale cookie get the connection dropped by Redbus.
HEADERS = {"content-type": "application/json"}
FILTERS = {k: [] for k in ["onlyShow", "dt", "SeaterType", "AcType", "travelsList", "amtList", "bpList", "dpList",
                           "CampaignFilter", "at", "persuasionList", "bpIdentifier", "dpIdentifier", "bcf",
                           "opBusTypeFilterList", "priceRange", "RouteIds", "bpKeys", "dpKeys", "streaksFilter"]}
FILTERS.update(appliedFilterCount=0, preRouteFilters={})


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def wanted(name):
    return any(norm(o) in norm(name) for o in OPS)


def op_rank(name):
    """Position in OPS, so output is grouped Flix, IntrCity, Zing ('IntrCity SmartBus.AQI' stays with IntrCity)."""
    return next(i for i, o in enumerate(OPS) if norm(o) in norm(name))


def write_grouped(path, rows, key):
    """CSV with one blank row between operator groups. Returns the path actually written."""
    try:
        f = open(path, "w", newline="", encoding="utf-8")
    except PermissionError:  # open in Excel
        path = path.replace(".csv", f"_{datetime.now():%H%M}.csv")
        f = open(path, "w", newline="", encoding="utf-8")
    with f:
        w = csv.DictWriter(f, [c for c in rows[0] if not c.startswith("_")], extrasaction="ignore")
        w.writeheader()
        prev = None
        for r in rows:
            if prev is not None and key(r) != prev:
                f.write("\r\n")
            w.writerow(r)
            prev = key(r)
    return path


def bp_time(tm, doj):
    """'23:15' or '00:20 (02-Oct)' -> datetime."""
    m = re.match(r"(\d{1,2}):(\d{2})(?:\s*\((\d{2}-\w{3})\))?", tm or "")
    if not m:
        return None
    day = datetime.strptime(f"{m.group(3)}-{doj[-4:]}" if m.group(3) else doj, "%d-%b-%Y")
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
    out, groups, first = [], {0}, True
    while groups:
        gid, offset = groups.pop(), 0
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
    if not d.get("services") and "BPId" in (d.get("Message") or "") and p.get("bpId"):
        d = get_json(f"{url}&bpid={p['bpId']}&dpid={p['dpId']}")
    return d


def fetch(doj, inv):
    """(doj, layout, sold_out). Sold out -> next day's layout, analysed shifted back a day."""
    d = layout(doj, inv)
    if d.get("services"):
        return doj, d, False
    # Full buses come back as either 'sold out' or code 300.4 "can't load the seats right now".
    if "sold out" not in (d.get("Message") or "").lower() and d.get("Code") != "300.4":
        return doj, None, False
    nxt = (datetime.strptime(doj, "%d-%b-%Y") + timedelta(days=1)).strftime("%d-%b-%Y")
    t = layout(nxt, inv)
    return doj, (t if t.get("services") else None), True


def analyse(doj, d, sold_out):
    shift = timedelta(days=1 if sold_out else 0)
    base = (datetime.strptime(doj, "%d-%b-%Y") + shift).strftime("%d-%b-%Y")
    bps = d.get("BPInformationList") or []
    find = lambda *keys: next((bp for bp in bps if any(k in (bp.get("Name") or "").lower() for k in keys)), None)
    t = lambda bp: bp_time(bp and bp["BpTm"], base) and bp_time(bp["BpTm"], base) - shift
    jad_t, sham_t = t(find("jadcherla")), t(find("shamshabad", "shamshad"))
    est = jad_t is None
    if est and sham_t:
        jad_t = sham_t + SHAM_TO_JAD
    elif est and t(find("kurnool")):
        jad_t = t(find("kurnool")) - KURNOOL_FROM_JAD
    elif est:
        times = sorted(x for x in (t(bp) for bp in bps) if x)
        hyd = [x for x in times if x <= times[0] + timedelta(hours=2.5)] if times else []  # Hyderabad pickups only
        jad_t = hyd[-1] + LAST_HYD_BP_TO_JAD if hyd else None
    # Our restaurant is before Jadcherla: Shamshabad + 50 min (same point as Jadcherla - 25 when only that is known).
    rest_t = sham_t + SHAM_TO_REST if sham_t else jad_t and jad_t - (SHAM_TO_JAD - SHAM_TO_REST)
    if not rest_t or not (WINDOW[0] <= rest_t <= WINDOW[1]):
        return None

    svc = d["services"][0]
    op = svc.get("Travels") or d.get("Travels")
    has_stop = bool((svc.get("param42") or {}).get("isRestStop"))
    if not has_stop and not any(norm(o) in norm(op) for o in PITSTOP_NOT_PUBLISHED):
        return None  # Redbus says no rest stop -> won't stop at the restaurant
    seats = svc.get("seatlist") or []
    fare = lambda s: s.get("OP") or (s.get("fares") or {}).get("amount") or 0
    sold = seats if sold_out else [s for s in seats if not s.get("IsAvailable")]
    sold_fares = [fare(s) for s in sold if fare(s) > 0]
    dep = svc.get("depTimeString") or ""
    if sold_out and dep:
        dep = f"{datetime.strptime(dep, '%Y-%m-%d %H:%M:%S') - shift:%Y-%m-%d %H:%M:%S}"
    return {
        "Operator": op, "Route": d.get("ToCity"), "BusType": svc.get("busType"),
        "Shamshabad": f"{sham_t:%d-%b %H:%M}" if sham_t else "N/A",
        "Restaurant": f"{rest_t:%d-%b %H:%M}" + ("" if sham_t else " (est)"),
        "PitStop": "Yes" if has_stop else "not declared on Redbus",
        "TotalSeats": len(seats), "Sold": len(sold),
        "Occupancy%": round(100 * len(sold) / len(seats), 1) if seats else "",
        "ASP": round(sum(sold_fares) / len(sold_fares)) if sold_fares else "",
        "Note": "SOLD OUT (fares from next day)" if sold_out else "",
        # '_' fields are kept out of the CSV; ServiceId + DepHyd are only used to drop duplicates.
        "_rest": rest_t, "_ServiceId": str(svc.get("serviceId")), "_DepHyd": dep,
    }


def main():
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M} IST | window {WINDOW[0]:%d-%b %H:%M} -> {WINDOW[1]:%d-%b %H:%M} | ops {OPS}")

    # Today's search hides nearly/fully sold-out buses, so tomorrow's search is used as the catalogue too.
    jobs = {}
    for doj in (TODAY, TOMORROW):
        for city, cid in CITIES.items():
            try:
                hits = [i for i in search(doj, cid) if i.get("routeId") and wanted(i.get("travelsName"))]
            except Exception as e:
                print(f"search {city} {doj} failed: {e}")
                continue
            for i in hits:
                jobs.setdefault((TODAY, i["routeId"]), i)
                if doj == TOMORROW and i.get("departureTime", "") < f"{WINDOW[1]:%Y-%m-%d %H:%M}":
                    jobs.setdefault((TOMORROW, i["routeId"]), i)

    results = []
    with ThreadPoolExecutor(4) as pool:
        for fut in [pool.submit(fetch, doj, i) for (doj, _), i in jobs.items()]:
            try:
                doj, d, sold_out = fut.result()
            except Exception as e:
                print(f"layout failed: {e}")
                continue
            r = analyse(doj, d, sold_out) if d else None
            # Same physical bus is sold under several routes; keep one.
            if r and not any((x["Operator"], x["_ServiceId"], x["_DepHyd"]) == (r["Operator"], r["_ServiceId"], r["_DepHyd"]) for x in results):
                results.append(r)

    if not results:
        print("Nothing fetched (Redbus 403 = rate-limited). No report written.")
        sys.exit(1)  # non-zero so cron/monitoring notices

    # Flix, then IntrCity, then Zing; each by restaurant time.
    results.sort(key=lambda r: (op_rank(r["Operator"]), r["_rest"]))
    os.makedirs(OUT_DIR, exist_ok=True)
    stem = os.path.join(OUT_DIR, f"{_day:%Y-%m-%d}")
    csv_path = write_grouped(f"{stem}_buses.csv", results, key=lambda r: op_rank(r["Operator"]))

    # Bus counts per operator per restaurant-time slot.
    ops = [o for o in DISPLAY_ORDER if o in OPS] + [o for o in OPS if o not in DISPLAY_ORDER]
    slot_of = lambda t: SLOTS[t.hour - 19] if t.hour >= 19 else SLOTS[-1]
    counts = {(s, o): 0 for s in SLOTS for o in ops}
    for r in results:
        counts[(slot_of(r["_rest"]), OPS[op_rank(r["Operator"])])] += 1
    totals = {o: sum(counts[(s, o)] for s in SLOTS) for o in ops}

    label = lambda o: LABELS.get(o, o.title())
    header = ["Slot"] + [label(o) for o in ops]
    rows = [[s] + [counts[(s, o)] for o in ops] for s in SLOTS] + [["Total"] + [totals[o] for o in ops]]
    png_path = slot_image(f"{stem}_slots.png",
                          f"Active services - {_day:%d %b %Y}\nby restaurant time (Shamshabad + 50 min)", header, rows)

    print()
    for o in ops:
        print(f"{label(o)} - {totals[o]}")
    print(f"\nActive Services running today ({_day:%d %b})")
    print(f"\nWrote {csv_path} and {png_path}")


def slot_image(path, title, header, rows):
    """Plain table PNG: header row, slot rows, bold-ish Total row."""
    from PIL import Image, ImageDraw, ImageFont  # pip install pillow
    font = ImageFont.load_default(size=22)
    lines = title.split("\n")
    cw, rh, pad = [150] + [130] * (len(header) - 1), 44, 20
    w = max(sum(cw), *(font.getlength(l) for l in lines)) + 2 * pad
    h = rh * (len(rows) + 1 + len(lines)) + 2 * pad
    img = Image.new("RGB", (int(w), h), "white")
    d = ImageDraw.Draw(img)
    for k, l in enumerate(lines):
        d.text((pad, pad + k * 32), l, fill="black" if k == 0 else "#555", font=font)
    for i, row in enumerate([header] + rows):
        y = pad + rh * (i + len(lines))
        fill = "#1f3b57" if i == 0 else "#e8eef4" if i == len(rows) else "#f7f9fb" if i % 2 else "white"
        d.rectangle([pad, y, pad + sum(cw), y + rh], fill=fill, outline="#c5ced8")
        x = pad
        for j, cell in enumerate(row):
            text = str(cell)
            tw = d.textlength(text, font=font)
            tx = x + 12 if j == 0 else x + (cw[j] - tw) / 2
            d.text((tx, y + (rh - 22) / 2), text, fill="white" if i == 0 else "black", font=font)
            x += cw[j]
            if j < len(row) - 1:
                d.line([x, y, x, y + rh], fill="#c5ced8")
    try:
        img.save(path)
    except OSError:  # open in an image viewer
        path = path.replace(".png", f"_{datetime.now():%H%M}.png")
        img.save(path)
    return path


if __name__ == "__main__":
    main()
