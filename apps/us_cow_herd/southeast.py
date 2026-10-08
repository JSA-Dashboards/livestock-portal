"""
The same retention incentive, measured at five southeastern barns back to 2008.

WHY A SECOND PANEL EXISTS AT ALL. The twelve markets behind the main chart --
Joplin, OKC West, Oklahoma National, Woodward, Ozarks, Springfield, Ada, Tina,
Salina, Palmyra, Billings -- did not report a bred cow to USDA before 2019.
That is not a gap to be filled: in the whole legacy auction archive, 2000-2019,
bred-cow rows run GA 34,864 / KY 25,991 / NC 16,094 / SC 15,480 / TN 13,141 and
**zero Oklahoma, zero Missouri, zero Texas**. There is no file to load. 2019 is
the floor for the plains and always will be.

Bred cows WERE reported in the southeast throughout, so a long series is
available there -- at different barns, for different cattle.

THE TWO PANELS MUST NOT SHARE AN AXIS, and that is the whole reason this is a
separate view rather than eleven more bars on the existing chart. The
southeast-to-plains offset is tight over 2019-2026 (about +0.25, sd 0.013) and
looks eminently subtractable. It is not: the one pre-2019 plains-versus-
southeast comparison that can actually be run has that offset wandering from
+0.085 to +0.312, which is wider than the plains series' entire modern range of
0.247. Calibrating a shift on the recent years and extrapolating it backwards
was tested inside the legacy archive on ten matched state pairs: median
back-window error 0.092, maximum 0.264. A small calibration-window sd does not
buy out-of-window stability. So this line is drawn on its own baseline, against
its own normal, and no number here is ever added to a plains number.

WHAT IT IS GOOD FOR. Not a level, a shape. Over the overlap the two panels move
together at first-difference r=0.964, and the long view answers the question the
plains series cannot reach: 2010-2012 was the trough of the whole record, and
2015-2016 ran above today.

HOW THE SERIES IS BUILT, and why it is a file rather than a query. The 2008-2018
half comes from the USDA legacy auction archive, two zips totalling about 960MB
of CSV -- far too much to parse on a page load, and a static archive that will
never gain a row. It is precomputed into data/southeast_retention.json by
scripts/build_southeast_retention.py and read from there. The 2019-2026 half is
MARS, recomputed by the same script.

Three things in the build that look wrong and are not:

- **The legacy archive has no price-unit column**, and quotes bred cows per cwt
  at some barns and per head at others IN THE SAME YEAR, with SELLING_BASIS
  reading "Live" on every row either way. The split is cleanly bimodal --
  20,491 rows under $250, 78 between $250 and $300, 104,583 above -- so the
  threshold is a fact rather than a judgement, and moving it between 250 and 300
  changes any annual ratio by at most 0.002. Read naively, 2002-2007 computes to
  about 0.11 instead of 1.1: a factor of ten that looks like a market collapse,
  raises nothing, and charts plausibly.
- **The two sources are concatenated, not spliced**, because they do not
  overlap. Legacy's last bred sale at these barns falls 2019-04-15..04-29 and
  MARS's first 2019-04-22..05-08, with **zero shared barn-dates** -- verified on
  every build. There is nothing to double-count and no seam to calibrate.
- **The legacy archive has no `Bred Heifers` class at all**, while MARS carries
  it (15-21% of bred head, priced about 16% above bred cows). The pre-2019 half
  is therefore a slightly narrower definition than the post-2019 half. It is
  left that way rather than dropping Bred Heifers from the modern side, because
  the alternative is discarding real data to match an archive's omission -- but
  it is a reason to read the join as approximate in level even though it is
  exact in dates.

2007 and earlier are deliberately absent: coverage thins to two months at these
barns, and `MIN_MONTHS` drops it.
"""
import json
from pathlib import Path
from statistics import median

DATA = Path(__file__).parent / "data" / "southeast_retention.json"

# A year needs this many distinct months to be drawn, the same rule
# herd.MIN_ANNUAL_MONTHS applies to the plains panel.
MIN_MONTHS = 6

# Bump when the JSON's shape changes -- app.py passes it into the cached loader
# so st.cache_data notices, the trap recorded for leverage.SCHEMA.
SCHEMA = 1

# Matches herd.BASELINE_YEARS so "normal" means the same span on both panels.
# The VALUE is computed from this panel's own years and is nothing like the
# plains figure -- see the module note on why the two never share a baseline.
BASELINE_YEARS = (2021, 2025)


def load():
    """{'panel': [barn names], 'series': [{year, ratio, n, months, barns, source}]}

    Returns None rather than raising if the file is missing, so a packaging
    slip costs the toggle and not the page.
    """
    try:
        d = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return None
    rows = [r for r in d.get("series", []) if r.get("months", 0) >= MIN_MONTHS]
    if not rows:
        return None
    d["series"] = sorted(rows, key=lambda r: r["year"])
    return d


def baseline(series):
    """This panel's own normal, over BASELINE_YEARS."""
    v = [r["ratio"] for r in series
         if BASELINE_YEARS[0] <= r["year"] <= BASELINE_YEARS[1]]
    return median(v) if v else None


def span(series):
    """('Jan','Oct') for a trailing part year, else None -- as herd.annual_span."""
    if not series:
        return None
    last = series[-1]
    if last.get("months", 0) >= 12:
        return None
    return last.get("span")
