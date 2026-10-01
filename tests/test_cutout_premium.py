"""
The cutout premium line: what it measures, and the short-week trap.

The newest week is almost always SHORT -- it is only as long as the market
has traded so far. Averaging those few days against full five-day weeks in
every base year compares a partial week with complete ones, and it lands on
the single point the chart labels. On 2026-10-01 that overstated the premium
by 0.75 $/cwt (81.88 against a like-for-like 81.13), and seven of the 52
plotted weeks were short for holidays besides.

Nothing raises, the line looks plausible, and the error is largest exactly
where a reader looks first.
"""
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from letter import sources  # noqa: E402


def _series(rows):
    """rows: {date: value} -> the shape fetch_cutout_history returns."""
    idx = [d for d in rows]
    return pd.Series([rows[d] for d in idx], index=idx, dtype=float)


def _weekdays(year, week, days):
    return [dt.date.fromisocalendar(year, week, d) for d in days]


WEEKS = [35, 36, 37, 38, 39, 40]       # the series needs >= 5 points to render


def _build(current_days, current_val, base_mon_wed, base_thu_fri, years=5):
    """
    Six ISO weeks in the current year and the same six in five base years.

    Only the LAST week takes `current_days`; the earlier ones are full, so the
    fixture isolates the short-newest-week case rather than making every point
    partial. The base years are deliberately given a DIFFERENT level on Thu/Fri
    from Mon/Wed, so a full-week average and a Mon-Wed average cannot coincide
    -- which is what makes the bug visible at all.
    """
    rows = {}
    for w in WEEKS:
        days = current_days if w == WEEKS[-1] else [1, 2, 3, 4, 5]
        for d in _weekdays(2026, w, days):
            rows[d] = current_val
        for n in range(1, years + 1):
            for d in _weekdays(2026 - n, w, [1, 2, 3]):
                rows[d] = base_mon_wed
            for d in _weekdays(2026 - n, w, [4, 5]):
                rows[d] = base_thu_fri
    return _series(dict(sorted(rows.items())))


def test_a_short_current_week_is_compared_like_for_like(monkeypatch):
    """
    Mon-Wed of this year against Mon-Wed of the base years, not their full week.

    Base years run 100 Mon-Wed and 200 Thu-Fri, so the full-week mean is 140
    and the Mon-Wed mean is 100. With the current week holding only Mon-Wed at
    150, the honest premium is +50. Taking the full-week baseline would give
    +10 -- wrong by the entire Thu/Fri step.
    """
    data = _build(current_days=[1, 2, 3], current_val=150.0,
                  base_mon_wed=100.0, base_thu_fri=200.0)
    monkeypatch.setattr(sources, "fetch_cutout_history", lambda reports=1700: data)

    out = sources.cutout_premium_series(weeks=len(WEEKS))
    assert out["values"][-1] == 50.0, (
        f"got {out['values'][-1]} -- a partial week was measured against full ones"
    )


def test_a_full_current_week_still_uses_the_whole_base_week(monkeypatch):
    """The correction must not change the complete-week case."""
    data = _build(current_days=[1, 2, 3, 4, 5], current_val=150.0,
                  base_mon_wed=100.0, base_thu_fri=200.0)
    monkeypatch.setattr(sources, "fetch_cutout_history", lambda reports=1700: data)

    out = sources.cutout_premium_series(weeks=len(WEEKS))
    # base full-week mean = (100*3 + 200*2)/5 = 140
    assert out["values"][-1] == 10.0, out["values"][-1]


def test_a_base_year_missing_those_weekdays_drops_the_point(monkeypatch):
    """
    ALL FIVE OR NONE survives the change.

    An average over four of the five years is a different statistic wearing
    the same label, and restricting to weekdays must not quietly relax it.
    """
    data = _build(current_days=[1, 2, 3], current_val=150.0,
                  base_mon_wed=100.0, base_thu_fri=200.0)
    # strip Mon-Wed of ONE base year in the newest week only
    drop = set(_weekdays(2021, WEEKS[-1], [1, 2, 3]))
    data = data[[d not in drop for d in data.index]]
    monkeypatch.setattr(sources, "fetch_cutout_history", lambda reports=1700: data)

    out = sources.cutout_premium_series(weeks=len(WEEKS))
    # That POINT goes; the earlier weeks are untouched and still render.
    last_week_monday = dt.date.fromisocalendar(2026, WEEKS[-1], 1)
    assert last_week_monday not in out["dates"], (
        "a four-year average was passed off as a five-year one"
    )
    assert len(out["dates"]) == len(WEEKS) - 1


def test_the_title_says_premium_not_vs(monkeypatch):
    """
    The line is the SPREAD. "Choice cutout vs 5-yr avg" read as though the
    cutout itself were plotted, so 81.88 looked wrong beside a 382 cutout --
    reported 2026-10-01.
    """
    data = _build(current_days=[1, 2, 3, 4, 5], current_val=150.0,
                  base_mon_wed=100.0, base_thu_fri=200.0)
    monkeypatch.setattr(sources, "fetch_cutout_history", lambda reports=1700: data)

    title = sources.cutout_premium_series(weeks=len(WEEKS))["title"].lower()
    assert "premium" in title
    assert "cutout vs" not in title
