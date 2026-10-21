#!/usr/bin/env python3
"""
Keep the Cattle Cycles seed current. For the droplet's crontab.

WHY A JOB AND NOT A PAGE FETCH. The seed behind apps/cattle_cycles is two
keyless feeds -- USDA NASS monthly price received and BLS CPI-U -- so nothing
about credentials stops the page reading them itself. What stops it is size:
the NASS side is a 464MB gzipped dump of every animal-products observation
NASS has ever published, 10.2 million lines, of which this page wants 3,961.
That is not a page load, and there is no smaller keyless cut of it -- the
QuickStats API would need a key the portal's deployment does not carry for
this page. The droplet streams it in about 25 seconds and writes the 3,961.

ONE PASS, TWO KINDS OF SERIES. The same stream carries the monthly PRICE
RECEIVED figures the price views chart and the annual January 1 INVENTORY
counts the herd view dates its liquidations from, so both are collected in a
single scan. A second pass would double a 464MB download for 267 numbers.

WHAT GOES STALE. Both halves, at different rates and on different clocks.
NASS publishes Agricultural Prices near the end of each month and the price
series runs about a month behind; BLS publishes CPI mid-month. So the seed
can be a month stale in prices and current in CPI at the same time, which is
exactly what the committed file shows today (prices to Aug 2026, CPI to Sep
2026). Both are refetched every run and neither is assumed to move with the
other.

The inventory half runs on a third clock and a far slower one: USDA counts the
herd once, on January 1, and publishes that count in late January. So for
eleven months of the year a correct run writes no inventory at all, which is
why the shortfall guard rather than the row count is what says the fetch
worked.

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

THE SAME TRAP IS LIVE ON THE INVENTORY SIDE AND IT IS SHARPER. NASS carries

    CATTLE, INCL CALVES - INVENTORY                      head, 160 years
    CATTLE, INCL CALVES - INVENTORY, MEASURED IN $        dollars, 160 years
    CATTLE, INCL CALVES - INVENTORY, MEASURED IN $ / HEAD dollars, 160 years

and the first is a strict PREFIX of the other two. All three are NATIONAL,
STATISTICCAT_DESC INVENTORY, REFERENCE_PERIOD_DESC FIRST OF JAN and domain
TOTAL, so every filter below passes all three and only the exact short_desc
separates them -- where the price trap is caught by nothing else either, but
at least differs in wording rather than in unit. They collide on all 160
years: 1867 is 28,636,000 head, $547,888,000 and $19.13 per head, and 2026
is 86,155,300 head against $207,540,308,000. A substring match therefore
yields whichever row the dump happened to serve last, under a label saying
head.

REFERENCE_PERIOD_DESC IS NOT DECORATION EITHER. The identical short_desc,
statisticcat, aggregation and domain also appear at FIRST OF JUL (51-53 years)
and END OF DEC. Those are real head counts of the same herd at another moment,
so dropping that filter does not produce an obviously wrong chart -- it
produces a January series with a midsummer count spliced into half of it.
FREQ_DESC does NOT do this job: inventory rows are POINT IN TIME, not ANNUAL,
so the test the price path makes on that column has no equivalent here.

Both are pinned in tests/test_cattle_cycles_refresh.py, and `fetch_nass`
raises if two rows ever land on one year with different values -- a filter
that stops selecting one row a year is the failure this whole note is about,
and a count of 107 looks exactly as healthy whichever row won.

INVENTORY GOES INTO THE SAME SNOWFLAKE TABLE AS THE PRICES, AND THE TABLE'S
NAME IS NOW A MISNOMER. JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES carries
`beef_cows` and `all_cattle` beside the three price series and CPI-U, with
PERIOD holding a bare year ("2026") where a price holds "2026-08" -- PERIOD is
a string, so that fits, and no key can collide because the series names differ.

The alternative was to leave inventory in the committed file alone and let
cycles.load() take prices from the table and the herd series from the file.
That is rejected because the page NAMES ITS SOURCE in a caption, and a read
that reported "the live table" over a herd chart drawn from a file nobody had
regenerated would be a lie told by the one control that exists to prevent one.
Writing both into the table keeps that caption true for every view, and keeps
the fallback the all-or-nothing one cycles._at_least_as_long already argues
for.

The cost is a name. Renaming a live table is a migration; a reader meeting
`beef_cows` in CATTLE_CYCLE_PRICES is told what it is by SHORT_DESC on the row
("CATTLE, COWS, BEEF - INVENTORY"), which is the same provenance column that
makes the substring trap visible in the data rather than only in this file.

One consequence worth knowing before it is reported as a bug: a table written
by the version of this job that fetched prices only has no inventory in it, so
cycles.load() falls back to the committed file WHOLE until this job has run
once. Prices stop advancing for that interval; nothing goes dark.

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

# EXACT NASS short_desc -> the key the seed and cycles.py use for the herd
# view's January 1 head counts. Never match these by substring either; see the
# module note, where the near-miss is a DOLLAR value over the same 160 years.
INVENTORY_SERIES = {
    "CATTLE, COWS, BEEF - INVENTORY": "beef_cows",
    "CATTLE, INCL CALVES - INVENTORY": "all_cattle",
}

# The near-misses that make the exact match load-bearing on the inventory side.
# Both are NATIONAL / INVENTORY / FIRST OF JAN / TOTAL like the real series and
# both run 1867-2026, so every filter but the short_desc admits them.
COLLIDING_INVENTORY_SHORT_DESCS = (
    "CATTLE, INCL CALVES - INVENTORY, MEASURED IN $",
    "CATTLE, INCL CALVES - INVENTORY, MEASURED IN $ / HEAD",
)

# Columns of the bulk dump, 1-indexed as NASS numbers them in its own layout
# file. Note COL_BEGIN is BEGIN_CODE, which for a MONTHLY row is the month
# number -- there is no column literally called "period".
COL_COMMODITY = 4
COL_STATISTICCAT = 8
COL_SHORT_DESC = 10
COL_AGG = 13
COL_YEAR = 31
COL_FREQ = 32
COL_BEGIN = 33
COL_REF_PERIOD = 35
COL_VALUE = 38

UNIT = "$/cwt"

# The one moment of the year the herd view is about. It is a FILTER and not a
# label: the same series is published at FIRST OF JUL and END OF DEC under an
# identical short_desc. Stored on the seed block too, so the file says which
# count it holds rather than leaving that to this module.
REF_PERIOD_JAN = "FIRST OF JAN"
INVENTORY_UNIT = "head"


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


def _qualifies_inventory(fields: list[str]) -> str | None:
    """The seed key for a January 1 inventory row, or None. `==` again.

    FOUR CONDITIONS AND EVERY ONE OF THEM IS LOAD-BEARING -- see the module
    note. The exact short_desc keeps out two dollar-valued series that share
    the prefix; REFERENCE_PERIOD_DESC keeps out the midsummer and year-end
    counts of the same herd, which are real head counts and would splice in
    without looking wrong.

    FREQ_DESC IS DELIBERATELY NOT TESTED. These rows are POINT IN TIME, not
    ANNUAL, so the `== "MONTHLY"` test the price path makes has no equivalent
    here and guessing "ANNUAL" by symmetry selects nothing at all.
    """
    if len(fields) <= COL_VALUE - 1:
        return None
    key = INVENTORY_SERIES.get(fields[COL_SHORT_DESC - 1])    # exact, never `in`
    if key is None:
        return None
    if fields[COL_AGG - 1] != "NATIONAL":
        return None
    if fields[COL_STATISTICCAT - 1] != "INVENTORY":
        return None
    if fields[COL_REF_PERIOD - 1] != REF_PERIOD_JAN:
        return None
    return key


def _year(year: str) -> str | None:
    """'2026' from YEAR, or None if it is not a plausible one.

    THE PERIOD KEY IS THE YEAR ALONE, NOT 'YYYY-01'. A January 1 inventory is a
    point-in-time count stamped with its year, and cycles.inventory() indexes
    it by int(year) precisely so nobody can line it up against a monthly price
    series and difference the two. A 'YYYY-01' key would read as a month and
    would sort into the price series' own period space.
    """
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    if not (1800 < y < 2200):
        return None
    return f"{y:04d}"


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


def fetch_nass(url: str, verbose: bool = True) -> tuple[
        dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """({price key: {'YYYY-MM': $}}, {inventory key: {'YYYY': head}}), ONE PASS.

    Both halves come off the same stream because a second pass would mean
    downloading 464MB again for 267 numbers. The two are returned apart rather
    than merged: they are different periods, different units and different
    clocks, and the whole herd view exists on the premise that the price cycle
    and the herd cycle are not two views of one series.

    Streamed through resp.raw deliberately: requests would otherwise decode
    Content-Encoding for us, and the gzip here is the FILE rather than a
    transfer encoding. Nothing is written to disk -- 464MB has no business
    landing on a droplet for 3,961 numbers.
    """
    import requests
    prices: dict[str, dict[str, float]] = {k: {} for k in SERIES.values()}
    inv: dict[str, dict[str, float]] = {k: {} for k in INVENTORY_SERIES.values()}
    with requests.get(url, headers=UA, timeout=(10, 600), stream=True) as resp:
        resp.raise_for_status()
        gz = gzip.GzipFile(fileobj=resp.raw)
        lines = 0
        for raw in io.TextIOWrapper(gz, encoding="utf-8", errors="replace"):
            lines += 1
            if lines == 1:
                continue                      # header
            f = raw.rstrip("\n").split("\t")
            # Cheap prefilter: every series wanted here is COMMODITY_DESC
            # CATTLE, and this skips ~99.9% of the dump before the string
            # compares. The value is parsed only once a key has matched --
            # this line runs ten million times.
            if len(f) <= COL_VALUE - 1 or f[COL_COMMODITY - 1] != "CATTLE":
                continue
            key = _qualifies(f)
            if key is not None:
                period = _period(f[COL_YEAR - 1], f[COL_BEGIN - 1])
                value = _num(f[COL_VALUE - 1])
                if period is not None and value is not None:
                    prices[key][period] = value
                continue
            key = _qualifies_inventory(f)
            if key is None:
                continue
            period = _year(f[COL_YEAR - 1])
            value = _num(f[COL_VALUE - 1])
            if period is None or value is None:
                continue
            # TWO VALUES FOR ONE YEAR MEANS A FILTER HAS STOPPED SELECTING ONE
            # ROW A YEAR, and that is the one failure here with no symptom: the
            # count stays 107 whichever row lands last, and a July count or a
            # dollar value charts perfectly under a label saying January head.
            # There are zero such collisions today, which is what makes raising
            # safe rather than a nuisance.
            prior = inv[key].get(period)
            if prior is not None and abs(prior - value) > 1e-9:
                raise RuntimeError(
                    f"{f[COL_SHORT_DESC - 1]} has two different values for "
                    f"{period}: {prior} and {value}. A filter in "
                    f"_qualifies_inventory is no longer selecting one row a "
                    f"year -- see the module note.")
            inv[key][period] = value
    if verbose:
        print(f"  scanned {lines:,} lines")
    return prices, inv


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


def describe_years(rows: dict[str, float]) -> dict:
    """first/last/n for a year-keyed series, with first and last as INTS.

    Separate from describe() rather than a flag on it. That one walks a month
    grid and lists the holes it finds, and the shape it returns -- string
    periods and a `missing` list -- is the shape the committed seed stores for
    a MONTHLY series. The inventory blocks in that file carry neither, so one
    shared function would mean either changing the file's shape or branching
    inside it on the kind of key it was handed. A gap in the years shows here
    as n < last - first + 1, which these three figures already say between
    them; both series are contiguous today.
    """
    if not rows:
        return {"first": None, "last": None, "n": 0}
    ys = sorted(int(y) for y in rows)
    return {"first": ys[0], "last": ys[-1], "n": len(rows)}


def seed_payload(prices: dict[str, dict[str, float]], cpi: dict[str, float],
                 inventory: dict[str, dict[str, float]],
                 previous: dict | None = None) -> dict:
    """The committed-seed structure, rebuilt from a fetch.

    `schema`, `note` and `sources` are carried over from the file being
    replaced rather than restated here, so regenerating it cannot silently
    rewrite the note that explains why it stores nominal prices.

    INVENTORY IS FETCHED NOW AND AN EMPTY ONE RAISES. It was carried over from
    the previous file for as long as this job did not fetch it, which kept a
    rebuild from deleting a series the page depends on. Now that the fetch
    exists, the carry-over would hide exactly the failure it used to prevent:
    a scan that matched no inventory rows -- a renamed short_desc, a dropped
    reference period -- would write a seed whose herd half was last year's
    while every count in it still looked plausible. Refusing outright is the
    only reading of "no inventory came back" that cannot be mistaken for a
    quiet month, and the herd view reads this block and nothing else, so the
    alternative failure takes one view off the page while every price view
    keeps working.
    """
    missing = [k for k in INVENTORY_SERIES.values() if not inventory.get(k)]
    if missing:
        raise ValueError(
            "refusing to build a seed with no January 1 inventory for "
            + ", ".join(missing)
            + " -- the herd view reads that block and nothing else, so writing "
              "this would take the view off the page rather than fail the job")

    prev = previous or {}
    desc_by_key = {v: k for k, v in SERIES.items()}
    series = {}
    for key, rows in prices.items():
        series[key] = {"short_desc": desc_by_key[key], "unit": UNIT,
                       **describe(rows),
                       "rows": {k: rows[k] for k in sorted(rows)}}
    inv_desc_by_key = {v: k for k, v in INVENTORY_SERIES.items()}
    inv = {}
    for key, rows in inventory.items():
        inv[key] = {"short_desc": inv_desc_by_key[key], "unit": INVENTORY_UNIT,
                    "period": REF_PERIOD_JAN,
                    **describe_years(rows),
                    "rows": {k: rows[k] for k in sorted(rows, key=int)}}
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
            "inventory": {"agency": "USDA NASS QuickStats",
                          "agg_level": "NATIONAL", "statisticcat": "INVENTORY",
                          "reference_period": REF_PERIOD_JAN,
                          "bulk_dump": NASS_DIR + "qs.animals_products_<YYYYMMDD>.txt.gz"},
        }),
        "series": {k: series[k] for k in sorted(series)},
        "cpi_u": {**describe(cpi), "rows": {k: cpi[k] for k in sorted(cpi)}},
        "inventory": {k: inv[k] for k in sorted(inv)},
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
            inventory: dict[str, dict[str, float]],
            have: dict[tuple[str, str], float]) -> list[tuple]:
    """Rows whose value has MOVED (or is new). The whole idempotency story.

    NASS restates price received, so an existing period changing is normal and
    is exactly what has to be written -- append-only keeps the superseded
    figure. A period that has not moved is skipped, which is what lets the
    catch-up run cost two fetches and no write.

    Inventory restates too: the January count is published preliminary and
    revised against the following year, so a year already in the table moving
    is the normal case rather than the alarming one. Its PERIOD is a bare year
    against a price PERIOD of "YYYY-MM"; nothing can collide because the
    series names differ, and SHORT_DESC on every row says which kind it is.
    """
    desc_by_key = {v: k for k, v in SERIES.items()}
    inv_desc_by_key = {v: k for k, v in INVENTORY_SERIES.items()}
    out = []
    for key, rows in sorted(prices.items()):
        for period in sorted(rows):
            v = rows[period]
            prev = have.get((key, period))
            if prev is not None and abs(prev - v) < 1e-9:
                continue
            out.append((key, period, v, desc_by_key[key], "nass"))
    for key, rows in sorted(inventory.items()):
        for period in sorted(rows, key=int):
            v = rows[period]
            prev = have.get((key, period))
            if prev is not None and abs(prev - v) < 1e-9:
                continue
            out.append((key, period, v, inv_desc_by_key[key], "nass"))
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

def _shortfall(prices, cpi, inventory, seed) -> list[str]:
    """Series that came back with fewer periods than the committed seed holds.

    See the module note: a cleanly-truncated stream otherwise writes nothing
    and exits 0, which is indistinguishable from a month in which nothing
    changed.

    THE INVENTORY SIDE NEEDS THIS MORE THAN THE PRICES DO, because it is right
    for it to write nothing eleven months of the year -- USDA counts the herd
    once. "No new inventory" is therefore the expected outcome of a healthy run
    and cannot be read as a signal, so a count against the seed is the only
    thing separating it from a fetch that matched no inventory rows at all.
    """
    bad = []
    for key, rows in prices.items():
        want = len((seed.get("series", {}).get(key) or {}).get("rows") or {})
        if want and len(rows) < want:
            bad.append(f"{key}: {len(rows)} fetched vs {want} in the seed")
    for key, rows in inventory.items():
        want = len((seed.get("inventory", {}).get(key) or {}).get("rows") or {})
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
        prices, inv = fetch_nass(NASS_DIR + name)
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
    for key in sorted(inv):
        d = describe_years(inv[key])
        # The span is printed beside the count because they are the gap check:
        # a year USDA never published shows as n below last - first + 1, and
        # there is nothing else on this line that would say so.
        span = (d["last"] - d["first"] + 1) if d["n"] else 0
        print(f"{key:<14}{d['n']:>7}  {d['first']} -> {d['last']}"
              + (f"  missing {span - d['n']}" if span != d["n"] else ""))
    d = describe(cpi)
    print(f"{CPI_KEY:<14}{d['n']:>7}  {d['first']} -> {d['last']}"
          + (f"  missing {d['missing']}" if d["missing"] else ""))

    # THE SHORTFALL CHECK RUNS BEFORE --write-json AND THAT ORDER IS THE GUARD.
    # Below it, a short fetch would be written over the committed seed, and the
    # seed is what the page falls back to whenever Snowflake is unreachable --
    # so a truncated run would quietly shorten the record for every reader.
    short = _shortfall(prices, cpi, inv, seed)
    if short:
        print("\nABORT: a series came back shorter than the committed seed --",
              file=sys.stderr)
        for s in short:
            print(f"  {s}", file=sys.stderr)
        print("that is a truncated fetch, not a quiet month.", file=sys.stderr)
        return 1

    if args.write_json:
        SEED.write_text(json.dumps(seed_payload(prices, cpi, inv, seed), indent=1),
                        encoding="utf-8")
        print(f"\nwrote {SEED}")

    if args.dry_run:
        rows = pending(prices, cpi, inv, {})
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
        rows = pending(prices, cpi, inv, have)
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
