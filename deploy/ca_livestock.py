#!/usr/bin/env python3
"""
Record AMS 3213 — Weekly Canadian Livestock and Poultry Summary. For the droplet.

WHY THIS EXISTS. The Mexican half of apps/mexican_feeder_imports/ is built on
AMS 3486 and 3629, and NEITHER HAS A CANADIAN COUNTERPART: a sweep of all 1,051
MARS reports and all 151 LMR datamart reports on 2026-10-07 found exactly one
Canadian livestock report, and this is it. It carries Canadian-side feeder and
slaughter-cattle prices by region, already in US dollars per hundredweight, and
Canadian federally-inspected slaughter by class. It does NOT carry cross-border
head counts — nothing published does, and those have to come from Census.

WHY A DROPLET JOB RATHER THAN A PAGE FETCH. `marsapi.ams.usda.gov` rejects
Streamlit Community Cloud's IPs — CLAUDE.md, confirmed 2026-10-04, and the same
reason the beef-trimmings import side moved here. A live fetch from the page
would fail in production whatever we wanted, so the page reads Snowflake and
this writes it, exactly as the Mexican side already works.

IT DEFINES NO PARSING OF ITS OWN. Every figure is produced by
`apps/canadian_feeder_cattle/ca_prices.py`, imported BY PATH, so the cron and
the page can never disagree about what a report says. A second copy of a parser
running unattended, where nobody would see it drift, is the
`snowflake_db.py`-times-five problem with no renderer to catch it — the rule
`deploy/bank_am_cutout.py` already follows, and `tests/test_ca_livestock.py`
asserts it by AST rather than by grep.

THE SCHEDULE IS A DAILY SWEEP FOR A WEEKLY REPORT, which looks wasteful and is
not. Measured over all 121 publications on file:

    publish weekday   Tue 105, Mon 11, Wed 3, Thu 1, Fri 1
    publish hour      06 (61), 07 (42), 08 (3), 04 (2), 09 (1),
                      11 (3), 12 (1), 13 (1), 14 (6), 15 (1)
    lag to publish    9-17 days after the week ends, median 10

So a Tuesday-only job would miss 16 weeks in 121 until the following Tuesday,
and a single pinned hour would miss the dozen that land after 11:00. Daily
costs one HTTP request on the six days a week that write nothing, needs no
holiday calendar and no DST arithmetic, and the timestamps' own timezone — AMS
publishes out of Washington DC and the droplet runs America/Chicago — never has
to be resolved. `bank_prices`/`bank_slaughter` insert only what is absent or
changed, which is what makes a blunt schedule safe.

HISTORY: 2024-06-01 forward, 119 usable weeks, and that is all AMS keeps. The
first run backfills the lot in one request per section; every run after it
writes nothing until a new week publishes.

Exit codes: 0 banked or already present, 1 could not fetch or could not write.
A non-zero exit is the whole alerting story — the droplet's crontab has no
MAILTO and the box has no MTA, so every job runs under /opt/alerting/cron-alert
and a bare entry would fail silently for ever.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent

BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"

#: Generous because this runs unattended and the full unfiltered history is
#: ~3,500 rows on the price section. Measured at 2-6 s; 120 is not a budget,
#: it is a ceiling that stops a hung socket holding the lock until
#: cron-alert's ALERT_TIMEOUT kills it 90 minutes later.
TIMEOUT = 120


def _load_ca_prices():
    """
    apps/canadian_feeder_cattle/ca_prices.py, BY PATH and under a private name.

    By path because `apps/` is not a package and this runs from `deploy/`. Under
    a private name for the reason CLAUDE.md records: module names are cached
    globally, and a generic one is how a job silently binds some other copy.
    """
    path = REPO / "apps" / "canadian_feeder_cattle" / "ca_prices.py"
    spec = importlib.util.spec_from_file_location("_ca_livestock_prices", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ca_livestock_prices"] = mod
    spec.loader.exec_module(mod)
    return mod


cap = _load_ca_prices()


def _api_key() -> str:
    """
    MARS_API_KEY from the environment, which on the droplet means $DEST/.env
    sourced by run_ca_livestock.sh.

    NOT read from a file here. The wrapper owns that, so there is one place
    credentials enter and `--dry-run` on a laptop works the same way.
    """
    import os
    return os.environ.get("MARS_API_KEY", "").strip()


def fetch_section(section: str, key: str) -> list:
    """
    One section of AMS 3213, unfiltered — the whole history in one request.

    SECTIONS ARE A PATH SEGMENT, not a query parameter. The bare slug answers
    HTTP 200 with header rows and no data, which reads exactly like a report
    that has stopped publishing — the trap `direct_reports.py` documents for
    MARS and `leverage.py` for the datamart.

    No date filter, deliberately. MARS accepts several date grammars and
    SILENTLY IGNORES most of them, returning the full series while looking
    bounded (CLAUDE.md records this for `from`/`to`/`start`/`end`). Asking for
    everything and letting `bank_*` decide what is new cannot be fooled that
    way, and at ~3,500 rows it costs nothing worth saving.
    """
    sess = requests.Session()
    sess.auth = (key, "")
    url = f"{BASE}/{cap.SLUG}/{section}"
    r = sess.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json()
    rows = body.get("results") if isinstance(body, dict) else body
    return rows or []


def collect(key: str):
    """(price_rows, slaughter_rows, rejects, errors) — parsed, never re-parsed."""
    rejects, errors = [], []
    prices, slaughter = [], []
    try:
        prices = cap.parse_prices(fetch_section(cap.SECTION_PRICE, key), rejects)
    except Exception as e:
        errors.append(f"{cap.SECTION_PRICE}: {type(e).__name__}: {e}")
    try:
        slaughter = cap.parse_slaughter(fetch_section(cap.SECTION_SLAUGHTER, key), rejects)
    except Exception as e:
        errors.append(f"{cap.SECTION_SLAUGHTER}: {type(e).__name__}: {e}")
    return prices, slaughter, rejects, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and parse, print a summary, write nothing")
    args = ap.parse_args(argv)

    key = _api_key()
    if not key:
        print("MARS_API_KEY is not set — nothing would be fetched", file=sys.stderr)
        return 1

    prices, slaughter, rejects, errors = collect(key)
    for e in errors:
        print(e, file=sys.stderr)
    if errors and not (prices or slaughter):
        return 1

    week = cap.latest_week(prices) or cap.latest_week(slaughter)
    print(f"AMS {cap.SLUG}: {len(prices)} price row(s), {len(slaughter)} slaughter row(s), "
          f"newest week ending {week}")

    # REJECTIONS ARE PRINTED, NEVER COUNTED SILENTLY. A row refused for an
    # unexpected currency or unit means the feed changed shape, and on this
    # report that is the one failure that would otherwise render perfectly —
    # a Canadian-dollar price shown as US is a ~1.35x error in the right
    # column. Capped so a wholesale change does not bury the log.
    if rejects:
        print(f"{len(rejects)} row(s) rejected:", file=sys.stderr)
        for r in rejects[:10]:
            print(f"  {r}", file=sys.stderr)
        if len(rejects) > 10:
            print(f"  ... and {len(rejects) - 10} more", file=sys.stderr)

    missing = cap.missing_weeks(prices)
    if missing:
        print(f"weeks absent from the series (excluding the year-end closure): "
              f"{', '.join(f'{y}-W{w:02d}' for y, w in missing)}")

    if args.dry_run:
        for region in cap.REGIONS:
            ladder = cap.feeder_ladder(prices, region, week)
            if not any(r["Steers"] or r["Heifers"] for r in ladder):
                continue
            print(f"  {region} feeders, w/e {week} (US$/cwt):")
            for rung in ladder:
                st = f"{rung['Steers']:.2f}" if rung["Steers"] is not None else "-"
                hf = f"{rung['Heifers']:.2f}" if rung["Heifers"] is not None else "-"
                print(f"    {rung['weight_group']:>9}  steers {st:>8}  heifers {hf:>8}")
        for species in cap.SLAUGHTER_CLASSES:
            s = cap.slaughter_summary(slaughter, species, week)
            if s:
                print(f"  Canadian FI {species}: {s['head']:,.0f} head | "
                      f"YTD {s['ytd']:,.0f} vs {s['ytd_prior']:,.0f} = {s['pct_change']}%")
        print("dry run — nothing written")
        return 0

    # EVERY RUN, so a fresh host needs no manual DDL step. The portal already
    # proved the deployed identity can CREATE SCHEMA (JSA.BOXED_BEEF, first run
    # 2026-10-07), so this is not an assumption about grants — it is the same
    # capability letter/draft_store.py relied on for JSA.LETTER.
    problem = cap.ensure_table()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    rc = 0
    for label, note in (("prices", cap.bank_prices(prices)),
                        ("slaughter", cap.bank_slaughter(slaughter))):
        if note.startswith("Could not"):
            print(f"{label}: {note}", file=sys.stderr)
            rc = 1
        elif note:
            print(f"{label}: {note}")
        else:
            print(f"{label}: nothing new")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
