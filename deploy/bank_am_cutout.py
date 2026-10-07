#!/usr/bin/env python3
"""
Record USDA's morning boxed beef cutout. For the droplet's crontab.

WHY THIS EXISTS. LM_XB402 is published once each weekday morning and then
**overwritten in place** -- USDA keeps no archive of it and no API serves it
(see apps/beef_cutout/am_cutout.py, which records the probes). The Beef Cutout
page banks it opportunistically, but Streamlit Community Cloud has no
scheduler, so the series only fills on days somebody opens the page after the
release. This closes those holes.

IT IMPORTS THE PAGE'S PARSER, IT DOES NOT REIMPLEMENT IT. `am_cutout.py` is
loaded from this checkout, so the cron and the page can never disagree about
what a morning report says. That matters more here than it looks: CLAUDE.md
records `snowflake_db.py` existing five times in this repo and the quiet
trouble that causes. A sixth copy of a PDF parser, running unattended where
nobody would see it drift, is exactly the thing not to create.

IT IS IDEMPOTENT, AND THAT IS LOAD-BEARING. `am_cutout.bank()` inserts only
when the report date is absent or its figures have changed, so running this
ten times a day costs ten PDF fetches and writes one row. Two things follow,
and both are why the crontab below is a blunt hourly sweep rather than one
precise time:

  * **No DST arithmetic.** USDA publishes on Central time and droplets run on
    UTC, so a single pinned minute is wrong for half the year unless someone
    remembers to move it. An hourly window spans the shift.
  * **No calendar.** On a weekend or a federal holiday USDA publishes nothing
    and the PDF still serves the previous session's report -- which is already
    banked, so the run is a no-op. There is no holiday list to maintain and
    none to get wrong.

Exit codes: 0 banked or already present, 1 could not fetch or could not write.
Cron mails stderr on a non-zero exit, which is the whole alerting story.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_am_cutout():
    """apps/beef_cutout/am_cutout.py, by path, under a private name."""
    path = REPO / "apps" / "beef_cutout" / "am_cutout.py"
    if not path.exists():
        raise SystemExit(f"{path} is missing -- is this a full checkout?")
    spec = importlib.util.spec_from_file_location("_cron_am_cutout", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cron_am_cutout"] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and print, write nothing. Use this first on a new host.")
    args = ap.parse_args(argv)

    am = _load_am_cutout()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    row = am.fetch_am()
    if row.get("error"):
        print(f"{stamp} FAIL  {row['error']}", file=sys.stderr)
        return 1

    desc = (f"{row['report_date']} Choice {row['choice']:.2f} "
            f"({row['change_choice']:+.2f}) Select {row['select']:.2f} "
            f"({row['change_select']:+.2f})")

    if args.dry_run:
        print(f"{stamp} DRY   {desc}")
        return 0

    if not am.enabled():
        print(f"{stamp} FAIL  USE_SNOWFLAKE is unset -- nothing would be recorded.",
              file=sys.stderr)
        return 1

    # ensure_table() is safe to call every run and is what makes a fresh host
    # work with no manual DDL step.
    err = am.ensure_table()
    if err:
        print(f"{stamp} FAIL  {err}", file=sys.stderr)
        return 1

    result = am.bank(row)
    if result == "banked":
        print(f"{stamp} OK    banked {desc}")
        return 0
    if result == "":
        print(f"{stamp} OK    already recorded {desc}")
        return 0
    print(f"{stamp} FAIL  {result}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
