#!/usr/bin/env python3
"""
Keep the Cattle Cycles seed current. For the droplet's crontab.

WHY A JOB AND NOT A PAGE FETCH. The seed behind apps/cattle_cycles is two
keyless feeds -- USDA NASS monthly price received and BLS CPI-U -- so nothing
about credentials stops the page reading them itself. What stops it is size:
the NASS side is a 464MB gzipped dump of every animal-products observation
NASS has ever published, 10.2 million lines, of which this page wants 3,694.
That is not a page load, and there is no smaller keyless cut of it -- the
QuickStats API would need a key the portal's deployment does not carry for
this page. The droplet streams it in about 25 seconds and writes the 3,694.

WHAT GOES STALE. Both halves, at different rates and on different clocks.
NASS publishes Agricultural Prices near the end of each month and the price
series runs about a month behind; BLS publishes CPI mid-month. So the seed
can be a month stale in prices and current in CPI at the same time, which is
exactly what the committed file shows today (prices to Aug 2026, CPI to Sep
2026). Both are refetched every run and neither is assumed to move with the
other.

SELECTION IS BY EXACT short_desc AND THAT IS THE WHOLE CORRECTNESS OF THIS
FILE. NASS carries both

    CATTLE, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT
    CATTLE, STEERS & HEIFERS, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT

and they share the tail `GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT`,
which is a substring of BOTH. (The first is not itself a substring of the
second -- "CATTLE, GE 500 LBS" against "HEIFERS, GE 500 LBS" -- so the trap is
the shared tail, not the whole string. It is worth being exact about, because
the loose version invites a reader to test `broad in narrow`, find False, and
conclude the trap is not real.) Any match that is not anchored at both ends --
`in`, `endswith`, a SQL LIKE '%...%' -- therefore admits both series under one
key: they overlap on 884 months and differ on all 884 (Jan 1953 is 19.1
against 21.9), so the result is a plausible series that is two price
definitions spliced at random. That is not hypothetical -- it is how the first
cut of this analysis was built, and it moved the headline median cycle from
7.4 years to 10.1 while rendering perfectly. SERIES below is keyed on the
exact string and `_qualifies` compares with `==`; tests/test_cattle_cycles_
refresh.py pins both and asserts the two series really do still collide.

APPEND-ONLY, NEWEST WINS PER (SERIES, PERIOD) -- the shape
JSA.BOXED_BEEF.CUTOUT_AM, JSA.LETTER.DRAFTS and SOUTHEAST_RETENTION already
use, and for the same reasons: an INSERT needs no UPDATE grant, and no run can
bury the figure a previous run recorded. That matters more here than for most
of them, because NASS REVISES price received -- a month published preliminary
in October is restated in November. The superseded figure stays on the record.

IDEMPOTENT, so the schedule can be blunt. A period whose value has not moved
is skipped, so the second run of the month fetches both feeds and writes
nothing at all. There is no holiday calendar to maintain and none to get
wrong. The first run writes about 5,058 rows; every run after it writes the
handful of months that actually changed.

THE SHORTFALL GUARD IS NOT PARANOIA. An interrupted stream that closes
cleanly yields a SHORT series, and because unchanged periods are skipped the
job would then write nothing and report "nothing had changed" -- a truncated
fetch and a quiet month are indistinguishable at the exit code. So a series
that comes back with fewer periods than the committed seed holds is a failure,
not a no-op. It cannot corrupt the table (newest-wins per period means absent
periods keep their last recorded value) but it would silently corrupt the seed
under --write-json, and it is the one failure here that otherwise looks
healthy.

Exit codes: 0 wrote or had nothing to write, 1 could not fetch, came back
short, or could not write. The droplet has no MAILTO and no MTA, so the exit
code is the entire alerting contract -- see deploy/run_cattle_cycles.sh.
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "apps" / "cattle_cycles" / "data" / "cattle_cycles.json"

TABLE = "JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES"

# BLS refuses a request with no User-Agent, or with a library default, with a
# 403 that reads as a dead link. A real one is a condition of their access
# policy rather than a workaround.
UA = {"User-Agent": "JSA-livestock-portal/1.0 (RBaldwin@jpsi.com)"}

NASS_DIR = "https://www.nass.usda.gov/datasets/"
# THERE IS NO STABLE "latest" ALIAS. The dump is named for the day it was cut
# (qs.animals_products_20261020.txt.gz) and the directory carries exactly one,
# so the filename has to be scraped. Guessing today's date fails on any day
# NASS has not re-cut it yet, which is most days.
NASS_FILE_RE = re.compile(r"qs\.animals_products_\d{8}\.txt\.gz")

BLS_URL = "https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems"
CPI_SERIES_ID = "CUUR0000SA0"   # CPI-U, US city average, all items, NSA
CPI_KEY = "cpi_u"

# EXACT NASS short_desc -> the key the seed and cycles.py use. Never match
# these by substring; see the module note.
SERIES = {
    "CATTLE, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT": "cattle_ge500",
    "CATTLE, CALVES - PRICE RECEIVED, MEASURED IN $ / CWT": "calves",
    "CATTLE, COWS - PRICE RECEIVED, MEASURED IN $ / CWT": "cows",
}

# The near-miss that makes the exact match load-bearing. It is named here so a
# test can assert the collision is still live -- if NASS ever renames one of
# them the trap is gone, but so is the reason the test exists.
COLLIDING_SHORT_DESC = (
    "CATTLE, STEERS & HEIFERS, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT"
)

# Columns of the bulk dump, 1-indexed as NASS numbers them in its own layout
# file. Note COL_BEGIN is BEGIN_CODE, which for a MONTHLY row is the month
# number -- there is no column literally called "period".
COL_COMMODITY = 4
COL_SHORT_DESC = 10
COL_AGG = 13
COL_YEAR = 31
COL_FREQ = 32
COL_BEGIN = 33
COL_VALUE = 38

UNIT = "$/cwt"


def _load_db():
    """snowflake_db under a PRIVATE name.

    That module exists five times in this repo and is imported by bare name by
    several pages, so whichever loads first wins for every other. Loading it by
    path under a name of our own keeps this job out of that collision -- the
    same thing letter/draft_store.py and deploy/refresh_southeast.py do.
    """
    path = REPO / "apps" / "us_cow_herd" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_cyc_snowflake_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cyc_snowflake_db"] = mod
    spec.loader.exec_module(mod)
    return mod


# -- parsing ------------------------------------------------------------------

def _num(raw: str):
    """A NASS or BLS value as a float, or None.

    Both feeds mark an absent figure in-band rather than leaving it out:
    BLS writes a bare "-" (that is October 2025, the one hole in 113 years of
    CPI) and NASS writes "(D)" withheld, "(NA)", "(Z)" or "(S)". Read naively
    every one of those raises mid-stream, which on a 10-million-line scan
    reads as a corrupt download. Thousands separators appear on head counts
    elsewhere in the same dump and cost nothing to strip here.
    """
    v = (raw or "").strip().replace(",", "")
    if not v or v.startswith("("):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _qualifies(fields: list[str]) -> str | None:
    """The seed key for a dump row, or None. The `==` here is load-bearing."""
    if len(fields) <= COL_VALUE - 1:
        return None
    key = SERIES.get(fields[COL_SHORT_DESC - 1])      # exact, never `in`
    if key is None:
        return None
    if fields[COL_AGG - 1] != "NATIONAL":
        return None
    if fields[COL_FREQ - 1] != "MONTHLY":
        return None
    return key


def _period(year: str, begin_code: str) -> str | None:
    """'2026-08' from YEAR and BEGIN_CODE, or None if it is not a real month."""
    try:
        y, m = int(year), int(begin_code)
    except (TypeError, ValueError):
        return None
    if not (1800 < y < 2200 and 1 <= m <= 12):
        return None
    return f"{y:04d}-{m:02d}"


def nass_latest_filename(session=None) -> str:
    import requests
    get = session.get if session else requests.get
    r = get(NASS_DIR, headers=UA, timeout=(10, 120))
    r.raise_for_status()
    names = sorted(set(NASS_FILE_RE.findall(r.text)))
    if not names:
        raise RuntimeError(f"no animals_products dump linked from {NASS_DIR}")
    return names[-1]


def fetch_nass(url: str, verbose: bool = True) -> dict[str, dict[str, float]]:
    """{seed key: {'YYYY-MM': price}} from the streamed bulk dump.

    Streamed through resp.raw deliberately: requests would otherwise decode
    Content-Encoding for us, and the gzip here is the FILE rather than a
    transfer encoding. Nothing is written to disk -- 464MB has no business
    landing on a droplet for 3,694 numbers.
    """
    import requests
    out: dict[str, dict[str, float]] = {k: {} for k in SERIES.values()}
    with requests.get(url, headers=UA, timeout=(10, 600), stream=True) as resp:
        resp.raise_for_status()
        gz = gzip.GzipFile(fileobj=resp.raw)
        lines = 0
        for raw in io.TextIOWrapper(gz, encoding="utf-8", errors="replace"):
            lines += 1
            if lines == 1:
                continue                      # header
            f = raw.rstrip("\n").split("\t")
            # Cheap prefilter: all three series are COMMODITY_DESC CATTLE, and
            # this skips ~99.9% of the dump before the string compares.
            if len(f) <= COL_VALUE - 1 or f[COL_COMMODITY - 1] != "CATTLE":
                continue
            key = _qualifies(f)
            if key is None:
                continue
            period = _period(f[COL_YEAR - 1], f[COL_BEGIN - 1])
            value = _num(f[COL_VALUE - 1])
            if period is None or value is None:
                continue
            out[key][period] = value
    if verbose:
        print(f"  scanned {lines:,} lines")
    return out


def fetch_cpi(verbose: bool = True) -> dict[str, float]:
    """{'YYYY-MM': index} for CUUR0000SA0.

    M13 IS NOT A MONTH. BLS writes the year's ANNUAL AVERAGE as period M13 in
    the same column as M01..M12 -- 113 of them in this file. Admitting it adds
    a thirteenth observation a year at a value near the year's mean, which
    charts perfectly and quietly shifts every month's deflator.
    """
    import requests
    rows: dict[str, float] = {}
    with requests.get(BLS_URL, headers=UA, timeout=(10, 300), stream=True) as resp:
        resp.raise_for_status()
        for i, line in enumerate(resp.iter_lines(decode_unicode=True)):
            if i == 0 or not line:
                continue
            f = line.split("\t")
            if len(f) < 4 or f[0].strip() != CPI_SERIES_ID:
                continue
            period = f[2].strip()
            if not period.startswith("M") or period == "M13":
                continue
            p = _period(f[1].strip(), period[1:])
            v = _num(f[3])
            if p is None or v is None:
                continue
            rows[p] = v
    if verbose:
        print(f"  {CPI_SERIES_ID}: {len(rows):,} months")
    return rows


# -- the seed payload ---------------------------------------------------------

def _months_between(first: str, last: str) -> int:
    fy, fm = int(first[:4]), int(first[5:])
    ly, lm = int(last[:4]), int(last[5:])
    return (ly - fy) * 12 + lm - fm + 1


def describe(rows: dict[str, float]) -> dict:
    """first/last/n/missing for a period-keyed series."""
    if not rows:
        return {"first": None, "last": None, "n": 0, "missing": []}
    ks = sorted(rows)
    first, last = ks[0], ks[-1]
    have = set(ks)
    missing = []
    y, m = int(first[:4]), int(first[5:])
    for _ in range(_months_between(first, last)):
        p = f"{y:04d}-{m:02d}"
        if p not in have:
            missing.append(p)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return {"first": first, "last": last, "n": len(rows), "missing": missing}


def seed_payload(prices: dict[str, dict[str, float]], cpi: dict[str, float],
                 previous: dict | None = None) -> dict:
    """The committed-seed structure, rebuilt from a fetch.

    `schema`, `note` and `sources` are carried over from the file being
    replaced rather than restated here, so regenerating it cannot silently
    rewrite the note that explains why it stores nominal prices.
    """
    prev = previous or {}
    desc_by_key = {v: k for k, v in SERIES.items()}
    series = {}
    for key, rows in prices.items():
        series[key] = {"short_desc": desc_by_key[key], "unit": UNIT,
                       **describe(rows),
                       "rows": {k: rows[k] for k in sorted(rows)}}
    return {
        "schema": prev.get("schema", 1),
        "note": prev.get(
            "note",
            "Nominal monthly prices as published, plus CPI-U. Deflate at load "
            "-- storing real values would freeze the base year into this file."),
        "sources": prev.get("sources", {
            "price": {"agency": "USDA NASS QuickStats", "agg_level": "NATIONAL",
                      "statisticcat": "PRICE RECEIVED", "freq": "MONTHLY",
                      "bulk_dump": NASS_DIR + "qs.animals_products_<YYYYMMDD>.txt.gz"},
            "cpi": {"agency": "US BLS", "series_id": CPI_SERIES_ID, "url": BLS_URL},
        }),
        "series": {k: series[k] for k in sorted(series)},
        "cpi_u": {**describe(cpi), "rows": {k: cpi[k] for k in sorted(cpi)}},
    }


# -- Snowflake ----------------------------------------------------------------

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    SERIES STRING NOT NULL,
    PERIOD STRING NOT NULL,
    VALUE FLOAT NOT NULL,
    SHORT_DESC STRING,
    SOURCE STRING,
    RECORDED_AT TIMESTAMP_NTZ NOT NULL
)
"""


