"""Proof that the forecast scorecard is not marking its own homework.

A scorecard is only worth the page space if two things hold, and both fail
silently rather than loudly:

  * it scores the code the page actually runs, not a second copy that drifts;
  * it replays each past week seeing ONLY what had been published at the time.

The second is the one that flatters. If the scored week's Friday-final file
survives into the inputs, the "forecast" is reading the answer and the
scorecard reports near-perfect accuracy for a method that has none.

    python -m pytest tests/test_cash_scorecard.py -q
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
                "FORECAST_MAX_ANALOGUES", "FORECAST_WEAK_MATURITY",
                "FORECAST_MIN_ANALOGUES"),
        globals_={"pd": pd},
    )


def _vol(rows):
    df = pd.DataFrame(rows, columns=["trade_date", "region", "cut", "period", "head"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["head_week_ago"] = None
    return df


def _week_rows(monday, per_day, region="Nebraska"):
    """per_day: five (afternoon_wtd, morning_wtd) pairs, None to omit a file."""
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


# ── the integrity test ───────────────────────────────────────────────────────

def test_truncation_hides_the_scored_week_s_own_answer(fc):
    """The Friday FINAL is the answer and must not survive into the inputs.

    USDA publishes it the following Monday, so a forecast standing at Friday's
    1:30 pm cut cannot have seen it. If it leaks, every scored week reports a
    near-zero miss and the scorecard is worthless while looking excellent.
    """
    rows, _ = _history(6)
    vol = _vol(rows)
    week = pd.Timestamp("2026-02-02")
    t = sc._truncate(vol, week, 4, fc["CUT_ORDER"]["afternoon"], fc["CUT_ORDER"])

    leaked = t[(t["trade_date"] == week + pd.Timedelta(days=4)) & (t["cut"] == "morning")]
    assert leaked.empty, "the scored week's final survived truncation"
    # ...and the truncated frame must still END on the scored week, or
    # forecast_5area would pick a different week as "current".
    cps = fc["wtd_checkpoints"](t)
    assert pd.Timestamp(cps["week"].max()) == week
    # earlier weeks keep their finals, which is what the analogue pool needs
    earlier = t[(t["trade_date"] == week - pd.Timedelta(days=3)) & (t["cut"] == "morning")]
    assert not earlier.empty


def test_a_leaked_answer_would_change_the_score(fc):
    """Guard the guard: show the truncation is load-bearing, not decorative."""
    rows, finals = _history(8)
    # The live week must be OPEN -- no Friday final yet -- or the page is in its
    # "week is closed" state and the scorecard steps back a checkpoint instead.
    cur = pd.Timestamp("2026-03-02")
    rows += _week_rows(cur, [(None, None), (None, None), (None, 36000),
                             (None, 36000), (40000, None)])
    vol = _vol(rows)
    board = sc.build_scorecard(vol, finals, finals * 1.5, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=5)
    assert not board.empty
    # Standing at the Friday cut, the forecast sees 40,000 and adds the median
    # late trade from identical past weeks -- landing exactly on the answer.
    # The point is that it got there by INFERENCE: the 43,000 it reports is
    # built from other weeks, and the wtd it stood on is the pre-final 40,000.
    assert (board["wtd"] == 40000).all()
    assert (board["f5"] == 43000).all()


# ── scoring the real thing ───────────────────────────────────────────────────

def test_the_scorecard_imports_no_forecast_of_its_own(fc):
    """It must receive the page's functions, never define or import a copy.

    A reimplementation grades a copy: the copy drifts, the page keeps its own
    behaviour, and the scorecard reports on code nobody runs.
    """
    tree = ast.parse(APP.with_name("scorecard.py").read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "forecast_5area" not in defined
    assert "forecast_national" not in defined
    imported = {a.name.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.module}
    assert "app" not in imported
    # and the entry point really does take them as parameters
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "build_scorecard")
    args = [a.arg for a in fn.args.args]
    assert "forecast_5area" in args and "forecast_national" in args


def test_only_weeks_at_the_same_checkpoint_are_scored(fc):
    """A Thursday call must never be scored as though it were a Friday one.

    How much of a week is still to come depends entirely on where in the week
    you stand, so mixing checkpoints compares two different questions.
    """
    rows, finals = _history(5)          # weeks 01-05 .. 02-02
    # one past week that published NO Friday afternoon file at all. It must sit
    # OUTSIDE the generated run or it collides and gives published5 a duplicate
    # index, which is impossible in production -- weekly_5area_head de-dupes.
    odd = pd.Timestamp("2026-02-09")
    rows += _week_rows(odd, [(None, None), (None, None), (None, 30000),
                             (None, 33000), (None, 35000)])
    finals = pd.concat([finals, pd.Series({odd: 35000.0})]).sort_index()
    # current week, standing at the Friday cut
    cur = pd.Timestamp("2026-02-16")
    rows += _week_rows(cur, [(None, None), (None, None), (None, 36000),
                             (None, 36000), (40000, None)])
    vol = _vol(rows)

    board = sc.build_scorecard(vol, finals, finals * 1.5, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=10)
    assert odd not in set(board["week"]), "scored a week that never hit the checkpoint"
    assert cur not in set(board["week"]), "scored the live week against itself"


# ── the summary ──────────────────────────────────────────────────────────────

def test_summary_uses_the_median_not_the_mean():
    """Misses are right-skewed, so a mean describes none of the weeks.

    Late trade can surprise upward without limit and cannot go below zero. One
    back-loaded week in ten drags a mean well past every individual miss.
    """
    board = pd.DataFrame({
        "week": pd.date_range("2026-01-05", periods=5, freq="7D"),
        "miss5": [100.0, 100.0, 100.0, 100.0, 50_000.0],
        "a5": [50_000.0] * 5,
        "in5": [True] * 5,
        "missn": [0.0] * 5, "an": [1.0] * 5, "inn": [True] * 5,
    })
    board["pct5"] = board["miss5"] / board["a5"]
    board["pctn"] = board["missn"] / board["an"]
    s = sc.summarise(board)
    assert s["five"]["median_abs_head"] == 100.0        # not the 10,080 mean
    assert s["five"]["in_band"] == 1.0
    assert s["n"] == 5


def test_empty_when_there_is_nothing_to_score(fc):
    """No history means no accuracy claim, not a claim built on one week."""
    rows, finals = _history(1)
    vol = _vol(rows)
    board = sc.build_scorecard(vol, finals, finals * 1.5, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"])
    assert board.empty
    assert sc.summarise(board) == {}


# ── the week in flight ───────────────────────────────────────────────────────

def _live_week(fc, n_history=12, open_week="2026-03-30"):
    """History of settled weeks, plus one open week standing at Friday 1:30.

    TWELVE weeks, not eight: forecast_5area refuses to call off a pool thinner
    than FORECAST_MIN_ANALOGUES, so a short history now produces a pending row
    with no estimates and these tests would be exercising the blocked path
    while reading like they exercise the live one.
    """
    rows, fin = _history(n_history, start="2026-01-05")
    rows += _week_rows(open_week, [(None, None), (None, None), (None, 36000),
                                   (None, 36000), (40000, None)])
    vol = _vol(rows)
    nat = pd.Series({k: v + 20000.0 for k, v in fin.items()})
    return vol, fin, nat


def test_the_open_week_appears_as_a_pending_row(fc):
    """What the page puts on top of the table: a call with no answer yet."""
    vol, fin, nat = _live_week(fc)
    row = sc.pending_row(vol, fin, nat, fc["forecast_5area"],
                         fc["forecast_national"])
    assert len(row) == 1
    r = row.iloc[0]
    assert r["week"] == pd.Timestamp("2026-03-30")
    assert r["pending"] is True or bool(r["pending"])
    # The estimates are there...
    assert r["f5"] > 0 and r["fn"] > 0
    assert r["wtd"] == 40000
    # ...and nothing that would need an actual is.
    assert pd.isna(r["a5"]) and pd.isna(r["an"])
    assert pd.isna(r["miss5"]) and pd.isna(r["missn"])


def test_the_pending_row_vanishes_once_usda_prints(fc):
    """The whole correctness condition.

    Leave it in after the print and the week shows TWICE -- once scored, once
    blank -- and the blank one reads as a second call that failed.
    """
    vol, fin, nat = _live_week(fc)
    week = pd.Timestamp("2026-03-30")
    assert not sc.pending_row(vol, fin, nat, fc["forecast_5area"],
                              fc["forecast_national"]).empty

    printed = pd.concat([fin, pd.Series({week: 43000.0})])
    printed_nat = pd.concat([nat, pd.Series({week: 63000.0})])
    assert sc.pending_row(vol, printed, printed_nat, fc["forecast_5area"],
                          fc["forecast_national"]).empty


def test_a_pending_row_never_reaches_the_accuracy_figures(fc):
    """summarise() must describe settled calls only.

    Its actual is NaN, so a median would skip it and report "the last 10"
    while averaging 9 -- true-looking, and wrong by one.
    """
    vol, fin, nat = _live_week(fc)
    board = sc.build_scorecard(vol, fin, nat, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=10)
    clean = sc.summarise(board)
    assert clean and clean["n"] == len(board)

    row = sc.pending_row(vol, fin, nat, fc["forecast_5area"],
                         fc["forecast_national"])
    polluted = sc.summarise(pd.concat([row, board], ignore_index=True))
    assert polluted == clean, "an unsettled week changed the accuracy figures"


def test_scored_rows_are_marked_not_pending(fc):
    """The flag the page and summarise() both switch on."""
    vol, fin, nat = _live_week(fc)
    board = sc.build_scorecard(vol, fin, nat, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=10)
    assert "pending" in board.columns
    assert not board["pending"].any()


def test_pending_and_scored_rows_concatenate(fc):
    """They are displayed as one table, so the columns have to line up."""
    vol, fin, nat = _live_week(fc)
    board = sc.build_scorecard(vol, fin, nat, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=10)
    row = sc.pending_row(vol, fin, nat, fc["forecast_5area"],
                         fc["forecast_national"])
    assert set(row.columns) == set(board.columns)
    both = pd.concat([row, board], ignore_index=True)
    assert len(both) == len(board) + 1
    assert bool(both["pending"].iloc[0]) is True


def test_no_pending_row_without_a_live_forecast(fc):
    """Empty rather than a row of NaNs when there is nothing to stand on."""
    rows, fin = _history(8, start="2026-01-05")
    assert sc.pending_row(_vol(rows), fin,
                          pd.Series({k: v + 20000.0 for k, v in fin.items()}),
                          fc["forecast_5area"], fc["forecast_national"]).empty

def test_once_printed_the_live_forecast_is_not_the_call_we_made(fc):
    """The reason the tiles need a settled state at all.

    Once Friday's final lands forecast_5area reports done=True and returns the
    week-to-date unchanged, so its "central" IS the actual. A headline tile
    reading that field therefore prints the answer and calls it a forecast,
    and the call we actually made disappears from the page — which is exactly
    what happened on 2026-10-05: the tiles read 60,063 twice while the
    scorecard below them reported we had called 61,167.

    This pins the gap between the two numbers, so a tile wired back to the
    live forecast fails here rather than looking plausible.
    """
    # history settles 3,000 above its Friday cut; the live week settles 5,000
    # above, so the replayed call and the actual cannot coincide by luck.
    rows, finals = _history(8)
    cur = pd.Timestamp("2026-03-02")
    rows += _week_rows(cur, [(None, None), (None, None), (None, 36000),
                             (None, 36000), (40000, 45000)])
    finals = pd.concat([finals, pd.Series({cur: 45000.0})]).sort_index()
    vol = _vol(rows)
    nat = finals * 1.5

    live = fc["forecast_5area"](vol, finals)
    assert live["done"] is True
    assert live["central"] == live["wtd"] == 45000     # the actual, not a call

    board = sc.build_scorecard(vol, finals, nat, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=5)
    top = board.iloc[0]
    assert pd.Timestamp(top["week"]) == cur           # the just-printed week
    assert bool(top.get("pending", False)) is False   # genuinely scored
    assert top["a5"] == 45000                         # USDA's figure
    assert top["f5"] == 43000                         # what we actually called
    assert top["f5"] != live["central"], (
        "the replayed call and the live 'forecast' must differ once printed, "
        "or this test cannot catch a tile wired to the wrong one")

def test_an_empty_new_week_does_not_rescore_history_from_zero(fc):
    """Every Tuesday the live checkpoint is a Monday where nothing has traded.

    Scoring the last ten weeks at THAT point replays each from an empty base,
    so every estimate collapses to the same figure — the median late trade
    added to nothing — every row grades "weak", and the accuracy reads an
    order of magnitude worse than the calls those weeks really produced.

    Observed live on 2026-10-06: the tiles reported the settled Sep 28 week at
    60,897 against USDA's 60,063, while the table underneath said 49,062 for
    the same week. Same week, two "we called" figures, one screen — the exact
    contradiction the settled tiles were added to remove.

    A checkpoint nobody would ever forecast from is not one worth scoring at.
    """
    rows, finals = _history(10)
    # a fresh week with a single Monday publication and nothing in it
    newwk = pd.Timestamp("2026-03-16")
    rows += [(newwk, "Nebraska", "afternoon", "wtd", 0.0)]
    vol = _vol(rows)
    nat = finals * 1.5

    live = fc["forecast_5area"](vol, finals)
    assert pd.Timestamp(live["week"]) == newwk and live["wtd"] == 0

    board = sc.build_scorecard(vol, finals, nat, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=5)
    assert not board.empty
    # scored where the calls were MADE — the Friday cut, wtd 40,000 — not at
    # the empty Monday, which would put every wtd at 0 and every call equal.
    assert (board["wtd"] == 40000).all(), (
        "history was rescored from the empty new week")
    assert board["f5"].nunique() == 1 and board.iloc[0]["f5"] == 43000
    assert (board["grade"] != "weak").all()


def test_the_table_and_the_settled_tiles_quote_the_same_call(fc):
    """They read the same row, so they cannot disagree — pin that they do.

    This is the invariant both 2026-10-05 and 2026-10-06 broke from opposite
    directions: first the tiles overwrote the call with the actual, then the
    table rescored it at a checkpoint the call never stood at.
    """
    rows, finals = _history(10)
    cur = pd.Timestamp("2026-03-16")
    rows += _week_rows(cur, [(None, None), (None, None), (None, 36000),
                             (None, 36000), (40000, 45000)])
    finals = pd.concat([finals, pd.Series({cur: 45000.0})]).sort_index()
    vol = _vol(rows)

    board = sc.build_scorecard(vol, finals, finals * 1.5, fc["forecast_5area"],
                               fc["forecast_national"], fc["CUT_ORDER"], weeks=5)
    top = board.iloc[0]
    assert pd.Timestamp(top["week"]) == cur
    # what the tiles show IS this row — one object, so one number
    assert top["f5"] == 43000 and top["a5"] == 45000
    assert top["wtd"] == 40000
