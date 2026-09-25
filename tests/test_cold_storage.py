"""Proof that the Cold Storage MoM/YoY arithmetic says what it claims.

Three things here would be wrong silently rather than loudly, which is why
they are pinned:

  * a missing month bridged instead of blanked, printing a 13-month change as
    a "MoM";
  * a run of months above year-ago counted through a gap, so "N straight
    months" is not straight;
  * the computed red-meat total silently becoming beef+pork+lamb for the years
    before veal starts.

The September 2026 release is used as the reference throughout — its figures
are on page 7 of cost0926.pdf and are quoted in the fixtures below.

    python -m pytest tests/test_cold_storage.py -q
"""

import os
import sys

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "apps", "cattle_on_feed"))

import cold_storage as cs  # noqa: E402


def _series(pairs):
    """[('2026-07', 398_285_000), ...] -> the frame fetch_series returns."""
    return pd.DataFrame([{"date": pd.Timestamp(m + "-01"), "value": float(v)}
                         for m, v in pairs])


def _months(start, values):
    """A run of consecutive months from `start`."""
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in values]})


# ── the grid, and the gaps in it ─────────────────────────────────────────────

def test_mom_and_yoy_match_the_september_2026_release():
    # Total beef, Aug 2025 through Aug 2026, straight off USDA's page 7:
    # 407,115 against 398,285 a month earlier and 387,127 a year earlier.
    frame = cs.monthly_frame(_months("2025-08", [
        387_127_000, 402_960_000, 414_544_000, 425_546_000, 434_602_000,
        427_337_000, 418_692_000, 406_973_000, 405_470_000, 403_048_000,
        388_879_000, 398_285_000, 407_115_000,
    ]))
    latest = cs.latest(frame)
    assert latest["date"] == pd.Timestamp("2026-08-01")
    assert latest["value"] == 407_115_000
    # USDA prints these rounded to 102 and 105 percent of prior month/year.
    assert round(latest["mom"], 1) == 2.2
    assert round(latest["yoy"], 1) == 5.2
    assert latest["mom_abs"] == 407_115_000 - 398_285_000
    assert latest["yoy_abs"] == 407_115_000 - 387_127_000


def test_a_missing_month_blanks_the_change_rather_than_bridging_it():
    frame = cs.monthly_frame(_series([("2026-01", 100), ("2026-03", 120)]))
    assert len(frame) == 3                     # Feb exists on the grid...
    assert pd.isna(frame.loc[1, "value"])      # ...with no value
    # March must NOT report +20% "month over month" against January.
    assert pd.isna(frame.loc[2, "mom"])


def test_yoy_needs_the_same_month_twelve_rows_back():
    vals = list(range(100, 125))                       # 25 consecutive months
    raw = _months("2025-01", vals)
    raw = raw.drop(index=3).reset_index(drop=True)     # lose Apr 2025
    frame = cs.monthly_frame(raw)
    apr26 = frame[frame["date"] == pd.Timestamp("2026-04-01")].iloc[0]
    assert pd.isna(apr26["yoy"])
    mar26 = frame[frame["date"] == pd.Timestamp("2026-03-01")].iloc[0]
    assert not pd.isna(mar26["yoy"])


# ── runs above year-ago ──────────────────────────────────────────────────────

def _rising(frame):
    return [(r["start"].strftime("%Y-%m"), r["end"].strftime("%Y-%m"), r["months"])
            for r in cs.yoy_runs(frame, rising=True)]


def test_runs_split_where_the_sign_flips():
    # Year one flat at 100, then up, up, down, up, up, up.
    base = [100] * 12
    frame = cs.monthly_frame(_months("2025-01", base + [110, 120, 90, 130, 140, 150]))
    assert _rising(frame) == [("2026-01", "2026-02", 2), ("2026-04", "2026-06", 3)]


def test_a_gap_breaks_a_run_even_when_the_sign_holds():
    raw = _months("2025-01", [100] * 12 + [110, 120, 130, 140])
    raw = raw.drop(index=14).reset_index(drop=True)   # lose Mar 2026
    frame = cs.monthly_frame(raw)
    # Feb and Apr are both above year-ago, but they are not consecutive, so
    # this must be two runs of one rather than one run of three.
    assert _rising(frame) == [("2026-01", "2026-02", 2), ("2026-04", "2026-04", 1)]


def test_falling_runs_are_the_complement():
    frame = cs.monthly_frame(_months("2025-01", [100] * 12 + [110, 90, 80]))
    assert [r["months"] for r in cs.yoy_runs(frame, rising=False)] == [2]


def test_no_yoy_anywhere_gives_no_runs():
    assert cs.yoy_runs(cs.monthly_frame(_months("2026-01", [1, 2, 3]))) == []


# ── the computed red meat total ──────────────────────────────────────────────

def test_red_meat_total_reproduces_usdas_printed_figure():
    # 31 Aug 2026, page 7: beef 407,115 + pork 436,269 + veal 465
    # + lamb & mutton 18,279 = total frozen red meat 862,128.
    parts = {
        "Beef, total":   _series([("2026-08", 407_115_000)]),
        "Pork, total":   _series([("2026-08", 436_269_000)]),
        "Veal":          _series([("2026-08",     465_000)]),
        "Lamb & mutton": _series([("2026-08",  18_279_000)]),
    }
    assert cs.combine(parts)["value"].iloc[0] == 862_128_000


def test_red_meat_total_covers_only_months_every_part_reports():
    parts = {
        "Beef, total":   _series([("2026-07", 1), ("2026-08", 1)]),
        "Pork, total":   _series([("2026-07", 1), ("2026-08", 1)]),
        "Veal":          _series([("2026-08", 1)]),          # starts late
        "Lamb & mutton": _series([("2026-07", 1), ("2026-08", 1)]),
    }
    out = cs.combine(parts)
    # July must be dropped, not summed as though veal were zero.
    assert list(out["date"]) == [pd.Timestamp("2026-08-01")]
    assert out["value"].iloc[0] == 4


def test_red_meat_total_is_empty_if_any_part_failed_to_load():
    parts = {
        "Beef, total":   _series([("2026-08", 1)]),
        "Pork, total":   pd.DataFrame(columns=["date", "value"]),
        "Veal":          _series([("2026-08", 1)]),
        "Lamb & mutton": _series([("2026-08", 1)]),
    }
    assert cs.combine(parts).empty


# ── catalogue ────────────────────────────────────────────────────────────────

def test_every_offered_commodity_has_a_start_year():
    for label in list(cs.SERIES) + [cs.TOTAL_RED_MEAT]:
        assert label in cs.FIRST_YEAR


def test_the_red_meat_parts_are_all_real_series():
    for part in cs.RED_MEAT_PARTS:
        assert part in cs.SERIES


@pytest.mark.parametrize("year,month,expect", [
    (2026, 9, "cost0926.pdf"),     # August stocks, released September
    (2027, 1, "cost0127.pdf"),     # December stocks, released the next January
])
def test_report_url_names_the_release_month(year, month, expect):
    assert cs.report_url(year, month).endswith(expect)


def test_empty_input_gives_an_empty_frame_not_an_exception():
    frame = cs.monthly_frame(pd.DataFrame(columns=["date", "value"]))
    assert frame.empty
    assert cs.latest(frame) == {}
