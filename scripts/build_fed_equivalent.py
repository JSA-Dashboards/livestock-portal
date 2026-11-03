"""Precompute the annual fed-cattle history the Cattle Equivalent tab reaches back into.

WHY A FROZEN FILE RATHER THAN A FETCH. The shared NASS cache (usda-nass-etl)
holds this page's weekly slaughter for the last eight years only -- the ETL is
keyed per year and `LOAD_YEARS` is `current_year - 7`. The tab offers baselines
older than that (2015 is the last herd low, and the whole point of the panel is
to set today against it), so the years before the live window have to come from
somewhere else.

They are CLOSED. A completed year's fed slaughter and carcass weight gain one
more revision at most and then never move again, so freezing them costs nothing
and buys a baseline the live cache cannot reach. Same shape, and the same
reasoning, as `apps/us_cow_herd/data/southeast_legacy.json`.

WHAT IS *NOT* FROZEN, DELIBERATELY:

  * **Fed marketings.** The cattle-on-feed ETL caches that series unfiltered and
    in full -- 1995 to date, monthly, every state and capacity class -- so the
    page reads it live for every year including the running one. Freezing a copy
    would be a second number for one quantity, which is the failure this repo's
    CLAUDE.md records five times over.
  * **Anything from the live window.** The frozen file stops at
    `LIVE_FROM - 1` so there is exactly one source per year and no overlap to
    reconcile. `tests/test_fed_equivalent.py` asserts the boundary holds in both
    directions, and separately that the frozen years agree with NASS's own
    annual series to the pound.

SOURCE: the NASS QuickStats bulk dump, which needs NO API KEY --
`https://www.nass.usda.gov/datasets/qs.animals_products_<YYYYMMDD>.txt.gz`,
regenerated daily, ~464 MB. The filename carries the date and there is no
stable "latest" alias, so the directory listing is scraped rather than guessed.
Streamed and filtered rather than saved: this script never writes the archive
to disk.

THE WEIGHT IS HEAD-WEIGHTED ACROSS STEERS AND HEIFERS, NEVER A SIMPLE MEAN OF
THE TWO. Steers outnumber heifers about 3:2 and carry an 80-plus pound heavier
carcass, so averaging the two class figures unweighted runs the fed carcass
about 15 lb light -- a plausible number, in the denominator of every
head-equivalent on the page.

Usage:
    python scripts/build_fed_equivalent.py            # write the JSON
    python scripts/build_fed_equivalent.py --dry-run  # print, write nothing
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

DATASETS = "https://www.nass.usda.gov/datasets/"
OUT = Path(__file__).resolve().parents[1] / "apps" / "beef_weight" / "data" / "fed_equivalent.json"

# The first year the shared NASS cache serves weekly data for this page. Years
# from here on are read live and MUST NOT appear in the frozen file.
LIVE_FROM = 2019
FIRST_YEAR = 1996  # fed marketings start 1995; 1996 is the first full year

# Bulk-dump column positions (0-based). Documented in the project memory note
# "NASS bulk dump for series discovery"; re-derived from the header here anyway
# so a column insert upstream fails loudly instead of silently shifting.
COLS = {
    "SOURCE_DESC": 0, "COMMODITY_DESC": 3, "STATISTICCAT_DESC": 7,
    "SHORT_DESC": 9, "AGG_LEVEL_DESC": 12, "YEAR": 30,
    "REFERENCE_PERIOD_DESC": 34, "VALUE": 37,
}

STEER_HEAD = "CATTLE, STEERS, SLAUGHTER, COMMERCIAL, FI - SLAUGHTERED, MEASURED IN HEAD"
STEER_CWT = ("CATTLE, STEERS, SLAUGHTER, COMMERCIAL, FI - SLAUGHTERED, "
             "MEASURED IN LB / HEAD, DRESSED BASIS")
HEIFER_HEAD = "CATTLE, HEIFERS, SLAUGHTER, COMMERCIAL, FI - SLAUGHTERED, MEASURED IN HEAD"
HEIFER_CWT = ("CATTLE, HEIFERS, SLAUGHTER, COMMERCIAL, FI - SLAUGHTERED, "
              "MEASURED IN LB / HEAD, DRESSED BASIS")
WANTED = {STEER_HEAD: "str_h", STEER_CWT: "str_w",
          HEIFER_HEAD: "hfr_h", HEIFER_CWT: "hfr_w"}


def latest_dump_name() -> str:
    with urllib.request.urlopen(DATASETS, timeout=120) as r:
        listing = r.read().decode("utf-8", "replace")
    names = sorted(set(re.findall(r"qs\.animals_products_\d{8}\.txt\.gz", listing)))
    if not names:
        raise SystemExit("no qs.animals_products_*.txt.gz in the NASS directory listing")
    return names[-1]


def _check_header(header: list[str]) -> None:
    for name, idx in COLS.items():
        if idx >= len(header) or header[idx] != name:
            got = header[idx] if idx < len(header) else "<past end>"
            raise SystemExit(
                f"bulk dump layout changed: column {idx} is {got!r}, expected {name!r}. "
                "Re-derive COLS before trusting any figure from this run."
            )


def harvest(name: str) -> dict[int, dict[str, float]]:
    """Stream the dump and pull the four national annual fed series."""
    url = DATASETS + name
    rows: dict[int, dict[str, float]] = {}
    with urllib.request.urlopen(url, timeout=1800) as resp:
        with gzip.open(resp, mode="rt", encoding="utf-8", errors="replace") as fh:
            reader = csv.reader(fh, delimiter="\t")
            _check_header(next(reader))
            for row in reader:
                if len(row) <= COLS["VALUE"]:
                    continue
                if (row[COLS["COMMODITY_DESC"]] != "CATTLE"
                        or row[COLS["AGG_LEVEL_DESC"]] != "NATIONAL"
                        or row[COLS["SOURCE_DESC"]] != "SURVEY"
                        or row[COLS["REFERENCE_PERIOD_DESC"]] != "YEAR"):
                    continue
                key = WANTED.get(row[COLS["SHORT_DESC"]])
                if key is None:
                    continue
                raw = row[COLS["VALUE"]].replace(",", "").strip()
                if not raw or not raw[0].isdigit():
                    continue  # (D) withheld, (NA), (Z) -- never coerce to zero
                rows.setdefault(int(row[COLS["YEAR"]]), {})[key] = float(raw)
    return rows


def build(rows: dict[int, dict[str, float]], lo: int, hi: int) -> dict:
    """Head-weighted annual fed figures for years in [lo, hi)."""
    out = {}
    for year in sorted(rows):
        if year < lo or year >= hi:
            continue
        r = rows[year]
        if len(r) != 4:
            # A year missing one class cannot produce a head-weighted average.
            # Skipping beats averaging the classes that happen to be present,
            # which yields a fed carcass weight for a different population.
            print(f"  skip {year}: have {sorted(r)}, need all four", file=sys.stderr)
            continue
        head = r["str_h"] + r["hfr_h"]
        beef = r["str_h"] * r["str_w"] + r["hfr_h"] * r["hfr_w"]
        out[str(year)] = {
            "fed_head": round(head),
            "fed_carcass_lb": round(beef / head, 2),
            "steer_head": round(r["str_h"]), "steer_carcass_lb": r["str_w"],
            "heifer_head": round(r["hfr_h"]), "heifer_carcass_lb": r["hfr_w"],
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    name = latest_dump_name()
    print(f"streaming {name} ...", file=sys.stderr)
    rows = harvest(name)
    data = build(rows, FIRST_YEAR, LIVE_FROM)

    # NASS's own annual figures for the years the page reads LIVE. The page
    # must never touch these -- a second source for a year it already has is
    # the failure this file's own docstring warns about. They exist so
    # tests/test_fed_equivalent.py can check that aggregating the live weekly
    # series reproduces USDA's annual number, which is otherwise untestable:
    # the frozen history stops exactly where the live window begins, so there
    # is no overlap anywhere else to compare.
    check = build(rows, LIVE_FROM, max(rows) + 1)

    years = sorted(int(y) for y in data)
    if not years:
        raise SystemExit("no complete years harvested -- refusing to write")
    # Contiguity is the cheap guard that a parse hole did not silently drop a
    # year a baseline selector would then offer and fail to find.
    missing = [y for y in range(years[0], years[-1] + 1) if str(y) not in data]
    if missing:
        raise SystemExit(f"gap in the frozen history at {missing} -- refusing to write")
    if years[-1] >= LIVE_FROM:
        raise SystemExit(f"frozen history reaches {years[-1]}, the live window starts {LIVE_FROM}")

    payload = {
        "_source": f"USDA NASS QuickStats bulk dump {name}",
        "_note": ("`years` is complete years only, ending before the live weekly "
                  "window; it is what the page reads. `check_years` covers the "
                  "LIVE window and is for tests alone -- the page must never "
                  "read it, or a year would have two sources."),
        "live_from": LIVE_FROM,
        "years": data,
        "check_years": check,
    }
    text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    print(f"{len(years)} years, {years[0]}-{years[-1]}", file=sys.stderr)
    for y in (years[0], years[-1]):
        d = data[str(y)]
        print(f"  {y}: fed head {d['fed_head']:,}  carcass {d['fed_carcass_lb']:.1f} lb",
              file=sys.stderr)
    if args.dry_run:
        print(text)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
