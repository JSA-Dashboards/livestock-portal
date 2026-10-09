"""Proof that the Monday Print Forecast adds up, and that its traps stay shut.

The tab turns a part-finished week into the two figures USDA prints the
following Monday. Everything it claims rests on one identity -- the four daily
regions' Friday-FINAL week-to-date, summed with nulls as zero, IS USDA's
published 5-Area weekly negotiated head -- so that is pinned first, against
real published numbers.

The rest are the places this would be wrong quietly rather than loudly:

  * a holiday release keyed one day off, so every weekly join silently misses;
  * a suppressed region counted as missing instead of zero, which would move
    the 5-Area total away from the figure USDA actually prints;
  * the two daily cuts ordered by name rather than by when they appear, which
    would read a 1:30 pm partial as the latest word after the final had landed;
  * analogues drawn from a different point in the week, where the amount still
    to come is a different question entirely;
  * a forecast still being offered after Friday's final has made it a fact.

    python -m pytest tests/test_cash_forecast.py -q
"""

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from streamlit_source import load_from_app  # noqa: E402

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


# Real published figures, read from the live datamart 2026-10-02. The daily
# halves are Nebraska and Iowa/Minnesota only, because USDA was withholding
# Kansas and TX/OK/NM on every one of these weeks -- which is exactly why they
# make the point: the published 5-Area total carries the withheld regions as
# nothing too.
REAL_WEEKS = {
    # week start: (Nebraska Fri-final wtd, Iowa/Minn Fri-final wtd, USDA 5-Area)
    "2026-09-21": (17135, 13406, 30541),
    "2026-09-14": (26728, 22483, 49211),
    "2026-08-24": (27387, 24042, 51429),
}


