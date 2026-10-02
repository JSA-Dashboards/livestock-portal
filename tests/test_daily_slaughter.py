"""Proof that the Saturday slaughter view reads AMS 3208 the way it claims.

Four things here would be wrong silently rather than loudly:

  * Friday's Saturday PROJECTION left in place of Monday's restated figure,
    freezing every Saturday at its forecast -- the series would still look
    perfectly reasonable, just low, because Saturdays revise UP;
  * a Saturday quoted without the week it sat in, which cannot distinguish a
    sixth day bought on margin from one buying back a holiday Monday;
  * a partial week at the edge of the feed scored as though it were whole;
  * the reconcile against AMS's own week_to_date silently passing because it
    compares nothing.

The real 2026-09-07 Labor Day week is the reference throughout: Monday 2,000
head, then 109/109/109/106 thousand, then a 70,000 Saturday, for a 505,000
week -- the largest Saturday on file and the one that makes the point.

    python -m pytest tests/test_daily_slaughter.py -q
"""

import os
import sys
from datetime import date, timedelta

import pytest

# This file is shared verbatim with the beef-weight-dashboard repo, where the
# module sits at the repo root rather than under apps/beef_weight -- so both
# layouts are tried rather than hardcoding the portal's. Listed in SHARED in
# cme-feeder-cattle-index/tests/test_no_drift.py.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _rel in (("..", "apps", "beef_weight"), ("..",)):
    _cand = os.path.join(_HERE, *_rel)
    if os.path.isfile(os.path.join(_cand, "daily_slaughter.py")):
        sys.path.insert(0, _cand)
        break

import daily_slaughter as ds  # noqa: E402


def _row(day, head, report_date, period="Current", wtd=None):
    return {"day": day, "head": head, "report_date": report_date,
            "period": period, "revision": "No",
            "week_to_date": wtd, "year_ago": None}


def _labor_day_week():
    """The real week of 2026-09-07, as report 3208 served it.

    Saturday appears TWICE: as Friday's projection and again in Monday's
    report. Both carry 70,000 here because that Saturday was not revised; the
    revision case is its own test below.
    """
    mon = date(2026, 9, 7)
    heads = [2_000, 109_000, 109_000, 109_000, 106_000, 70_000]
    rows, running = [], 0
    for i, h in enumerate(heads):
        d = date(2026, 9, 7 + i)
        running += h
        # each day is reported on the day itself, then restated the next
        rows.append(_row(d, h, d, "Current", running))
        if i < 5:
            rows.append(_row(d, h, date(2026, 9, 8 + i), "Previous", running))
    # Monday's report restates Saturday
    rows.append(_row(date(2026, 9, 12), 70_000, date(2026, 9, 14), "Previous", 505_000))
    return {"rows": rows, "published": date(2026, 9, 14)}, mon


# ── the dedupe ───────────────────────────────────────────────────────────────

def test_latest_report_date_wins_so_a_projection_is_replaced():
    """A Saturday revised UP must end at the revised figure, not the forecast.

    2024-11-30 really did go 39,000 -> 47,000 overnight. Taking the first row,
    or trusting period=="Current", would keep 39,000 and never raise.
    """
    raw = {"rows": [
        _row(date(2024, 11, 30), 39_000, date(2024, 11, 29), "Current", 528_000),
        _row(date(2024, 11, 30), 47_000, date(2024, 12, 2), "Previous", 536_000),
    ], "published": date(2024, 12, 2)}

    df = ds.daily_frame(raw)
    assert len(df) == 1
    assert int(df.iloc[0]["head"]) == 47_000


def test_newest_days_are_marked_as_unsettled():
    """Today and anything after it are forecasts; earlier days are not."""
    raw = {"rows": [
        _row(date(2026, 10, 1), 109_000, date(2026, 10, 2), "Previous", 410_000),
        _row(date(2026, 10, 2), 100_000, date(2026, 10, 2), "Current", 510_000),
        _row(date(2026, 10, 3), 38_000, date(2026, 10, 2), "Current", 548_000),
    ], "published": date(2026, 10, 2)}

    df = ds.daily_frame(raw).set_index("day")
    assert not df.loc[date(2026, 10, 1), "is_projection"]
    assert df.loc[date(2026, 10, 2), "is_projection"]
    assert df.loc[date(2026, 10, 3), "is_projection"]


