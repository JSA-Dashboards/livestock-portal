#!/usr/bin/env python3
"""
Mirror USDA NW_LS421 Frozen 90s import prices into Snowflake. For the droplet.

WHY THIS EXISTS, AND WHY IT IS IN THE REPOSITORY. `marsapi.ams.usda.gov`
rejects Streamlit Community Cloud's IPs, so the Beef Trimmings import series is
fetched on a droplet and the page reads the Snowflake mirror. Until 2026-10-07
the fetching half existed ONLY on that droplet, in a script in no repository --
the reader was committed, the writer was not, and a rebuilt host would have
lost it with nothing to rebuild it from.

IT IMPORTS THE PAGE'S FETCHER, IT DOES NOT REIMPLEMENT IT.
`apps/beef_trimmings/import_cow90.py` is loaded from this checkout, so the cron
and the page can never disagree about what NW_LS421 says. A second copy of a
parser running unattended, where nobody would see it drift, is the
`snowflake_db.py`-times-five problem with no renderer to catch it. A test
asserts this file defines no fetch or parse of its own.

DAILY, NOT WEEKLY, AND THAT IS THE FIX IT SHIPPED FOR. The old schedule ran
weekly against a weekly publication, which leaves no slack: USDA posted the
2026-10-02 report after the 10-05 run, so the page sat on 09-25 data for a week
with nothing wrong anywhere. A daily sweep costs one request and rewrites the
same rows. There is no holiday calendar to maintain either -- on a day USDA
publishes nothing the fetch returns the same series and the rewrite is a no-op
in content.

Exit codes: 0 written, 1 could not fetch or could not write. Cron mails stderr
on a non-zero exit, which is the whole alerting story.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(path: Path, name: str):
    if not path.exists():
        raise SystemExit(f"{path} is missing -- is this a full checkout?")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_import_cow90():
    return _load(REPO / "apps" / "beef_trimmings" / "import_cow90.py",
                 "_cron_import_cow90")


def _load_db():
    """snowflake_db.py by path under a private name, never by bare import.

    CLAUDE.md records that file existing five times in this repo and resolving
    by whichever page loaded first. A cron binding whichever copy happens to be
    importable, unattended, is exactly the thing not to add.
    """
    return _load(REPO / "apps" / "mexican_feeder_imports" / "snowflake_db.py",
                 "_cron_cow90_db")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mirror NW_LS421 into Snowflake.")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and summarise, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="write even if the series has shrunk (see bank())")
    args = ap.parse_args(argv)

    key = os.environ.get("MARS_API_KEY", "").strip()
    if not key:
        print("MARS_API_KEY is not set", file=sys.stderr)
        return 1

    ic = _load_import_cow90()
    try:
        df = ic.fetch_live(key)
    except Exception as e:
        print(f"could not fetch NW_LS421: {e}", file=sys.stderr)
        return 1

    if df.empty:
        print("NW_LS421 returned no Cow Meat (90%) rows", file=sys.stderr)
        return 1

    newest = df["report_date"].max()
    print(f"fetched {len(df)} rows, {df['report_date'].nunique()} weeks, "
          f"newest {newest:%Y-%m-%d}")
    for origin, sub in df.groupby("origin"):
        print(f"   {origin:<16} {len(sub):>4} weeks, newest "
              f"{sub['report_date'].max():%Y-%m-%d} at {sub.iloc[-1]['avg_price']:.2f}")

    if args.dry_run:
        return 0

    conn = _load_db().get_conn()
    try:
        err = ic.ensure_table(conn)
        if err:
            print(err, file=sys.stderr)
            return 1
        n, err = ic.bank(conn, df, force=args.force)
        if err:
            print(err, file=sys.stderr)
            return 1
        print(f"wrote {n} rows")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