def _vol(rows):
    """Build the frame fetch_daily_volume returns. rows: (date, region, cut, period, head)."""
    df = pd.DataFrame(rows, columns=["trade_date", "region", "cut", "period", "head"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["head_week_ago"] = None
    return df


def _week(monday, per_day):
    """A full Mon-Fri week of week-to-date rows for one region, both cuts."""
    out = []
    base = pd.Timestamp(monday)
    for i, (aftn, final) in enumerate(per_day):
        d = base + pd.Timedelta(days=i)
        if aftn is not None:
            out.append((d, "Nebraska", "afternoon", "wtd", aftn))
        if final is not None:
            out.append((d, "Nebraska", "morning", "wtd", final))
    return out


# ── the identity everything rests on ─────────────────────────────────────────

@pytest.mark.parametrize("week,parts", REAL_WEEKS.items())
def test_friday_final_equals_usda_published_5area(fc, week, parts):
    """Summed with nulls as zero, the daily regions ARE the published figure.

    Not approximately. If this ever drifts, the forecast is estimating a
    different number from the one USDA prints and the whole tab is wrong.
    """
    ne, iamn, published = parts
    fri = pd.Timestamp(week) + pd.Timedelta(days=4)
    rows = [(fri, "Nebraska", "morning", "wtd", ne),
            (fri, "Iowa/Minnesota", "morning", "wtd", iamn),
            # USDA publishes the skeleton for a withheld region with a null
            # volume; it must land as zero, not as a missing row.
            (fri, "Kansas", "morning", "wtd", None),
            (fri, "TX/OK/NM", "morning", "wtd", None)]
    cps = fc["wtd_checkpoints"](_vol(rows))
    assert len(cps) == 1
    assert cps.iloc[0]["wtd"] == published


def test_suppressed_region_is_zero_not_missing(fc):
    """A null volume must not drop the whole checkpoint or skew the sum."""
    fri = pd.Timestamp("2026-09-25")
    allnull = fc["wtd_checkpoints"](_vol([
        (fri, "Kansas", "morning", "wtd", None),
        (fri, "TX/OK/NM", "morning", "wtd", None)]))
    assert len(allnull) == 1 and allnull.iloc[0]["wtd"] == 0


# ── keying ───────────────────────────────────────────────────────────────────

def test_week_start_survives_a_holiday_release(fc):
    """Monday and Tuesday releases of the same week must key identically.

    report_date minus seven days alone would put a Tuesday release on the
    previous TUESDAY, and every join against the daily frame -- which is keyed
    on the Monday of the trading week -- would then quietly find nothing.
    """
    monday = pd.Series([pd.Timestamp("2026-09-28")])
    tuesday = pd.Series([pd.Timestamp("2026-09-29")])
    assert fc["_week_start"](monday).iloc[0] == pd.Timestamp("2026-09-21")
    assert fc["_week_start"](tuesday).iloc[0] == pd.Timestamp("2026-09-21")


def test_weekly_series_dedupes_the_header_field(fc):
    """previous_week_head_count repeats on every row of the report."""
    price = pd.DataFrame({
        "report_date": [pd.Timestamp("2026-09-28")] * 4,
        "previous_week_head_count": [30541.0] * 4,
    })
    s = fc["weekly_5area_head"](price)
    assert len(s) == 1
    assert s.loc[pd.Timestamp("2026-09-21")] == 30541.0


# ── cut ordering ─────────────────────────────────────────────────────────────

def test_cuts_order_by_when_they_appear(fc):
    """The 1:30 pm cut of day D precedes the final for D, which precedes D+1.

    USDA publishes the afternoon partial on the trading day and the file that
    finalises it the next morning, so sorting on the cut NAME would put
    "morning" first and read a partial as the latest word.
    """
    mon, tue = pd.Timestamp("2026-09-28"), pd.Timestamp("2026-09-29")
    cps = fc["wtd_checkpoints"](_vol([
        (tue, "Nebraska", "afternoon", "wtd", 2165),
        (mon, "Nebraska", "morning", "wtd", 699),
        (mon, "Nebraska", "afternoon", "wtd", 400),
    ]))
    seq = list(zip(cps["weekday"], cps["cut"]))
    assert seq == [(0, "afternoon"), (0, "morning"), (1, "afternoon")]
    # and the last row really is the newest thing published
    assert cps.iloc[-1]["wtd"] == 2165


# ── the forecast itself ──────────────────────────────────────────────────────

def _history(n_weeks, final_minus_cut, start="2026-01-05"):
    """n_weeks of identical weeks: Friday cut 40,000 then `final_minus_cut` more."""
    rows, finals = [], {}
    base = pd.Timestamp(start)
    for i in range(n_weeks):
        wk = base + pd.Timedelta(days=7 * i)
        rows += _week(wk, [(None, None), (None, None), (None, 36000),
                           (None, 36000), (40000, 40000 + final_minus_cut)])
        finals[wk] = 40000.0 + final_minus_cut
    return rows, pd.Series(finals)


def test_friday_final_means_no_forecast(fc):
    """Once the final has landed the week is a fact, not an estimate."""
    rows, finals = _history(10, 3000)
    f5 = fc["forecast_5area"](_vol(rows), finals)
    assert f5["done"] is True
    assert f5["grade"] == "final"
    assert f5["central"] == f5["wtd"] == f5["low"] == f5["high"]
    assert f5["late_median"] == 0.0


def test_analogues_come_from_the_same_point_in_the_week(fc):
    """A Friday 1:30 cut is estimated from other Friday 1:30 cuts.

    The Wednesday finals in this fixture sit 4,000 head below their week's
    close and the Friday cuts sit 3,000 below; an estimate that pooled the two
    would land between them. Pinning the exact figure is what catches a
    checkpoint filter that has quietly stopped filtering.
    """
    rows, finals = _history(10, 3000)
    cur = pd.Timestamp("2026-03-16")
    # current week: Wed/Thu finals then a Friday 1:30 cut, no Friday final yet
    rows += _week(cur, [(None, None), (None, None), (None, 36000),
                        (None, 36000), (40000, None)])
    f5 = fc["forecast_5area"](_vol(rows), finals)
    assert f5["done"] is False
    assert f5["wtd"] == 40000
    assert f5["late_median"] == 3000          # not 4,000, and not a blend
    assert f5["central"] == 43000


def test_national_step_is_additive_over_the_short_window(fc):
    """Median gap of the last FORECAST_GAP_WEEKS weeks, added -- never scaled.

    The last four gaps here are 20k; the two before them are 2k. A ratio, or a
    longer window, would both pull the answer away from 80,000 -- which is the
    regime break this short window exists to track.
    """
    weeks = pd.date_range("2026-07-06", periods=6, freq="7D")
    h5 = pd.Series([50000.0] * 6, index=weeks)
    gaps = [2000.0, 2000.0, 20000.0, 20000.0, 20000.0, 20000.0]
    nat = pd.Series([h5.iloc[i] + gaps[i] for i in range(6)], index=weeks)

    f5 = {"central": 60000.0, "low": 58000.0, "high": 65000.0}
    fn = fc["forecast_national"](f5, h5, nat)
    assert fc["FORECAST_GAP_WEEKS"] == 4 and fc["FORECAST_BAND_WEEKS"] == 6
    assert fn["gap"] == 20000.0
    assert fn["central"] == 80000.0
    # band spans the wider window, so it still remembers the old regime
    assert fn["low"] == 58000.0 + 2000.0
    assert fn["high"] == 65000.0 + 20000.0


def test_confidence_grade_tracks_how_much_has_traded(fc):
    """The grade is the accuracy warning, so it has to move with the week.

    Backtested, the busiest quarter of weeks land within a median 3% and the
    quietest are a median 36% out -- same method, same band. A tab that
    printed one number with one error bar would be hiding that.
    """
    rows, finals = _history(10, 3000)
    cur = pd.Timestamp("2026-03-16")
    quiet = rows + _week(cur, [(None, None), (None, None), (None, 1000),
                               (None, 1000), (1200, None)])
    assert fc["forecast_5area"](_vol(quiet), finals)["grade"] == "weak"

    busy = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (41000, None)])
    assert fc["forecast_5area"](_vol(busy), finals)["grade"] == "firm"

