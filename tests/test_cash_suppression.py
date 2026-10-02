"""
A blank negotiated-cash volume is a zero in the 5-Area sum and not a zero
anywhere else.

USDA leaves `current_date_volume` empty both when a region had no confirmed
trade and when it is withholding the number under LMR confidentiality, and
**it never publishes a literal 0** -- zero occurrences in 2,877
region-trading-days over 2024-01-01..2026-10-02. So the field cannot say which
it is, and a 0 rendered on a region tile is always this page's own invention.

It was rendering one. TX/OK/NM has had no number since the 2026-06-26 trading
day and Kansas none since 2026-08-14, both still publishing the full Summary
skeleton with every volume blank, and both tiles read "0 head" -- which says
nobody traded in Texas for three months. The trade is real: over those weeks
the gap between LM_CT154 national confirmed negotiated and the LM_CT150 5-Area
doubled from a median 11,567 hd/wk to 23,172 hd/wk.

The 5-Area total was and remains right, which is the trap. USDA drops a
withheld region from its own aggregate exactly as a zero, so summing the four
with blanks as zero still reproduces LM_CT150's published
previous_week_head_count on 23 of 23 weeks back to April 2026. The same null
means different things in the two places, so these tests pin both.

Telling withheld from quiet is a RUN, because nothing on the day itself works
-- NEGOTIATED GRID BASE still carries a number on 90% of Iowa/Minnesota's
cash-blank days, so the "full skeleton" shape is not a signature. Measured over
2024-01-01..2026-10-02, the two are completely separable by length:

    Iowa/Minnesota   longest blank run  3
    Nebraska         longest blank run  4
    Kansas           runs of 1-4, then one run of 35 and open
    TX/OK/NM         runs of 1-4, then two runs reaching 36 and 67

Every ordinary stretch ended by day 4; every run that reached day 5 went on to
at least 35. SUPPRESSION_RUN_DAYS has to sit in that empty middle.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from streamlit_source import load_from_app  # noqa: E402

APP = ROOT / "apps" / "cash_trade" / "app.py"

# The observed bounds the threshold must clear, from the docstring above.
ORDINARY_MAX_RUN = 4      # longest blank run that was a quiet market
WITHHELD_MIN_RUN = 35     # shortest run that turned out to be suppression


@pytest.fixture(scope="module")
def ns():
    return load_from_app(
        APP, "weekly_to_date", "_null_run_days", "_trailing_blank_run",
        "and_list",
        consts=("DAILY_REGIONS", "SUPPRESSION_RUN_DAYS", "DAILY_VOLUME_PERIODS"),
        globals_={"pd": pd},
    )


def _vol(series, days=25, week_ago=None):
    """
    A /Summary volume frame shaped like fetch_daily_volume's output.

    `series` maps region -> list of week-to-date heads, newest LAST, one per
    trading day; None is USDA's blank. A region absent from `series` is absent
    from the feed entirely, which is the third case the tiles handle.
    """
    dates = list(pd.bdate_range(end="2026-10-02", periods=days))
    rows = []
    for region, heads in series.items():
        heads = [None] * (len(dates) - len(heads)) + list(heads)
        for d, h in zip(dates, heads):
            rows.append({
                "region": region, "cut": "morning", "file_date": d,
                "period": "wtd", "head": h,
                "head_week_ago": (week_ago or {}).get(region),
                "trade_date": d,
            })
    return pd.DataFrame(rows), dates[-1]


def test_a_blank_region_is_not_a_zero(ns):
    """The whole bug: USDA published nothing and the tile said 0."""
    vol, today = _vol({"Kansas": [None] * 25, "Nebraska": [3000.0] * 25})
    wtd = ns["weekly_to_date"](vol, today)
    assert wtd["Kansas"]["head"] is None
    assert wtd["Nebraska"]["head"] == 3000.0


def test_the_five_area_total_still_counts_a_blank_as_zero(ns):
    """
    USDA's own aggregate drops a withheld region, so ours must too -- this is
    the identity that reconciles on 23 of 23 weeks and it must not move.
    """
    vol, today = _vol({
        "TX/OK/NM": [None] * 25, "Kansas": [None] * 25,
        "Nebraska": [29990.0] * 25, "Iowa/Minnesota": [23331.0] * 25,
    })
    tot = ns["weekly_to_date"](vol, today)["_total"]
    assert tot["head"] == 29990.0 + 23331.0


def test_a_sustained_blank_is_reported_as_withheld(ns):
    vol, today = _vol({"Kansas": [None] * 25, "Nebraska": [3000.0] * 25})
    wtd = ns["weekly_to_date"](vol, today)
    assert wtd["Kansas"]["suppressed"] is True
    assert wtd["Nebraska"]["suppressed"] is False
    assert wtd["_total"]["withheld"] == ["Kansas"]
    assert wtd["_total"]["counted"] == ["Nebraska"]


def test_a_quiet_week_is_not_called_withheld(ns):
    """
    Nebraska's longest genuine blank run in three years is 4 days. Asserting
    confidentiality over one of those would be a wrong claim about USDA, not a
    cautious one -- so a short blank renders as a blank and says no more.
    """
    quiet = [3000.0] * (25 - ORDINARY_MAX_RUN) + [None] * ORDINARY_MAX_RUN
    vol, today = _vol({"Nebraska": quiet})
    entry = ns["weekly_to_date"](vol, today)["Nebraska"]
    assert entry["head"] is None          # still never a zero
    assert entry["suppressed"] is False   # but not accused of being withheld


def test_the_threshold_sits_inside_the_measured_gap(ns):
    """Above every quiet run, below every suppression run that was observed."""
    assert ORDINARY_MAX_RUN < ns["SUPPRESSION_RUN_DAYS"] <= WITHHELD_MIN_RUN


def test_a_window_too_short_to_judge_does_not_claim_withheld(ns):
    """
    The run is measured inside the fetched window, so a window shorter than the
    threshold cannot establish one. It must fail to "no volume published",
    never to an assertion it has not earned.
    """
    vol, today = _vol({"Kansas": [None] * 3}, days=3)
    entry = ns["weekly_to_date"](vol, today)["Kansas"]
    assert entry["head"] is None
    assert entry["suppressed"] is False


def test_a_number_anywhere_in_the_run_resets_it(ns):
    """A single print breaks the run -- the region is publishing again."""
    vol, today = _vol({"Kansas": [None] * 12 + [1500.0] + [None] * 12})
    assert ns["_null_run_days"](vol, "Kansas", today) == 12
    assert ns["weekly_to_date"](vol, today)["Kansas"]["suppressed"] is True

    vol, today = _vol({"Kansas": [None] * 20 + [1500.0] + [None] * 4})
    assert ns["_null_run_days"](vol, "Kansas", today) == 4
    assert ns["weekly_to_date"](vol, today)["Kansas"]["suppressed"] is False


def test_the_final_cut_wins_over_the_one_thirty_cut_in_the_run(ns):
    """
    weekly_to_date prefers the morning (final) figure, so the run has to be
    measured on the same series the tile shows -- otherwise a region whose
    1:30 cut is blank but whose final print lands reads as withheld.
    """
    vol, today = _vol({"Kansas": [None] * 25})
    aft = vol.copy()
    aft["cut"] = "afternoon"
    aft["head"] = aft["head"].astype("float64")   # all-NA object column
    mor = vol.copy()
    mor["head"] = 2000.0
    both = pd.concat([aft, mor], ignore_index=True)
    assert ns["_null_run_days"](both, "Kansas", today) == 0
    assert ns["weekly_to_date"](both, today)["Kansas"]["suppressed"] is False


def test_a_region_absent_from_the_feed_is_not_a_blank_one(ns):
    """
    Three states, not two: never published, published blank, published a
    number. The first already had a branch and must keep it.
    """
    vol, today = _vol({"Kansas": [None] * 25, "Nebraska": [3000.0] * 25})
    wtd = ns["weekly_to_date"](vol, today)
    assert "TX/OK/NM" not in wtd
    assert wtd["Kansas"]["head"] is None


def test_week_ago_is_untouched_by_a_blank(ns):
    vol, today = _vol({"Nebraska": [3000.0] * 25, "Kansas": [None] * 25},
                      week_ago={"Nebraska": 2500.0})
    wtd = ns["weekly_to_date"](vol, today)
    assert wtd["Nebraska"]["week_ago"] == 2500.0
    assert wtd["Kansas"]["week_ago"] is None
    assert wtd["_total"]["week_ago"] == 2500.0


def test_and_list(ns):
    f = ns["and_list"]
    assert f([]) == ""
    assert f(["Kansas"]) == "Kansas"
    assert f(["Kansas", "TX/OK/NM"]) == "Kansas and TX/OK/NM"
    assert f(["a", "b", "c"]) == "a, b and c"
