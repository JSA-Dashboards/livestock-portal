"""
The day's high and low, beside the weighted average.

Ross, 2026-10-16: *"my daily cash trade on the dashboard doesn't show the high
and low ranges anywhere. can we add that somewhere so i can see the 227 in
nebraska?"* Nebraska traded 222.00-227.00 live that day on 4,539 head; the
page showed only the head-weighted average, so the top of the market was
nowhere on it.

USDA sends `price_range_low` and `price_range_high` on every priced row and
fetch_daily_cash simply dropped them.

WHAT CAN GO WRONG HERE IS AN AVERAGED RANGE. A low and a high are min and max
over the rows the average is built from; head-weighting them gives a pair of
numbers no lot ever traded at, and the top of the market is the entire reason
to show it. These tests mostly pin that.

    python -m pytest tests/test_daily_cash_range.py -q
"""
from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from streamlit_source import load_from_app  # noqa: E402

APP = REPO / "apps" / "cash_trade" / "app.py"
SRC = APP.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

daily_combined = load_from_app(APP, "daily_combined")


def frame(rows):
    """fetch_daily_cash()-shaped rows for one region, one day, one basis."""
    return pd.DataFrame([
        {"trade_date": pd.Timestamp(2026, 10, 16), "region": "Nebraska",
         "cut": "afternoon", "basis": "Live FOB", "class": cls,
         "head": head, "weight": 1400.0, "price": price,
         "low": low, "high": high}
        for cls, head, price, low, high in rows
    ])


# -- the arithmetic -------------------------------------------------------

def test_the_range_spans_both_classes_and_the_average_sits_inside_it():
    """Nebraska's real 10/16 print: steers 222-227, heifers 222-225."""
    g = daily_combined(frame([
        ("STEER", 3875, 224.50, 222.0, 227.0),
        ("HEIFER", 664, 223.00, 222.0, 225.0),
    ]))
    row = g.iloc[0]
    assert (row["low"], row["high"]) == (222.0, 227.0)
    assert row["head"] == 4539
    # the free audit: a weighted average outside its own range is a bug
    assert row["low"] <= row["price"] <= row["high"]


def test_the_range_is_not_weighted():
    """
    THE WHOLE POINT. A big lot at a narrow range must not pull the extremes
    in -- 227.00 traded, and a head-weighted "high" of 224.40 would say it
    did not. Chosen so a weighted result is nowhere near the true one.
    """
    g = daily_combined(frame([
        ("STEER", 50, 227.00, 227.0, 227.0),     # small lot, top of the market
        ("HEIFER", 9950, 222.00, 222.0, 222.0),  # the rest, at the bottom
    ]))
    row = g.iloc[0]
    assert (row["low"], row["high"]) == (222.0, 227.0)
    weighted_high = (50 * 227.0 + 9950 * 222.0) / 10000
    assert row["high"] != weighted_high


def test_a_priced_row_with_no_range_does_not_narrow_it():
    """USDA can price a row and omit the spread; min/max skip NaN."""
    g = daily_combined(frame([
        ("STEER", 1000, 224.0, 222.0, 227.0),
        ("HEIFER", 500, 223.0, float("nan"), float("nan")),
    ]))
    row = g.iloc[0]
    assert (row["low"], row["high"]) == (222.0, 227.0)


def test_no_range_anywhere_leaves_it_blank_rather_than_zero():
    g = daily_combined(frame([
        ("STEER", 1000, 224.0, float("nan"), float("nan")),
    ]))
    row = g.iloc[0]
    assert pd.isna(row["low"]) and pd.isna(row["high"])
    assert row["price"] == 224.0, "the average must survive a missing range"


def test_each_cut_keeps_its_own_range():
    """The 1:30 cut and the final are different prints of the same day and
    must not be pooled -- the page shows them side by side."""
    df = frame([("STEER", 168, 220.0, 220.0, 220.0)])
    df2 = frame([("STEER", 3888, 221.5, 220.0, 223.0)])
    df2["cut"] = "morning"
    g = daily_combined(pd.concat([df, df2], ignore_index=True))
    cut = g[g["cut"] == "afternoon"].iloc[0]
    fin = g[g["cut"] == "morning"].iloc[0]
    assert (cut["low"], cut["high"]) == (220.0, 220.0)
    assert (fin["low"], fin["high"]) == (220.0, 223.0)