def test_the_call_does_not_move_when_the_fetch_window_rolls(fc):
    """A call that depends on WHEN you ask it cannot be scored honestly.

    The page fetches a rolling 365 days ending today, so without a cap the
    analogue pool loses its oldest week about every seven days and the
    estimate drifts with it. Replaying the real 2026-09-28 call from windows
    three weeks apart gave 61,167 / 60,897 / 60,627 — a 540-head spread on a
    call whose median miss is about 1.5%, so more than a third of the error
    being measured was an artefact of the clock.

    Both the scorecard and the settled tiles replay past calls, so this is
    load-bearing for anything the page claims about its own accuracy.
    """
    # 30 identical weeks, then one that differs, so a pool that reaches past
    # the cap would pick up a different median than one that stops at it.
    rows, finals = [], {}
    base = pd.Timestamp("2026-01-05")
    for i in range(30):
        wk = base + pd.Timedelta(days=7 * i)
        late = 9000 if i < 6 else 3000          # the OLD weeks are the odd ones
        rows += _week(wk, [(None, None), (None, None), (None, 36000),
                           (None, 36000), (40000, 40000 + late)])
        finals[wk] = 40000.0 + late
    finals = pd.Series(finals)
    cur = base + pd.Timedelta(days=7 * 30)
    rows += _week(cur, [(None, None), (None, None), (None, 36000),
                        (None, 36000), (40000, None)])
    vol = _vol(rows)

    # Three fetch windows, each dropping more of the old, unusual weeks.
    calls = []
    for drop_weeks in (0, 3, 6):
        start = base + pd.Timedelta(days=7 * drop_weeks)
        f = fc["forecast_5area"](vol[vol["trade_date"] >= start],
                                 finals[finals.index >= start])
        calls.append(f["central"])
        assert f["n"] <= fc["FORECAST_MAX_ANALOGUES"]

    assert len(set(calls)) == 1, (
        f"the call moved with the fetch window: {calls} — the analogue cap is "
        f"not holding the pool steady")


# ── the narrowing is gated on maturity ───────────────────────────────────────
#
# `front` is the previous checkpoint's share of the current one. Early in the
# week both terms are a few hundred head, so the ratio is noise -- and
# selecting on noise cut the analogue pool from 20 weeks to about 7. Measured
# over 455 (week, checkpoint) pairs, on the rows where the narrowing actually
# fired below the weak line: 28.8% median absolute error narrowed against
# 23.7% unnarrowed. Above the line it is what makes the forecast work at all,
# 6.7% against 14.2% once the week is fully traded.
#
# GATING IS NOT SELECTING. Choosing analogues BY maturity was tried on
# 2026-10-02 and is worse than choosing by front-loading (12.2% against 7.8%).
# That stands; the pool is still chosen on `front`. What is gated is when
# `front` is allowed to choose at all.