def existing(conn) -> dict[tuple[str, str], float]:
    """Newest row per (series, period), as the page reads it."""
    cur = conn.cursor().execute(
        f"SELECT SERIES, PERIOD, VALUE FROM {TABLE} "
        f"QUALIFY ROW_NUMBER() OVER (PARTITION BY SERIES, PERIOD "
        f"ORDER BY RECORDED_AT DESC) = 1")
    return {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}


def pending(prices: dict[str, dict[str, float]], cpi: dict[str, float],
            have: dict[tuple[str, str], float]) -> list[tuple]:
    """Rows whose value has MOVED (or is new). The whole idempotency story.

    NASS restates price received, so an existing period changing is normal and
    is exactly what has to be written -- append-only keeps the superseded
    figure. A period that has not moved is skipped, which is what lets the
    catch-up run cost two fetches and no write.
    """
    desc_by_key = {v: k for k, v in SERIES.items()}
    out = []
    for key, rows in sorted(prices.items()):
        for period in sorted(rows):
            v = rows[period]
            prev = have.get((key, period))
            if prev is not None and abs(prev - v) < 1e-9:
                continue
            out.append((key, period, v, desc_by_key[key], "nass"))
    for period in sorted(cpi):
        v = cpi[period]
        prev = have.get((CPI_KEY, period))
        if prev is not None and abs(prev - v) < 1e-9:
            continue
        out.append((CPI_KEY, period, v, CPI_SERIES_ID, "bls"))
    return out


