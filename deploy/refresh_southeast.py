#!/usr/bin/env python3
"""
Keep the southeastern retention series current. For the droplet's crontab.

WHAT GOES STALE AND WHAT DOES NOT. The US Cow Herd page's southeastern panel
spans 2008-2026 from two sources. The 2008-2018 half is USDA's legacy auction
archive: static, closed, and it will never gain a row. The 2019-onward half is
the live MARS feed, and it moves every week. Only the second half needs a job.

SO THE LEGACY HALF IS FROZEN, NOT REBUILT. apps/us_cow_herd/data/
southeast_legacy.json holds its 3,323 post-handover barn-date observations,
written once by scripts/build_southeast_retention.py. That matters practically
-- the archive is 960MB of CSV across two zips, which has no business on a
droplet -- and it matters for correctness: a job that recomputed it every week
could silently produce a different past, and nobody would be looking.

WHY SNOWFLAKE AND NOT THE JSON IN THE REPO. The page reads a committed file
today, which is fine as a seed and useless as a live series: this host has no
push credentials and should not have them. So the refreshed series goes to
JSA.CME_FEEDER_CATTLE.SOUTHEAST_RETENTION and southeast.py prefers that over
the file, falling back to the file when Snowflake is unreachable or empty. The
page therefore still renders if this job never runs -- it just stops advancing.

THE PAGE CANNOT DO THIS ITSELF, which is the reason a cron exists at all:
marsapi.ams.usda.gov rejects requests from Streamlit Community Cloud's IPs
(CLAUDE.md records this for Beef Trimmings). The droplet can reach it.

APPEND-ONLY, NEWEST WINS PER YEAR -- the shape JSA.BOXED_BEEF.CUTOUT_AM and
JSA.LETTER.DRAFTS already use, and for the same reasons: an INSERT needs no
UPDATE grant, and no run can bury the figure a previous run recorded. Nineteen
rows a time is nothing.

IDEMPOTENT, so the schedule can be blunt. Re-running inside the same week
writes a fresh set of rows that read identically; a year whose figures have
not moved is skipped entirely, so a catch-up run usually writes nothing.

Exit codes: 0 wrote or had nothing to write, 1 could not fetch or could not
write. The droplet has no MAILTO and no MTA, so the exit code is the entire
alerting contract -- see deploy/run_southeast_retention.sh.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "apps" / "us_cow_herd" / "data"
FROZEN = DATA / "southeast_legacy.json"
SERIES_JSON = DATA / "southeast_retention.json"

MARS = "https://marsapi.ams.usda.gov/services/v1.2"
BRED_CLASSES = ("Bred Cows", "Bred Heifers")
PER_HEAD_UNITS = ("Per Unit", "Per Head")
MIN_MONTHS = 6
TABLE = "JSA.CME_FEEDER_CATTLE.SOUTHEAST_RETENTION"

MONTH_NAME = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _load_db():
    """snowflake_db under a PRIVATE name.

    This module exists five times in the repo and is imported by bare name by
    several pages, so whichever loads first wins for every other. Loading it by
    path under a name of our own keeps this job out of that collision -- the
    same thing letter/draft_store.py does.
    """
    path = REPO / "apps" / "us_cow_herd" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_se_snowflake_db", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_mars(slug, auth):
    import requests
    r = requests.get(f"{MARS}/reports/{slug}", auth=auth, timeout=(5, 180))
    r.raise_for_status()
    j = r.json()
    return j.get("results", j) if isinstance(j, dict) else j


def mars_observations(panel, auth, verbose=True):
    """[(barn, iso_date, ratio)] -- bred over salvage, same barn, same date."""
    out = []
    for barn, slug in panel.items():
        rows = fetch_mars(slug, auth)
        per = defaultdict(lambda: [0, 0.0, 0, 0.0])
        for x in rows:
            p, h, w = x.get("avg_price"), x.get("head_count"), x.get("avg_weight")
            if not (p and h):
                continue
            d = datetime.strptime(x["report_date"], "%m/%d/%Y").date().isoformat()
            a = per[d]
            if (x.get("commodity") == "Replacement Cattle"
                    and x.get("class") in BRED_CLASSES
                    and x.get("price_unit") in PER_HEAD_UNITS):
                a[0] += h
                a[1] += h * p
            elif (x.get("commodity") == "Slaughter Cattle" and x.get("class") == "Cows"
                  and x.get("price_unit") == "Per Cwt" and w):
                a[2] += h
                a[3] += h * p * w / 100.0
        n = 0
        for d, (bh, bd, sh, sd) in per.items():
            if bh and sh:
                out.append((barn, d, (bd / bh) / (sd / sh)))
                n += 1
        if verbose:
            print(f"  {slug:>5} {barn:<14} {n:>4} paired sale-dates")
    return out


def build(frozen, mars_obs):
    """The annual series, legacy and MARS merged under the frozen handover."""
    handover = frozen["handover"]

    # ONE SOURCE PER BARN. Norwood and Turnersburg are carried by BOTH archives
    # for a few weeks of mid-2019 -- transcriptions of the same AMS report, so
    # summing them double-counts those barns in the median. The boundary comes
    # from the frozen file rather than from today's MARS response, so a feed
    # that briefly loses its earliest rows cannot move it.
    legacy = [(b, d, r) for b, d, r in frozen["obs"]
              if not (b in handover and d >= handover[b])]
    mars = [(b, d, r) for b, d, r in mars_obs
            if not (b in handover and d < handover[b])]

    overlap = {(b, d) for b, d, _ in legacy} & {(b, d) for b, d, _ in mars}
    if overlap:
        raise SystemExit(f"ABORT: {len(overlap)} overlapping barn-dates, e.g. "
                         f"{sorted(overlap)[:5]} -- would double-count")

    by = defaultdict(list)
    for b, d, r in legacy:
        by[d[:4]].append((r, b, d[5:7], "legacy"))
    for b, d, r in mars:
        by[d[:4]].append((r, b, d[5:7], "mars"))

    series = []
    for y in sorted(by):
        v = by[y]
        months = {m for _, _, m, _ in v}
        if len(months) < MIN_MONTHS:
            continue
        srcs = {s for _, _, _, s in v}
        rec = {"year": int(y), "ratio": round(median(r for r, _, _, _ in v), 4),
               "n": len(v), "months": len(months),
               "barns": len({b for _, b, _, _ in v}),
               "source": srcs.pop() if len(srcs) == 1 else "both"}
        if len(months) < 12:
            mo = sorted(months)
            rec["span"] = [MONTH_NAME[int(mo[0]) - 1], MONTH_NAME[int(mo[-1]) - 1]]
        series.append(rec)
    return series


DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    YEAR INTEGER NOT NULL,
    RATIO FLOAT NOT NULL,
    N INTEGER,
    MONTHS INTEGER,
    BARNS INTEGER,
    SOURCE STRING,
    SPAN STRING,
    PANEL STRING,
    RECORDED_AT TIMESTAMP_NTZ NOT NULL
)
"""