def test_the_weak_line_is_one_constant_not_three(fc):
    """
    It labels the call AND gates the narrowing, because it is the same
    judgement about the same threshold. A second literal 0.50 in the grade
    ladder is how the two drift apart.
    """
    assert fc["FORECAST_WEAK_MATURITY"] == 0.50
    src = APP.read_text(encoding="utf-8")
    start = src.index("def forecast_5area(")
    body = src[start:src.index("\ndef ", start + 10)]
    assert "maturity >= FORECAST_WEAK_MATURITY" in body
    assert "maturity >= 0.50" not in body, "the grade ladder still hardcodes it"


def test_a_green_week_does_not_narrow(fc):
    """
    The whole change. Ten identical past weeks make `front` match everywhere,
    so the narrowing WOULD fire -- it is the maturity gate that stops it, and
    the pool stays whole.
    """
    rows, finals = _history(10, 3000)
    cur = pd.Timestamp("2026-03-16")
    # 1,200 head against a ~43,000 typical week: maturity ~0.03
    green = rows + _week(cur, [(None, None), (None, None), (None, 1000),
                               (None, 1000), (1200, None)])
    f = fc["forecast_5area"](_vol(green), finals)
    assert f["maturity"] < fc["FORECAST_WEAK_MATURITY"]
    assert f["narrowed"] is False
    assert f["n"] == 10, f["n"]          # every past week, not a front-matched few


def test_a_mature_week_still_narrows(fc):
    """
    The gate must not switch the narrowing off altogether -- above the line it
    is the difference between 6.7% and 14.2%.
    """
    rows, finals = _history(10, 3000)
    cur = pd.Timestamp("2026-03-16")
    busy = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (40000, None)])
    f = fc["forecast_5area"](_vol(busy), finals)
    assert f["maturity"] >= fc["FORECAST_WEAK_MATURITY"]
    assert f["narrowed"] is True


def test_maturity_is_known_before_the_pool_is_chosen(fc):
    """
    The gate reads `maturity`, which used to be computed below the narrowing.
    Moving it up is what makes the gate possible, and moving it back down
    would be a NameError rather than a quiet wrong answer -- but only if the
    order is actually what this asserts.
    """
    src = APP.read_text(encoding="utf-8")
    start = src.index("def forecast_5area(")
    body = src[start:src.index("\ndef ", start + 10)]
    assert body.index("maturity = ") < body.index("pool, narrowed = hist, False")


def test_the_gate_does_not_touch_a_week_with_no_typical(fc):
    """
    maturity is NaN when there is no history to measure against, and
    `NaN >= 0.50` is False -- so the narrowing is skipped rather than raising
    or silently firing. Skipping is the safe side: the full pool.
    """
    rows, finals = _history(1, 3000)
    cur = pd.Timestamp("2026-01-12")
    one = rows + _week(cur, [(None, None), (None, None), (None, 20000),
                             (None, 20000), (30000, None)])
    f = fc["forecast_5area"](_vol(one), finals)
    assert f["narrowed"] is False


# ── too green to forecast ────────────────────────────────────────────────────
#
# Measured over 338 sub-0.50 (week, checkpoint) pairs on the live feed:
#
#   * the central is NOT a floor -- the actual lands at or above it on 50% of
#     checkpoints, and 50% / 50% / 48% across 0-5%, 5-20% and 20-50% maturity.
#     The page used to tell the reader to treat it as a floor. That was false.
#   * it does not beat ignoring the week: closer than the recent-weeks median
#     on 153 of 340, 45% against a coin flip's 50%.
#   * the band does not rescue it: 75% coverage at a median width of 86% OF
#     THE WEEK, against the recent-weeks band's 67% at 64%.
#
# So below the weak line the page prints the confirmed count and what recent
# weeks did, and no call on this week.


