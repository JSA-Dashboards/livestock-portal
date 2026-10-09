"""A week that has barely traded is not a checkpoint worth scoring at.

The scorecard replays every past week at the checkpoint the LIVE week is
standing at, which is right: read the page on a Wednesday and the accuracy
underneath should describe a Wednesday call, not flatter you with Friday's.

It stops being right when the live week has not meaningfully opened. Then
every past week is replayed from a near-empty base, the estimate is the
analogue median with noise added, and the table prints numbers that are not
the calls we made.

**This was found in the wild twice, the second time through a hole in the
first fix.** The 2026-10-06 guard tested `not live["wtd"]`, which catches a
literal zero only. On 2026-10-07 the live week stood at 337 head -- 0.76% of a
typical week -- so the guard sat out and the whole failure returned:

                        page showed        we actually called
    Sep 28  5-Area        45,784                60,897   (USDA printed 60,063)
    Sep 28  National      66,340                81,453   (USDA printed 88,019)
    headline 5-Area        23.8%                  1.4%
    headline National      29.4%                  7.9%

337 head is zero in every sense except the arithmetic one, so the test is
maturity rather than truthiness, and the line is forecast_5area's own "weak"
boundary. Measured over 457 (week, checkpoint) pairs on the live feed, the
forecast beats the naive alternative -- ignore the week, print a typical one --
nowhere below maturity 0.50 and clearly above it.

    python -m pytest tests/test_cash_scorecard_green.py -q
"""

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "apps" / "cash_trade"))
from streamlit_source import load_from_app  # noqa: E402

import scorecard as sc  # noqa: E402

APP = ROOT / "apps" / "cash_trade" / "app.py"


@pytest.fixture(scope="module")
def fc():
    return load_from_app(
        APP, "_week_start", "weekly_5area_head", "weekly_national_head",
        "wtd_checkpoints", "_front_of", "forecast_5area", "forecast_national",
        consts=("CUT_ORDER", "FORECAST_GAP_WEEKS", "FORECAST_BAND_WEEKS",
                "FORECAST_MAX_ANALOGUES", "FORECAST_WEAK_MATURITY"),
        globals_={"pd": pd},
    )