def write(conn, rows: list[tuple]) -> int:
    # CREATE SCHEMA is attempted and its failure IGNORED on purpose. The target
    # schema already exists, and the identity that runs this may not hold
    # CREATE SCHEMA on the database -- CME_INGEST_ROLE does not, and raising
    # there would stop a job whose schema is sitting right in front of it. If
    # the schema really is missing, the CREATE TABLE below says so.
    try:
        conn.cursor().execute(
            f"CREATE SCHEMA IF NOT EXISTS {'.'.join(TABLE.split('.')[:2])}")
    except Exception:
        pass
    conn.cursor().execute(DDL)
    if not rows:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sql = (f"INSERT INTO {TABLE} (SERIES, PERIOD, VALUE, SHORT_DESC, SOURCE, "
           f"RECORDED_AT) VALUES (%s,%s,%s,%s,%s,%s)")
    # Chunked executemany rather than a row at a time: the FIRST run writes
    # about 5,058 rows and a per-row round trip to Snowflake makes that minutes
    # instead of seconds. Every run after it writes a handful.
    cur = conn.cursor()
    for i in range(0, len(rows), 1000):
        cur.executemany(sql, [r + (now,) for r in rows[i:i + 1000]])
    conn.commit()
    return len(rows)


# -- main ---------------------------------------------------------------------

