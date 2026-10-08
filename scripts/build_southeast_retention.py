"""Regenerate apps/us_cow_herd/data/southeast_retention.json.

The southeastern long-history retention panel, 2008-2026.

Legacy zips 2008-2018 + MARS 2019-2026 at the SAME five barns. Written as a
one-off generator: the zips are 960MB of CSV and the page cannot parse them per
load, so this emits a small JSON the page reads instead.

Run from the repo root. Needs MARS_API_KEY and the two legacy zips in
Downloads. The legacy archive is static and will never gain a row, so
this is a rebuild rather than a refresh of the pre-2019 half; only the
MARS half moves. It reports whether the two sources share any barn-date
-- see apps/us_cow_herd/southeast.py for why that must stay zero.
"""
import zipfile, csv, io, json, collections, statistics, os, sys, pathlib
from datetime import date, datetime
import requests
from dotenv import load_dotenv

load_dotenv(r"C:\Users\RossBaldwin\projects\cme-feeder-cattle-index\.env")
AUTH = (os.environ["MARS_API_KEY"], "")
B = "https://marsapi.ams.usda.gov/services/v1.2"
DL = r"C:\Users\RossBaldwin\Downloads"

# Five barns continuous on BOTH sides. Legacy LOCATION_NAME -> MARS slug.
PANEL = {
    "Calhoun":     (1946, "Calhoun, GA"),
    "Carrollton":  (1949, "Carrollton, GA"),
    "Athens":      (1940, "Athens, GA"),
    "Saluda":      (1961, "Saluda, SC"),
    "Orangeburg":  (1964, "Orangeburg, SC"),
}
LEGACY_STATE = {"Calhoun": "GA", "Carrollton": "GA", "Athens": "GA",
                "Saluda": "SC", "Orangeburg": "SC"}

# The legacy archive has NO price-unit column and quotes bred cows per cwt at
# some barns and per head at others, in the same year, with SELLING_BASIS
# reading "Live" either way. The split is cleanly bimodal -- 20,491 rows under
# $250, 78 between $250 and $300, 104,583 above -- so the threshold is not a
# judgement call. Per-cwt rows are DROPPED rather than converted, matching the
# MARS-side rule which keeps only price_unit in (Per Unit, Per Head).
PER_HEAD_FLOOR = 250

FILES = [("usda_legacy_ls_auction_wtd_1_2000_2010.zip",
          ["usda_legacy_auction_wtd_3_2006_2008.csv", "usda_legacy_auction_wtd_4_2008_2010.csv"]),
         ("usda_legacy_ls_auction_wtd_2_2010_2019.zip",
          ["usda_legacy_auction_wtd_5_2010_2012.csv", "usda_legacy_auction_wtd_6_2012_2015.csv",
           "usda_legacy_auction_wtd_7_2015_2017.csv", "usda_legacy_auction_wtd_8_2017_2019.csv"])]

pairs = collections.defaultdict(lambda: {"bh": 0, "bd": 0.0, "sh": 0, "sd": 0.0})

for zn, members in FILES:
    z = zipfile.ZipFile(os.path.join(DL, zn))
    for mn in members:
        with z.open(mn) as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace")):
                cls = row["CLASS_NAME"]
                if cls not in ("Bred Cows", "Slaughter Cows"):
                    continue
                barn = row["LOCATION_NAME"]
                if barn not in PANEL or row["STATE_ABBREV"] != LEGACY_STATE[barn]:
                    continue
                try:
                    px = float(row["AVERAGE_PRICE"]); h = int(float(row["HEAD_COUNT"]))
                    wt = float(row["AVERAGE_WEIGHT"])
                except Exception:
                    continue
                if h <= 0 or px <= 0 or wt <= 0:
                    continue
                mm, dd, yy = row["LGDATE"].split("/")
                key = (barn, "%s-%02d-%02d" % (yy, int(mm), int(dd)))
                d = pairs[key]
                if cls == "Bred Cows":
                    if px < PER_HEAD_FLOOR:      # quoted per cwt -- dropped
                        continue
                    d["bh"] += h; d["bd"] += h * px
                else:
                    if px >= PER_HEAD_FLOOR:
                        continue
                    d["sh"] += h; d["sd"] += h * px * wt / 100.0
        print("  legacy", mn, flush=True)