# -- the wiring -----------------------------------------------------------

def test_the_fetch_carries_the_published_low_and_high():
    fn = next(n for n in TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_daily_cash")
    body = ast.unparse(fn)
    assert "price_range_low" in body and "price_range_high" in body


def test_the_frame_shape_change_is_in_the_cache_key():
    """
    fetch_daily_cash is @st.cache_data(persist="disk"), so a frame pickled
    before these columns existed is re-served FROM DISK and survives a reboot
    -- the tiles would render an em dash with nothing raising. `stamps` only
    changes when USDA publishes, which is a different question.

    Both halves of the SCHEMA rule: no leading underscore, and passed at the
    call site rather than left on its default.
    """
    fn = next(n for n in TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_daily_cash")
    names = [a.arg for a in fn.args.args]
    assert "schema" in names, "fetch_daily_cash takes no cache-shape key"
    assert "_schema" not in names, (
        "an underscore-prefixed argument is excluded from the cache key")

    calls = [n for n in ast.walk(TREE)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "fetch_daily_cash"]
    assert calls, "fetch_daily_cash is never called"
    for c in calls:
        passed = [ast.unparse(a) for a in c.args] + \
                 [ast.unparse(k.value) for k in c.keywords]
        assert "DAILY_SCHEMA" in passed, (
            "a default is not part of the cache key; pass DAILY_SCHEMA explicitly")


def test_the_tile_puts_the_range_on_its_own_line():
    """
    .tile-delta-neu is nowrap and four tiles share the row, so appending to a
    caption already reading "4,539 hd - Live FOB, 1:30 pm cut" overflows below
    desktop width. The same correction the WASDE panel needed.
    """
    i = SRC.index('class="tile-sub">range')
    assert i > 0, "the range is not on a .tile-sub line"
    # and it is labelled, because two prices under a third are not self-evident
    assert "tile-sub\">range " in SRC


def test_a_single_price_prints_no_range_line():
    """
    low == high means every lot traded at one price and the average above IS
    that price, so a range line would print the same figure a third time.
    """
    seg = SRC[SRC.index("_ranges = {}"):SRC.index("_rng_spacer")]
    assert "_lo != _hi" in seg, "a one-price day still renders a range"
    assert "pd.notna(_lo)" in seg and "pd.notna(_hi)" in seg


def test_the_tile_row_cannot_go_ragged():
    """
    MEASURED IN A BROWSER, invisible to everything else. Four tiles with
    backgrounds share the row and only some days carry a range, so adding the
    line per tile made Nebraska and Iowa/Minnesota 128px tall against 107 for
    Kansas and TX/OK/NM -- bottoms at 534 against 513 at 1440px.

    The line is reserved across the whole row or none of it, which means the
    spacer has to reach the BLANK tiles too; those render in a different
    branch, and that is the one a reader of this code would miss.
    """
    seg = SRC[SRC.index("_ranges = {}"):SRC.index("Both cuts, side by side")]
    assert "_rng_spacer" in seg
    # a day with no range anywhere keeps the short row
    assert "if _ranges else \"\"" in seg
    # and both render branches carry it
    assert seg.count("+ _rng,") == 2, (
        "the spacer reaches only one of the two tile branches, so a row "
        "mixing priced and withheld regions goes ragged again")


def test_the_table_shows_the_range_without_doubling_its_columns():
    """
    Six price columns is already wide; a parallel set of range columns is
    unreadable on a laptop. The range goes in the cell it belongs to.
    """
    seg = SRC[SRC.index("grid = []"):SRC.index("st.dataframe(pd.DataFrame(grid)")]
    assert '_cell' in seg and 'low' in seg and 'high' in seg
    # still four price columns, not eight
    assert seg.count('entry[f"{short} {DAILY_CUT_LABEL[cut]}"]') == 2