# ── the week a Saturday sat in ───────────────────────────────────────────────

def test_labor_day_saturday_carries_its_week():
    raw, _ = _labor_day_week()
    sats = ds.saturday_frame(ds.daily_frame(raw))

    assert len(sats) == 1
    r = sats.iloc[0]
    assert r["day"] == date(2026, 9, 12)
    assert int(r["head"]) == 70_000
    assert int(r["week_total"]) == 505_000
    assert int(r["week_low"]) == 2_000
    assert r["lost_day"] is True or bool(r["lost_day"])
    assert round(r["sat_share"], 4) == round(70_000 / 505_000, 4)


def test_a_full_week_is_not_flagged_as_holiday():
    """The week of 2026-09-28 -- the reason the Oct 3 Saturday is unusual.

    Same shape, no lost day, so `lost_day` must stay False. If the threshold
    ever drifts up far enough to catch an ordinary slow Monday, the view would
    explain away exactly the Saturday worth noticing.
    """
    heads = [95_000, 108_000, 98_000, 109_000, 100_000, 38_000]
    rows, running = [], 0
    for i, h in enumerate(heads):
        d = date(2026, 9, 28) + timedelta(days=i)   # this week crosses into October
        running += h
        rows.append(_row(d, h, date(2026, 10, 2), "Current", running))
    sats = ds.saturday_frame(ds.daily_frame({"rows": rows, "published": date(2026, 10, 2)}))

    r = sats.iloc[0]
    assert not r["lost_day"]
    assert int(r["week_total"]) == 548_000


def test_partial_week_is_dropped_not_scored():
    """A week missing weekdays must not produce a Saturday row at all.

    Scoring it would divide a real Saturday by a short week and print an
    invented share -- the feed's first and last weeks are both like this.
    """
    rows = [
        _row(date(2026, 9, 10), 109_000, date(2026, 9, 10), "Current", 109_000),
        _row(date(2026, 9, 11), 106_000, date(2026, 9, 11), "Current", 215_000),
        _row(date(2026, 9, 12), 70_000, date(2026, 9, 14), "Previous", 285_000),
    ]
    sats = ds.saturday_frame(ds.daily_frame({"rows": rows, "published": date(2026, 9, 14)}))
    assert sats.empty


# ── "when did we last do this" ───────────────────────────────────────────────

def test_at_or_above_excludes_the_day_being_asked_about():
    """A Saturday must never count as its own precedent."""
    import pandas as pd
    sats = pd.DataFrame([
        {"day": date(2024, 11, 30), "head": 47_000, "lost_day": True},
        {"day": date(2026, 9, 12),  "head": 70_000, "lost_day": True},
        {"day": date(2026, 10, 3),  "head": 38_000, "lost_day": False},
    ])
    hits = ds.at_or_above(sats, 38_000, before=date(2026, 10, 3))
    assert list(hits["day"]) == [date(2024, 11, 30), date(2026, 9, 12)]
    assert date(2026, 10, 3) not in list(hits["day"])


# ── the audit ────────────────────────────────────────────────────────────────

def test_reconcile_catches_a_week_that_does_not_sum():
    """The guard has to actually compare, not pass vacuously."""
    raw, _ = _labor_day_week()
    df = ds.daily_frame(raw)
    assert ds.reconcile(df, raw) == []          # the real week balances

    # bend one weekday; the Saturday's reported WTD no longer matches
    df.loc[df["day"] == date(2026, 9, 8), "head"] = 999_000
    bad = ds.reconcile(df, raw)
    assert len(bad) == 1
    assert bad[0][2] == 505_000                 # AMS's figure is the reference


# ── failure is reported, never raised ────────────────────────────────────────

def test_a_missing_key_is_an_error_string_not_an_exception():
    """The caller is a dashboard view: a dead feed says so, it does not blank."""
    out = ds.fetch("")
    assert "MARS_API_KEY" in out["error"]
    assert ds.daily_frame(out).empty
    assert ds.saturday_frame(ds.daily_frame(out)).empty