def test_too_green_tracks_the_weak_line(fc):
    rows, finals = _history(10, 3000)
    cur = pd.Timestamp("2026-03-16")
    green = rows + _week(cur, [(None, None), (None, None), (None, 1000),
                               (None, 1000), (1200, None)])
    f = fc["forecast_5area"](_vol(green), finals)
    assert f["maturity"] < fc["FORECAST_WEAK_MATURITY"]
    assert f["too_green"] is True

    busy = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (40000, None)])
    g = fc["forecast_5area"](_vol(busy), finals)
    assert g["maturity"] >= fc["FORECAST_WEAK_MATURITY"]
    assert g["too_green"] is False


def test_a_finished_week_is_never_too_green(fc):
    """
    `done` means Friday's final has landed and the number is a fact, not an
    estimate. Suppressing THAT would hide the answer.
    """
    rows, finals = _history(10, 3000)
    cur = pd.Timestamp("2026-03-16")
    shut = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (40000, 43000)])
    f = fc["forecast_5area"](_vol(shut), finals)
    assert f["done"] is True
    assert f["too_green"] is False


def test_an_unknown_maturity_is_treated_as_green(fc):
    """
    No history to measure against is not a licence to forecast. NaN must not
    fall through a `<` comparison into the confident branch.

    Maturity is NaN only when NOTHING precedes the live week -- one prior week
    is enough to give a typical, which is why this builds a published series
    that starts at the current week rather than a short one.
    """
    rows, _ = _history(3, 3000)
    cur = pd.Timestamp("2026-01-26")
    rows += _week(cur, [(None, None), (None, None), (None, 20000),
                        (None, 20000), (30000, None)])
    finals = pd.Series({cur: 43000.0})          # nothing published before `cur`
    f = fc["forecast_5area"](_vol(rows), finals)
    assert f["maturity"] != f["maturity"]       # NaN
    assert f["too_green"] is True


def test_the_recent_range_brackets_the_typical(fc):
    """
    What the tiles show in place of a call. p10-p90 and the median come from
    one sample, so they have to be ordered.
    """
    rows, finals = _history(13, 3000)
    cur = pd.Timestamp("2026-04-06")
    green = rows + _week(cur, [(None, None), (None, None), (None, 500),
                               (None, 500), (600, None)])
    f = fc["forecast_5area"](_vol(green), finals)
    assert f["recent_lo"] <= f["typical"] <= f["recent_hi"]


def test_the_national_half_carries_a_recent_range_too(fc):
    """Step 2 has nothing to carry across when step 1 made no call."""
    rows, finals = _history(13, 3000)
    cur = pd.Timestamp("2026-04-06")
    green = rows + _week(cur, [(None, None), (None, None), (None, 500),
                               (None, 500), (600, None)])
    f = fc["forecast_5area"](_vol(green), finals)
    n = fc["forecast_national"](f, finals, finals * 1.5)
    assert n["recent_lo"] <= n["recent_mid"] <= n["recent_hi"]


def test_the_page_does_not_call_a_green_week_a_floor():
    """
    The specific false claim this change removes. It is worth a test because
    it is prose, and prose drifting from the measurement is this repo's
    recurring defect.

    Read through ast rather than as text: the comment explaining why the
    wording went necessarily QUOTES the wording, so a substring search over
    the source finds it forever. ast sees the string literals and no comments.
    """
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    grades = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_GRADE"):
            grades = node.value
    assert grades is not None, "_GRADE is gone"
    text = " ".join(n.value for n in ast.walk(grades)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str))
    assert "floor, not a forecast" not in text
    assert "Too early to forecast" in text


def test_the_page_branches_on_too_green_everywhere_it_quotes_a_call():
    """
    Four places quote the call: the two tiles, Step 1 and Step 2. Missing one
    leaves a forecast on screen under a heading that says there isn't one.
    """
    src = APP.read_text(encoding="utf-8")
    # the page asks `no_call` now -- too_green is one of its two reasons, and
    # branching on it alone would let a thin-pool call through
    assert src.count('f5["no_call"]') >= 4, src.count('f5["no_call"]')
    for marker in ('5-Area &mdash; recent weeks', 'National &mdash; recent weeks',
                   'too little to', 'No 5-Area call to carry across yet'):
        assert marker in src, marker