def existing(conn):
    """Newest row per year, as the page reads it."""
    cur = conn.cursor().execute(
        f"SELECT YEAR, RATIO, N, MONTHS, BARNS FROM {TABLE} "
        f"QUALIFY ROW_NUMBER() OVER (PARTITION BY YEAR ORDER BY RECORDED_AT DESC) = 1")
    return {int(r[0]): (float(r[1]), r[2], r[3], r[4]) for r in cur.fetchall()}


def write(conn, series, panel_names):
    # CREATE SCHEMA is attempted and its failure IGNORED on purpose. The target
    # schema already exists, and the identity that runs this may not hold
    # CREATE SCHEMA on the database -- Ross's CME_INGEST_ROLE does not, and
    # raising there would stop a job whose schema is sitting right in front of
    # it. If the schema really is missing, the CREATE TABLE below says so.
    try:
        conn.cursor().execute(
            f"CREATE SCHEMA IF NOT EXISTS {'.'.join(TABLE.split('.')[:2])}")
    except Exception:
        pass
    conn.cursor().execute(DDL)
    try:
        have = existing(conn)
    except Exception:
        have = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # JSON, not a comma-join. Every barn name already contains a comma
    # ("Calhoun, GA"), so joining on ", " and splitting it back gives fourteen
    # barns from seven -- and the caption prints that number.
    panel = json.dumps(panel_names)
    wrote = 0
    for r in series:
        prev = have.get(r["year"])
        # Skip a year whose figures have not moved. Append-only means a no-op
        # run would otherwise add nineteen identical rows a week for ever.
        if prev and abs(prev[0] - r["ratio"]) < 1e-9 and prev[1] == r["n"]:
            continue
        conn.cursor().execute(
            f"INSERT INTO {TABLE} (YEAR, RATIO, N, MONTHS, BARNS, SOURCE, SPAN, "
            f"PANEL, RECORDED_AT) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (r["year"], r["ratio"], r["n"], r["months"], r["barns"], r["source"],
             json.dumps(r.get("span")) if r.get("span") else None, panel, now))
        wrote += 1
    conn.commit()
    return wrote


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and print, write nothing")
    ap.add_argument("--write-json", action="store_true",
                    help="also refresh the committed JSON (local rebuilds only)")
    args = ap.parse_args()

    if not FROZEN.exists():
        print(f"missing {FROZEN} -- run scripts/build_southeast_retention.py",
              file=sys.stderr)
        return 1
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))

    key = os.environ.get("MARS_API_KEY")
    if not key:
        print("MARS_API_KEY not set -- nothing would be fetched", file=sys.stderr)
        return 1

    # frozen['panel'] maps barn -> display label; frozen['slugs'] barn -> MARS
    # slug. Both come from the same PANEL literal in the build script, so the
    # refresh can never drift onto a different set of barns than the frozen
    # legacy half was computed for.
    slugs = frozen.get("slugs") or {}
    if not slugs:
        print("frozen file carries no slug map -- regenerate it with "
              "scripts/build_southeast_retention.py", file=sys.stderr)
        return 1

    print(f"fetching {len(slugs)} southeastern barns from MARS")
    try:
        obs = mars_observations({b: int(s) for b, s in slugs.items()}, (key, ""))
    except Exception as e:
        print(f"MARS fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    series = build(frozen, obs)
    print(f"\n{'year':>6}{'ratio':>8}{'n':>6}{'mo':>4}{'barns':>7}  source")
    for r in series:
        print(f"{r['year']:>6}{r['ratio']:>8.3f}{r['n']:>6}{r['months']:>4}"
              f"{r['barns']:>7}  {r['source']}")

    names = list(frozen["panel"].values())
    if args.write_json:
        SERIES_JSON.write_text(json.dumps({"panel": names, "series": series},
                                          indent=1), encoding="utf-8")
        print(f"\nwrote {SERIES_JSON}")

    if args.dry_run:
        print("\n--dry-run: nothing written to Snowflake")
        return 0

    db = _load_db()
    if not db.use_snowflake():
        print("USE_SNOWFLAKE is not set -- refusing to write to SQLite, which "
              "the deployed page does not read", file=sys.stderr)
        return 1
    try:
        conn = db.get_conn()
    except Exception as e:
        print(f"Snowflake connect failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    try:
        n = write(conn, series, names)
        print(f"\n{n} year(s) written to {TABLE}"
              + (" (nothing had changed)" if n == 0 else ""))
    except Exception as e:
        print(f"write failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