def _vol(rows):
    df = pd.DataFrame(rows, columns=["trade_date", "region", "cut", "period", "head"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["head_week_ago"] = None
    return df


def _week_rows(monday, per_day, region="Nebraska"):
    out, base = [], pd.Timestamp(monday)
    for i, (aftn, final) in enumerate(per_day):
        d = base + pd.Timedelta(days=i)
        if aftn is not None:
            out.append((d, region, "afternoon", "wtd", aftn))
        if final is not None:
            out.append((d, region, "morning", "wtd", final))
    return out


def _history(n_weeks, start="2026-01-05", late=3000):
    """Identical weeks: Fri 1:30 cut at 40,000, finishing `late` higher."""
    rows, finals = [], pd.Timestamp(start)
    fin = {}
    for i in range(n_weeks):
        wk = finals + pd.Timedelta(days=7 * i)
        rows += _week_rows(wk, [(None, None), (None, None), (None, 36000),
                                (None, 36000), (40000, 40000 + late)])
        fin[wk] = 40000.0 + late
    return rows, pd.Series(fin)


# -- the predicate -----------------------------------------------------------

def test_a_literal_zero_is_too_green():
    """What the original guard caught, and must keep catching."""
    assert sc._too_green({"wtd": 0, "maturity": 0.0}) is True


def test_337_head_is_also_too_green():
    """
    The bug. A head count that is 0.76% of a typical week is nothing, and the
    old `not live["wtd"]` read it as a real checkpoint because it is truthy.
    """
    assert sc._too_green({"wtd": 337, "maturity": 337 / 44_500}) is True


def test_a_mature_week_is_not_too_green():
    """The design survives: a real mid-week call is still scored where it stands."""
    assert sc._too_green({"wtd": 40000, "maturity": 0.90}) is False
    assert sc._too_green({"wtd": 25000, "maturity": 0.55}) is False


def test_the_boundary_is_the_forecasts_own_weak_line():
    """
    Not a new magic number: forecast_5area already grades below 0.50 "weak",
    and that is where the measurement says the forecast stops beating naive.
    """
    assert sc.GREEN_MATURITY == 0.50
    assert sc._too_green({"maturity": 0.499}) is True
    assert sc._too_green({"maturity": 0.50}) is False


def test_an_unknown_maturity_is_too_green():
    """
    No typical week to measure against is not a state to replay ten weeks
    from. NaN must not fall through to False on a `<` comparison.
    """
    assert sc._too_green({"maturity": float("nan")}) is True
    assert sc._too_green({}) is True


# -- what it does to the board -----------------------------------------------

def _board_for(fc, live_week_rows, weeks=5, n_hist=8):
    rows, finals = _history(n_hist)
    rows += live_week_rows
    vol = _vol(rows)
    return sc.build_scorecard(vol, finals, finals * 1.5, fc["forecast_5area"],
                              fc["forecast_national"], fc["CUT_ORDER"],
                              weeks=weeks), finals


def test_a_barely_traded_live_week_steps_back_to_a_real_checkpoint(fc):
    """
    The whole point. A Wednesday carrying a few hundred head must not drag
    every scored week down to a Wednesday replay.
    """
    cur = pd.Timestamp("2026-03-02")
    board, _ = _board_for(fc, _week_rows(cur, [(None, None), (None, None),
                                               (337, None), (None, None),
                                               (None, None)]))
    assert not board.empty
    cp = sc.checkpoint_of(board)
    assert cp == (4, fc["CUT_ORDER"]["afternoon"]), cp     # Friday 1:30, not Wednesday
    # ...and the rows are therefore the real calls: 40,000 standing, 43,000 called
    assert (board["wtd"] == 40000).all()
    assert (board["f5"] == 43000).all()


def test_a_mature_live_week_is_still_scored_where_it_stands(fc):
    """
    The guard must not swallow the design. A Thursday final at 36,000 is a
    real checkpoint and past weeks are replayed at that same Thursday.
    """
    cur = pd.Timestamp("2026-03-02")
    board, _ = _board_for(fc, _week_rows(cur, [(None, None), (None, None),
                                               (None, 36000), (None, 36000),
                                               (None, None)]))
    assert not board.empty
    assert sc.checkpoint_of(board) == (3, fc["CUT_ORDER"]["morning"])
    assert (board["wtd"] == 36000).all()


# -- checkpoint_of -----------------------------------------------------------

def test_checkpoint_of_is_empty_on_an_empty_board():
    assert sc.checkpoint_of(pd.DataFrame()) is None


def test_the_pending_row_never_answers_for_the_scored_checkpoint(fc):
    """
    The pending row stands at the LIVE checkpoint by design, so if it could
    answer checkpoint_of the page would label the table with the checkpoint
    the rows were NOT scored at -- which is the mislabelling this fixes.
    """
    rows, finals = _history(8)
    cur = pd.Timestamp("2026-03-02")
    rows += _week_rows(cur, [(None, None), (None, None), (337, None),
                             (None, None), (None, None)])
    vol = _vol(rows)
    board = sc.build_scorecard(vol, finals, finals * 1.5, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=5)
    pend = sc.pending_row(vol, finals, finals * 1.5,
                          fc["forecast_5area"], fc["forecast_national"])
    assert not pend.empty
    assert pend["pending"].all()
    both = pd.concat([pend, board], ignore_index=True)
    # concat must not invent columns, and the answer must not move
    assert sc.checkpoint_of(both) == sc.checkpoint_of(board)
    assert sc.checkpoint_of(both) == (4, fc["CUT_ORDER"]["afternoon"])


def test_the_checkpoint_rides_on_the_rows_not_on_attrs(fc):
    """
    pandas drops .attrs through most operations, including the concat the page
    does with the pending row. Carrying it per row is what keeps it readable
    after that, so the columns have to actually be there.
    """
    cur = pd.Timestamp("2026-03-02")
    board, _ = _board_for(fc, _week_rows(cur, [(None, None), (None, None),
                                               (337, None), (None, None),
                                               (None, None)]))
    assert {"cp_weekday", "cp_order"} <= set(board.columns)
    assert board["cp_weekday"].nunique() == 1


# -- the page has to say which checkpoint it scored --------------------------

def test_the_page_labels_the_checkpoint_it_actually_scored():
    """
    Stepping back buys honest rows and costs an honest header: "at this point
    in the week" then describes a checkpoint the rows were not scored at, and
    a Friday call's accuracy printed under a Monday one flatters rather than
    merely misleads.
    """
    src = APP.read_text(encoding="utf-8")
    assert "scorecard.checkpoint_of(board)" in src
    assert "_cp_label" in src
    # ast, not a substring: "checkpoint_of" also appears in prose nearby
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "checkpoint_of"]
    assert len(calls) == 1, [n.lineno for n in calls]


def test_the_label_is_built_before_the_header_that_prints_it():
    """
    A source test that only asserts both strings exist passes while the page
    raises NameError, which is exactly what happened: the label was written
    underneath the header that interpolates it. Script order again.

    ast, so this reads the real assignment and the real use rather than their
    spelling in a comment.
    """
    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assigns = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_cp_label"
                       for t in n.targets)]
    uses = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "_cp_label"
            and isinstance(n.ctx, ast.Load)]
    assert assigns, "_cp_label is never assigned"
    assert uses, "_cp_label is never used"
    assert max(assigns) < min(uses), (
        f"assigned at {assigns}, used at {uses} -- the page would NameError")


def test_no_prose_under_the_table_names_the_live_checkpoint():
    """
    The header was not the only place that named a checkpoint. The paragraph
    under the table says each week was replayed "standing at the same <dow>
    <cut>", and it was built from the LIVE checkpoint -- so with the guard
    stepping back it read "Wednesday 1:30 pm cut" over rows scored at Friday's.

    Both now read the SCORED checkpoint. `_dow`/`_cut` stay for the tiles
    above, which really are the live call, so the test is that the replay
    paragraph does not use them rather than that they are gone.
    """
    src = APP.read_text(encoding="utf-8")
    start = src.index("Each past week is replayed")
    para = src[start:src.index("published by then", start)]
    assert "_sc_dow_lbl" in para and "_sc_cut_lbl" in para
    assert "{_dow}" not in para, "the replay paragraph still names the live checkpoint"