# -- a pool too thin to forecast from ----------------------------------------
#
# Measured over 115 at-or-above-0.50 checkpoints, by pool depth:
#
#     pool <=3    +81.2% median signed error, actual at or below the call 0/11
#     pool 4-6    +56.7%,                     actual at or below the call 0/13
#     pool 7-10    +5.7%
#     pool 16-21   +3.0%, median absolute 9.1%
#
# Nothing checked, so a two-week pool printed with "Firm" confidence. Every one
# of those calls is Oct-Dec 2025, the start of the daily history -- which is
# also why this tab's headline accuracy used to read 13.6%. On pools of 10 or
# more it is 9.2% with a +1.4% bias.


def test_a_thin_pool_blocks_the_call_even_on_a_mature_week(fc):
    """
    The point. Maturity says this week has traded; it says nothing about
    whether there is any history to measure the rest against.
    """
    rows, finals = _history(3, 3000)          # only 3 analogue weeks
    cur = pd.Timestamp("2026-01-26")
    busy = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (40000, None)])
    f = fc["forecast_5area"](_vol(busy), finals)
    assert f["maturity"] >= fc["FORECAST_WEAK_MATURITY"]
    assert f["too_green"] is False            # the week is fine
    assert f["thin_pool"] is True             # the history is not
    assert f["no_call"] is True
    assert f["grade"] == "thin"


def test_a_full_pool_on_a_mature_week_still_calls(fc):
    rows, finals = _history(13, 3000)
    cur = pd.Timestamp("2026-04-06")
    busy = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (40000, None)])
    f = fc["forecast_5area"](_vol(busy), finals)
    assert f["thin_pool"] is False
    assert f["no_call"] is False
    assert f["n"] >= fc["FORECAST_MIN_ANALOGUES"]


def test_the_minimum_sits_above_the_catastrophic_pool_sizes(fc):
    """<=6 ran +57% to +81%; >=10 is +1.4%. The floor has to clear the first."""
    assert fc["FORECAST_MIN_ANALOGUES"] >= 7
    assert fc["FORECAST_MIN_ANALOGUES"] <= 16


def test_a_closed_week_is_never_blocked(fc):
    """
    Friday's final is the answer. Suppressing it for want of analogues would
    hide a number that needs none.
    """
    rows, finals = _history(2, 3000)
    cur = pd.Timestamp("2026-01-19")
    shut = rows + _week(cur, [(None, None), (None, None), (None, 36000),
                              (None, 36000), (40000, 43000)])
    f = fc["forecast_5area"](_vol(shut), finals)
    assert f["done"] is True
    assert f["thin_pool"] is False
    assert f["no_call"] is False


def test_the_page_asks_no_call_not_too_green():
    """
    Two reasons, one outcome. A page still branching on `too_green` would
    print a three-week-pool call on a mature week -- the +81% case.
    """
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("with tab_fcst:") if "with tab_fcst:" in src
               else src.index("Monday Print Forecast"):]
    assert 'f5["too_green"]' not in body or 'f5["no_call"]' in body
    assert src.count('f5["no_call"]') >= 4


def test_every_grade_has_a_rendering():
    """
    forecast_5area can return "thin" now. A grade without an entry is a
    KeyError on the live page, which is worse than a wrong label.
    """
    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    produced = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "grade"
                and isinstance(node.value, ast.Constant)):
            produced.add(node.value.value)
    assert produced, "no grade assignments found"
    start = src.index("_GRADE = {")
    rendered = src[start:src.index("_gc, _gl, _gt = _GRADE[", start)]
    for g in produced:
        assert f'"{g}":' in rendered, g


# -- a thin POOL and a thin HISTORY are two different things -----------------
#
# The guard was written on evidence from Oct-Dec 2025, where a small pool meant
# a short history -- nothing else stood behind the checkpoint. It was applied
# to `pool`, which is `hist` AFTER the front-loading narrowing, so from 2026 it
# also fired on weeks with deep history and an unusual shape. Those backtest at
# 12.3% median absolute error against 24.7% for the unnarrowed pool and 26.7%
# for the recent-weeks median the page showed instead: it was refusing the best
# number it had. Live casualty 2026-10-09, front-loading 0.748, 51 weeks of
# history, 5 of them a similar shape.