def _shortfall(prices, cpi, seed) -> list[str]:
    """Series that came back with fewer periods than the committed seed holds.

    See the module note: a cleanly-truncated stream otherwise writes nothing
    and exits 0, which is indistinguishable from a month in which nothing
    changed.
    """
    bad = []
    for key, rows in prices.items():
        want = len((seed.get("series", {}).get(key) or {}).get("rows") or {})
        if want and len(rows) < want:
            bad.append(f"{key}: {len(rows)} fetched vs {want} in the seed")
    want_cpi = len((seed.get(CPI_KEY) or {}).get("rows") or {})
    if want_cpi and len(cpi) < want_cpi:
        bad.append(f"{CPI_KEY}: {len(cpi)} fetched vs {want_cpi} in the seed")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and print, write nothing")
    ap.add_argument("--write-json", action="store_true",
                    help="also refresh the committed seed (local rebuilds only)")
    args = ap.parse_args()

    seed = {}
    if SEED.exists():
        try:
            seed = json.loads(SEED.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"could not read {SEED}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

    try:
        name = nass_latest_filename()
        print(f"NASS dump: {name}")
        prices = fetch_nass(NASS_DIR + name)
    except Exception as e:
        print(f"NASS fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    try:
        cpi = fetch_cpi()
    except Exception as e:
        print(f"BLS fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"\n{'series':<14}{'n':>7}  span")
    for key in sorted(prices):
        d = describe(prices[key])
        print(f"{key:<14}{d['n']:>7}  {d['first']} -> {d['last']}"
              + (f"  missing {len(d['missing'])}" if d["missing"] else ""))
    d = describe(cpi)
    print(f"{CPI_KEY:<14}{d['n']:>7}  {d['first']} -> {d['last']}"
          + (f"  missing {d['missing']}" if d["missing"] else ""))

    short = _shortfall(prices, cpi, seed)
    if short:
        print("\nABORT: a series came back shorter than the committed seed --",
              file=sys.stderr)
        for s in short:
            print(f"  {s}", file=sys.stderr)
        print("that is a truncated fetch, not a quiet month.", file=sys.stderr)
        return 1

    if args.write_json:
        SEED.write_text(json.dumps(seed_payload(prices, cpi, seed), indent=1),
                        encoding="utf-8")
        print(f"\nwrote {SEED}")

    if args.dry_run:
        rows = pending(prices, cpi, {})
        print(f"\n--dry-run: nothing written to Snowflake "
              f"({len(rows):,} rows would be written to an empty table)")
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
        try:
            have = existing(conn)
        except Exception:
            have = {}          # table does not exist yet; write() creates it
        rows = pending(prices, cpi, have)
        n = write(conn, rows)
        print(f"\n{n:,} row(s) written to {TABLE}"
              + (" (nothing had changed)" if n == 0 else ""))
    except Exception as e:
        print(f"write failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