legacy = [(b, dt, (v["bd"] / v["bh"]) / (v["sd"] / v["sh"]))
          for (b, dt), v in pairs.items() if v["bh"] and v["sh"]]
print("legacy paired barn-dates:", len(legacy))

# ---- MARS side, same five barns -------------------------------------------
mars_pairs = collections.defaultdict(lambda: {"bh": 0, "bd": 0.0, "sh": 0, "sd": 0.0})
for barn, (slug, label) in PANEL.items():
    j = requests.get(f"{B}/reports/{slug}", auth=AUTH, timeout=180).json()
    rows = j.get("results", j) if isinstance(j, dict) else j
    n = 0
    for x in rows:
        p, h, w = x.get("avg_price"), x.get("head_count"), x.get("avg_weight")
        if not (p and h):
            continue
        dt = datetime.strptime(x["report_date"], "%m/%d/%Y").date().isoformat()
        d = mars_pairs[(barn, dt)]
        if (x.get("commodity") == "Replacement Cattle"
                and x.get("class") in ("Bred Cows", "Bred Heifers")
                and x.get("price_unit") in ("Per Unit", "Per Head")):
            d["bh"] += h; d["bd"] += h * p; n += 1
        elif (x.get("commodity") == "Slaughter Cattle" and x.get("class") == "Cows"
              and x.get("price_unit") == "Per Cwt" and w):
            d["sh"] += h; d["sd"] += h * p * w / 100.0; n += 1
    print(f"  mars {slug} {label:18} usable rows {n}", flush=True)

mars = [(b, dt, (v["bd"] / v["bh"]) / (v["sd"] / v["sh"]))
        for (b, dt), v in mars_pairs.items() if v["bh"] and v["sh"]]
print("mars paired barn-dates:", len(mars))

# ---- the join must not overlap --------------------------------------------
ldates = {(b, dt) for b, dt, _ in legacy}
mdates = {(b, dt) for b, dt, _ in mars}
overlap = ldates & mdates
print("OVERLAPPING barn-dates between the two sources:", len(overlap))
if overlap:
    # The two halves are CONCATENATED, not spliced, and that is only legitimate
    # because they do not overlap -- legacy's last bred sale at each barn falls
    # just before MARS's first. If USDA ever back-fills the archive this stops
    # being true, and silently double-counts the shared weeks into the median.
    # Refuse to write rather than ship a quietly wrong year.
    print("  ", sorted(overlap)[:10])
    sys.exit("ABORT: the two sources overlap; concatenation would double-count")

allobs = [(b, dt, r, "legacy") for b, dt, r in legacy] + \
         [(b, dt, r, "mars") for b, dt, r in mars]

by = collections.defaultdict(list)
for b, dt, r, src in allobs:
    by[dt[:4]].append((r, b, dt[5:7], src))

out = []
for y in sorted(by):
    v = by[y]
    months = {m for _, _, m, _ in v}
    barns = {b for _, b, _, _ in v}
    if len(months) < 6:
        print(f"  dropped {y}: only {len(months)} months")
        continue
    NAME = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    mo = sorted(months)
    rec = {"year": int(y), "ratio": round(statistics.median(r for r, _, _, _ in v), 4),
           "n": len(v), "months": len(months), "barns": len(barns),
           "source": "legacy" if all(s == "legacy" for _, _, _, s in v)
                     else ("mars" if all(s == "mars" for _, _, _, s in v) else "both")}
    # A part year is labelled with the months it covers, never passed off as a
    # whole one -- the ratio is seasonal and a ten-month bar beside twelve-month
    # bars is a true number telling a false story.
    if len(months) < 12:
        rec["span"] = [NAME[int(mo[0]) - 1], NAME[int(mo[-1]) - 1]]
    out.append(rec)

print("\nyear  ratio   n   mo  barns  source")
for r in out:
    print(f"{r['year']}  {r['ratio']:.3f}  {r['n']:4}  {r['months']:2}   {r['barns']}    {r['source']}")

dest = str(pathlib.Path(__file__).resolve().parent.parent
            / "apps" / "us_cow_herd" / "data" / "southeast_retention.json")
json.dump({"panel": [v[1] for v in PANEL.values()], "series": out}, open(dest, "w"), indent=1)
print("\nwrote", dest)