def _shaped(monday, thu, fri_cut, final):
    """One week with a chosen front-loading: thu/fri_cut is the ratio."""
    return _week(monday, [(None, None), (None, None), (None, thu - 4000),
                          (None, thu), (fri_cut, None)]), float(final)


def _mixed_history(n_plain, n_rare, start="2025-01-06"):
    """`n_plain` weeks front-loaded 0.90, then `n_rare` front-loaded 0.70.

    The two shapes carry DIFFERENT late trade -- 3,000 head against 8,000 --
    so which pool a call is built from is visible in the answer rather than
    having to be asserted on a count.
    """
    rows, finals = [], {}
    base = pd.Timestamp(start)
    for i in range(n_plain):
        wk = base + pd.Timedelta(days=7 * i)
        r, f = _shaped(wk, 36000, 40000, 43000)
        rows += r
        finals[wk] = f
    for j in range(n_rare):
        wk = base + pd.Timedelta(days=7 * (n_plain + j))
        r, f = _shaped(wk, 28000, 40000, 48000)
        rows += r
        finals[wk] = f
    return rows, pd.Series(finals), base + pd.Timedelta(days=7 * (n_plain + n_rare))


def test_a_rare_shaped_week_with_deep_history_still_calls(fc):
    """
    THE REGRESSION. 26 past weeks stand at this checkpoint and only 6 share
    the week's shape. Gating on the narrowed pool refused the call outright;
    gating on the history behind the checkpoint keeps it.
    """
    rows, finals, cur = _mixed_history(20, 6)
    r, _ = _shaped(cur, 28000, 40000, 0)          # front 0.70, like the rare six
    f = fc["forecast_5area"](_vol(rows + r), finals)

    assert f["maturity"] >= fc["FORECAST_WEAK_MATURITY"]
    assert f["thin_pool"] is False, "deep history was read as no history"
    assert f["no_call"] is False
    assert f["n_hist"] == 26                       # what stands at this point
    assert f["narrowed"] is True
    assert f["n"] == 6                             # what resembles this week

    # AND IT IS THE NARROWED CALL, not the full pool's. The six rare weeks ran
    # 8,000 head late; the twenty plain ones ran 3,000. 48,000 is the first.
    assert f["central"] == pytest.approx(48000.0)


def test_the_same_narrow_pool_on_a_SHALLOW_history_is_still_refused(fc):
    """
    The other half, and why this is not simply a lower threshold. Same six
    analogue weeks, same shape, same maturity -- but nothing else behind the
    checkpoint. That is the population the +57%/+81% evidence describes and it
    is still blocked.
    """
    rows, finals, cur = _mixed_history(0, 6)
    r, _ = _shaped(cur, 28000, 40000, 0)
    f = fc["forecast_5area"](_vol(rows + r), finals)

    assert f["n_hist"] == 6
    assert f["thin_pool"] is True
    assert f["no_call"] is True
    assert f["grade"] == "thin"


def test_n_hist_is_the_history_and_n_is_the_pool(fc):
    """
    They are equal until narrowing fires and must not be read for each other:
    the no-call sentence quotes "past weeks stand at this same point in the
    week", which is the history, while the band and the central come from the
    pool. Printing `n` there told a reader 51 weeks of history were 5.
    """
    rows, finals, cur = _mixed_history(20, 6)
    r, _ = _shaped(cur, 28000, 40000, 0)
    narrowed = fc["forecast_5area"](_vol(rows + r), finals)
    assert narrowed["n_hist"] > narrowed["n"]

    plain, finals2 = _history(13, 3000)
    cur2 = pd.Timestamp("2026-04-06")
    same = plain + _week(cur2, [(None, None), (None, None), (None, 36000),
                                (None, 36000), (40000, None)])
    f = fc["forecast_5area"](_vol(same), finals2)
    assert f["n_hist"] == f["n"], "identical weeks should narrow to themselves"


def test_the_no_call_sentence_quotes_the_history_not_the_pool():
    """A standing guard: the two are different numbers whenever narrowing
    fires, and the sentence is about the history."""
    src = APP.read_text(encoding="utf-8")
    i = src.index("past weeks stand at this same point")
    window = src[i - 300:i]
    assert 'f5["n_hist"]' in window, "the no-call sentence is back on the pool"
