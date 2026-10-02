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

The PRICE tiles one row up had the identical defect and the identical cause.
They read "Undefined / no confirmed trade" for the same two regions, which
publish all 8 negotiated Steer/Heifer rows with head AND price both blank.
"Undefined" is USDA's own market-test word and stays for a region that reported
and did not trade; it is wrong for one that was not allowed to report.

Telling withheld from quiet is a RUN, because nothing on the day itself works
-- NEGOTIATED GRID BASE still carries a number on 90% of Iowa/Minnesota's
cash-blank days, so the "full skeleton" shape is not a signature. Measured over
2024-01-01..2026-10-02, longest ordinary run against shortest suppression run:

                    volume: quiet / withheld     price: quiet / withheld
    Iowa/Minnesota        3   /   --                  4   /   --
    Nebraska              4   /   --                  4   /   --
    Kansas                4   /   35 (open)           4   /   35 (open)
    TX/OK/NM              4   /   36, 67              6   /   35, 67

Every ordinary stretch ended by day 6 and every suppression run reached at
least 35, with nothing in between on either series. SUPPRESSION_RUN_DAYS has to
sit in that empty middle -- and the floor that binds is the PRICE series' 6,
not the volume series' 4, because TX/OK/NM is thin enough to go six sessions
without a usable quote while reporting normally.
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
ORDINARY_MAX_RUN = 4        # longest quiet blank run on the VOLUME series
PRICE_ORDINARY_MAX_RUN = 6  # ... and on the PRICE series, which is the binding one
WITHHELD_MIN_RUN = 35       # shortest run that turned out to be suppression


@pytest.fixture(scope="module")
def ns():
    return load_from_app(
        APP, "weekly_to_date", "_null_run_days", "_price_blank_run_days",
        "_trailing_blank_run", "and_list",
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
    """
    Above every quiet run on BOTH series, below every suppression run observed.

    The price floor is what binds. A threshold of 5 or 6 would clear the volume
    series and still call a live TX/OK/NM market withheld.
    """
    assert ORDINARY_MAX_RUN < ns["SUPPRESSION_RUN_DAYS"] <= WITHHELD_MIN_RUN
    assert PRICE_ORDINARY_MAX_RUN < ns["SUPPRESSION_RUN_DAYS"]


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


# ── The price tiles ──────────────────────────────────────────────────────────

def _prices(series, days=25):
    """
    A price frame shaped like fetch_daily_cash's output.

    `series` maps region -> list of (head, price) or None per trading day,
    newest LAST. None is a day USDA published the row with both fields blank;
    omitting a day entirely is a day USDA did not publish at all, which
    fetch_daily_cash keeps distinct on purpose.
    """
    dates = list(pd.bdate_range(end="2026-10-02", periods=days))
    rows = []
    for region, vals in series.items():
        vals = [None] * (len(dates) - len(vals)) + list(vals)
        for d, v in zip(dates, vals):
            head, price = (None, None) if v is None else v
            rows.append({
                "region": region, "cut": "morning", "file_date": d,
                "class": "STEER", "basis": "Live FOB",
                "head": head, "weight": 1400.0, "price": price,
                "trade_date": d,
            })
    return pd.DataFrame(rows), dates[-1]


def test_a_sustained_price_blank_is_withheld(ns):
    """TX/OK/NM and Kansas today: every row published, every price blank."""
    df, today = _prices({"Kansas": [None] * 25})
    assert ns["_price_blank_run_days"](df, "Kansas", today) == 25
    assert ns["_price_blank_run_days"](df, "Kansas", today) >= ns["SUPPRESSION_RUN_DAYS"]


def test_a_thin_market_going_six_sessions_quiet_is_not_withheld(ns):
    """
    The case that sets the floor. TX/OK/NM really does go six sessions without
    a usable quote while reporting normally -- it must still say "Undefined".
    """
    quiet = [(500.0, 220.0)] * (25 - PRICE_ORDINARY_MAX_RUN) \
        + [None] * PRICE_ORDINARY_MAX_RUN
    df, today = _prices({"TX/OK/NM": quiet})
    run = ns["_price_blank_run_days"](df, "TX/OK/NM", today)
    assert run == PRICE_ORDINARY_MAX_RUN
    assert run < ns["SUPPRESSION_RUN_DAYS"]


def test_a_usable_print_resets_the_price_run(ns):
    df, today = _prices({"Kansas": [None] * 20 + [(500.0, 220.0)] + [None] * 4})
    assert ns["_price_blank_run_days"](df, "Kansas", today) == 4


def test_a_price_without_a_head_count_is_not_a_usable_print(ns):
    """
    daily_combined() drops a row it cannot weight, so _headline never sees it
    and the tile still reads blank. The run has to agree with the tile.
    """
    df, today = _prices({"Kansas": [None] * 24 + [(None, 220.0)]})
    assert ns["_price_blank_run_days"](df, "Kansas", today) == 25


def test_a_head_count_without_a_price_is_not_a_usable_print(ns):
    df, today = _prices({"Kansas": [None] * 24 + [(500.0, None)]})
    assert ns["_price_blank_run_days"](df, "Kansas", today) == 25


def test_a_region_absent_from_the_price_feed_has_no_run(ns):
    df, today = _prices({"Nebraska": [(500.0, 220.0)] * 25})
    assert ns["_price_blank_run_days"](df, "TX/OK/NM", today) == 0


def test_the_run_ignores_days_after_the_one_asked_about(ns):
    """
    The tiles headline `last_trade`, but the window can hold later file dates;
    a run must describe the day on screen.
    """
    df, _ = _prices({"Kansas": [(500.0, 220.0)] * 20 + [None] * 5})
    earlier = list(pd.bdate_range(end="2026-10-02", periods=25))[19]
    assert ns["_price_blank_run_days"](df, "Kansas", earlier) == 0


def test_trailing_blank_run_skips_unpublished_days(ns):
    """
    A day USDA never published is not in the map. It must neither count toward
    the run nor break it -- the run is about what USDA said when it spoke.
    """
    days = list(pd.bdate_range(end="2026-10-02", periods=5))
    # days[2] is missing entirely; the rest are blank.
    flags = {days[0]: True, days[1]: True, days[3]: True, days[4]: True}
    assert ns["_trailing_blank_run"](flags, days[4]) == 4
    flags[days[1]] = False
    assert ns["_trailing_blank_run"](flags, days[4]) == 2


def _body(name):
    """
    The source of one top-level function, minus its docstring.

    ast, not inspect: these functions are exec'd out of the page by
    load_from_app, so they have no source file to read. And minus the
    docstring, because every one of them NAMES the other series in prose --
    matching a comment instead of code is the mistake streamlit_source.py
    exists to stop.
    """
    import ast
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            stmts = node.body
            if stmts and isinstance(stmts[0], ast.Expr) \
                    and isinstance(stmts[0].value, ast.Constant) \
                    and isinstance(stmts[0].value.value, str):
                stmts = stmts[1:]
            return "\n".join(ast.unparse(s) for s in stmts)
    raise AssertionError(f"{name} not found at module level in {APP.name}")


def test_the_two_series_are_measured_separately(ns):
    """
    Price and volume blank together when a region is suppressed, but they come
    from different requests and _fetch_many returns [] for a job that failed.
    A volume fetch that died must not make the price tiles claim a withholding,
    or vice versa, so neither helper may reach into the other's frame.
    """
    price_src = _body("_price_blank_run_days")
    vol_src = _body("_null_run_days")
    assert "period" not in price_src      # the volume frame's column
    assert "'price'" not in vol_src       # the price frame's column
    assert "head_week_ago" not in price_src
