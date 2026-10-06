"""Proof that the packer-leverage shares mean what the page says they mean.

Four ways this would be wrong without raising, and a share that is wrong
raises nothing by construction — it is a number between 0 and 1 either way:

  * the numerator and denominator taken from different reports, so the "share"
    divides cattle slaughtered by cattle purchased and tracks neither;
  * imported head dropped, understating committed supply by a few points;
  * a derived total instead of USDA's, so the shares keep summing to 100% while
    describing less than the whole reported kill;
  * coverage divided by a single holiday week, printing a supply spike that is
    only the calendar.

    python -m pytest tests/test_packer_leverage.py -q
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "cash_trade"))

import leverage as lev  # noqa: E402


def _mix_rows(weeks):
    """weeks: list of (date, formula, forward, neg, grid, imp_formula, total)."""
    out = []
    for d, f, fw, n, g, impf, tot in weeks:
        out.append({
            "report_date": d,
            "B_dom_formula_head_count": f"{f:,}",
            "B_dom_forward_head_count": f"{fw:,}",
            "B_dom_neg_head_count": f"{n:,}",
            "B_dom_neg_grid_head_count": f"{g:,}",
            "B_imp_formula_head_count": f"{impf:,}" if impf else None,
            "B_imp_forward_head_count": None,
            "B_imp_neg_head_count": None,
            "B_imp_neg_grid_head_count": None,
            "B_total_head_count": f"{tot:,}",
        })
    return out


# ── the shares ───────────────────────────────────────────────────────────────

def test_shares_use_usdas_own_total_not_a_derived_one():
    """If USDA ever adds a fifth purchase type, a derived total hides it.

    Summing the four parts would keep the shares adding to exactly 100% while
    the denominator quietly stopped being the whole reported kill. Using the
    published total instead makes that show up as shares that no longer sum to
    one — visible, rather than invisible.
    """
    # total is 10,000 ABOVE the four parts, as if a fifth bucket existed
    rows = _mix_rows([("09/28/2026", 200_000, 20_000, 60_000, 30_000, 0, 320_000)])
    m = lev._mix_frame(rows)
    assert m.iloc[0]["total"] == 320_000                      # USDA's, not 310,000
    assert m.iloc[0]["negotiated_pct"] == pytest.approx(60_000 / 320_000)
    four = sum(m.iloc[0][k] for k in lev.MIX)
    assert four == 310_000 and four != m.iloc[0]["total"]


def test_imported_head_count_as_committed_supply():
    """An imported formula steer is still supply nobody had to bid for."""
    rows = _mix_rows([("09/28/2026", 200_000, 20_000, 60_000, 30_000, 10_000, 320_000)])
    m = lev._mix_frame(rows)
    assert m.iloc[0]["formula"] == 210_000
    assert m.iloc[0]["negotiated_pct"] == pytest.approx(60_000 / 320_000)


def test_negotiated_grid_is_not_folded_into_the_headline():
    """The two readings differ by a third and the page must not pick silently.

    Grid's base is negotiated in the week, so it belongs with cash for "did
    the packer have to transact" and apart from it for "what discovered a cash
    price". Both are exposed; neither is substituted for the other.
    """
    rows = _mix_rows([("09/28/2026", 200_000, 20_000, 60_000, 30_000, 0, 310_000)])
    r = lev._mix_frame(rows).iloc[0]
    assert r["negotiated_pct"] == pytest.approx(60_000 / 310_000)      # headline
    assert r["must_buy_pct"] == pytest.approx(90_000 / 310_000)        # the looser one
    assert r["committed_pct"] == pytest.approx(1 - 90_000 / 310_000)
    assert r["must_buy_pct"] > r["negotiated_pct"] * 1.3


# ── the committed book ───────────────────────────────────────────────────────

def _committed_rows(weeks):
    out = []
    for d, com, dlv in weeks:
        out.append({"report_date_end": d, "purchasing_basis": "Committed",
                    "current_volume": f"{com:,}"})
        out.append({"report_date_end": d, "purchasing_basis": "Delivered",
                    "current_volume": f"{dlv:,}"})
    return out


def test_signings_vs_pace_uses_four_weeks_not_one_holiday_week():
    """A short week halves the denominator and fakes a move in the ratio.

    Thanksgiving, July 4th and Christmas all do it. The ratio compares two
    weekly FLOWS — head committed during the week against head shipped — so a
    holiday week's shipments would make new signings look like a surge when
    nothing moved but the calendar.
    """
    weeks = [(f"0{i}/01/2026", 400_000, 350_000) for i in range(1, 5)]
    weeks.append(("05/01/2026", 400_000, 175_000))      # the holiday week
    c = lev._committed_frame(_committed_rows(weeks))
    last = c.iloc[-1]
    assert last["delivered"] == 175_000
    naive = 400_000 / 175_000
    assert last["signings_vs_pace"] < naive * 0.65
    assert 1.2 < last["signings_vs_pace"] < 1.5


def test_committed_and_delivered_are_pivoted_not_filtered():
    """Both bases share a week and a column; reading one row would lose half."""
    c = lev._committed_frame(_committed_rows([("09/28/2026", 409_230, 368_246)]))
    assert len(c) == 1
    assert c.iloc[0]["committed"] == 409_230
    assert c.iloc[0]["delivered"] == 368_246


# ── the thing that must never happen ────────────────────────────────────────

def test_the_module_never_reads_the_purchase_side_report():
    """Slaughter and purchases are different populations on different clocks.

    LM_CT154's 9/28 row is head PURCHASED that week; LM_CT153's is head
    SLAUGHTERED that week, bought whenever. Their ratio ran 0.83 to 1.32 over
    six weeks of 2026 — so a "share" built from one over the other looks like
    a share, moves like a share, and measures nothing. Every share here comes
    from a single row of a single report.
    """
    src = (ROOT / "apps" / "cash_trade" / "leverage.py").read_text(encoding="utf-8")
    # the negotiated-purchases slug must not appear as a fetched id
    assert "CT154" not in src.replace("LM_CT154", "")   # prose mention is fine
    assert "2481" not in src
    assert lev.CT153_ID == 2480 and lev.CT142_ID == 2472


def test_percentile_refuses_a_sample_too_short_to_mean_anything():
    """Better no percentile than one built on five weeks."""
    rows = _mix_rows([(f"0{i}/01/2026", 200_000, 20_000, 60_000, 30_000, 0, 310_000)
                      for i in range(1, 6)])
    m = lev._mix_frame(rows)
    assert lev.percentile(m, "negotiated_pct", 0.2) != lev.percentile(m, "negotiated_pct", 0.2)

# ── the cash need ────────────────────────────────────────────────────────────

def _run(weeks_of):
    """weeks_of: list of (neg, grid) — formula fills the rest of a 350k kill."""
    rows = []
    for i, (n, g) in enumerate(weeks_of, start=1):
        rows.append(("%02d/01/2026" % i, 350_000 - n - g - 20_000, 20_000, n, g, 0, 350_000))
    return lev._mix_frame(_mix_rows(rows))


def test_cash_need_averages_rather_than_quoting_last_week():
    """One week is noise; the alternative to averaging is a worse estimate.

    Four weeks of 60k, 80k, 70k, 90k is a 75k run rate. Quoting the last week
    would say 90k — 20% high — and quoting the first would say 60k. Measured
    on the real series a four-week mean lands within a median ~8% of the week
    that follows, which is the number the page prints beside it.
    """
    m = _run([(60_000, 30_000), (80_000, 30_000), (70_000, 30_000), (90_000, 30_000)])
    n = lev.cash_need(m, weeks=4)
    assert n["cash"] == pytest.approx(75_000)
    assert n["cash"] != m.iloc[-1]["negotiated"]
    # the band is the real high and low, not a sigma: with four points a
    # spread can be pointed at and a standard deviation is decoration.
    assert n["cash_lo"] == 60_000 and n["cash_hi"] == 90_000
    assert n["weeks"] == 4


def test_cash_need_reports_both_readings_of_grid():
    """Same rule as the headline: show both, substitute neither."""
    m = _run([(70_000, 30_000)] * 4)
    n = lev.cash_need(m, weeks=4)
    assert n["cash"] == pytest.approx(70_000)
    assert n["must"] == pytest.approx(100_000)


def test_cash_need_window_shorter_than_asked_for_is_reported_honestly():
    """Two weeks of history must not be presented as a four-week rate."""
    m = _run([(70_000, 30_000), (80_000, 30_000)])
    n = lev.cash_need(m, weeks=4)
    assert n["weeks"] == 2
    assert n["cash"] == pytest.approx(75_000)


def test_need_accuracy_is_measured_not_asserted():
    """The error claim on the page must come from the data, not a constant.

    A perfectly flat series has to score ~0% and a wildly swinging one has to
    score badly, or the figure beside the run rate is decoration.
    """
    flat = _run([(70_000, 30_000)] * 20)
    a = lev.need_accuracy(flat, weeks=4)
    assert a["cash"]["median"] == pytest.approx(0.0, abs=1e-9)

    swing = _run([(40_000, 30_000) if i % 2 else (100_000, 30_000) for i in range(20)])
    b = lev.need_accuracy(swing, weeks=4)
    assert b["cash"]["median"] > 0.15


def test_need_accuracy_declines_to_speak_on_a_short_series():
    """Fewer weeks than the window plus a margin is no basis for a claim."""
    assert lev.need_accuracy(_run([(70_000, 30_000)] * 5), weeks=4) == {}
    assert lev.cash_need(lev._mix_frame([])) == {}

# ── the forward delivery schedule ───────────────────────────────────────────

def _sched_rows(months, totals, lastyr, date="09/28/2026"):
    """Lay the breakdown out exactly as AMS does: details, Totals, Last Yr."""
    rows = []
    for mon, yy in months:                       # six basis rows per month
        for basis in ("Feb", "Apr", "Jun", "Aug", "Oct", "Dec"):
            rows.append({"report_date": date, "left_title": f"{mon} '{yy}/{basis}",
                         "cumulative_total_for_month": None, "new_last_week": None})
    for (mon, _), tot in zip(months, totals):
        rows.append({"report_date": date, "left_title": f"Total {mon} Deliveries",
                     "cumulative_total_for_month": f"{tot:,}", "new_last_week": None})
    for (mon, _), ly in zip(months, lastyr):
        rows.append({"report_date": date, "left_title": f"Last Yr {mon} Deliveries",
                     "cumulative_total_for_month": f"{ly:,}", "new_last_week": None})
    return rows


def test_repeated_month_labels_are_resolved_by_position_not_name():
    """The window spans two years, so every month name appears twice.

    On the real 2026-09-28 report "Total Sep Deliveries" is 86,305 for Sep '26
    and 9,453 for Sep '27. Anything keyed on the label keeps whichever came
    last — the far month — and then reports a near-month book an order of
    magnitude too small, with no error anywhere.
    """
    months = [("Sep", "26"), ("Oct", "26"), ("Sep", "27"), ("Oct", "27")]
    d = lev._schedule_frame(_sched_rows(months, [86_305, 117_500, 9_453, 5_963],
                                        [108_567, 176_293, 86_305, 117_500]))
    assert len(d) == 4
    near = d[(d["month"] == "Sep") & (d["year"] == 2026)].iloc[0]
    far = d[(d["month"] == "Sep") & (d["year"] == 2027)].iloc[0]
    assert near["committed"] == 86_305        # not 9,453
    assert far["committed"] == 9_453
    assert near["last_year"] == 108_567
    assert near["vs_last_year"] == pytest.approx(86_305 / 108_567 - 1)


def test_schedule_reconciles_to_the_published_book_total():
    """The monthly totals adding back to USDA's own figure is the audit.

    On 2026-09-28 the sixteen months sum to 714,623, which is exactly the
    "Cumulative Total for Listed Months" on the report. If the row layout ever
    shifts, this stops matching instead of quietly mis-attributing a month.
    """
    months = [("Sep", "26"), ("Oct", "26"), ("Nov", "26")]
    d = lev._schedule_frame(_sched_rows(months, [86_305, 117_500, 110_103],
                                        [108_567, 176_293, 168_750]))
    assert lev.reconciles(d, 313_908)
    assert not lev.reconciles(d, 313_907)
    assert not lev.reconciles(pd.DataFrame(), 313_908)


def test_a_slipped_layout_returns_nothing_rather_than_wrong_months():
    """If the Total rows stop lining up, every figure after the slip is wrong.

    Returning empty makes the page say it has no schedule; mis-attributing
    would have it print a confident table of the wrong months.
    """
    rows = _sched_rows([("Sep", "26"), ("Oct", "26")], [86_305, 117_500],
                       [108_567, 176_293])
    for r in rows:
        if r["left_title"] == "Total Sep Deliveries":
            r["left_title"] = "Total Mar Deliveries"      # the slip
    assert lev._schedule_frame(rows).empty


def test_near_months_sums_only_the_front_of_the_book():
    """Cattle contracted for next spring do not fill a kill on Thursday."""
    months = [("Sep", "26"), ("Oct", "26"), ("Nov", "26"), ("Dec", "26")]
    d = lev._schedule_frame(_sched_rows(months, [86_305, 117_500, 110_103, 93_357],
                                        [108_567, 176_293, 168_750, 177_195]))
    n = lev.near_months(d, 3)
    assert n["committed"] == 313_908                      # Dec excluded
    assert n["last_year"] == 453_610
    assert n["change"] == pytest.approx(313_908 / 453_610 - 1)


def test_the_weekly_flow_ratio_is_no_longer_called_coverage():
    """It was shipped as "weeks of coverage" and is not weeks of anything.

    LM_CT142's Committed column is head committed DURING the week — the daily
    sibling's acc_current_volume accumulates within the week and ends on this
    exact figure. A median of 1.03 with sd 0.08 over sixteen years is two
    flows in steady state, not a stock over a flow.
    """
    src = (ROOT / "apps" / "cash_trade" / "leverage.py").read_text(encoding="utf-8")
    assert "coverage_weeks" not in src
    c = lev._committed_frame(_committed_rows([(f"0{i}/01/2026", 400_000, 350_000)
                                              for i in range(1, 6)]))
    assert "signings_vs_pace" in c
    assert c.iloc[-1]["signings_vs_pace"] == pytest.approx(400_000 / 350_000)

# ── currentness: weight against its own trend ───────────────────────────────

def _price_rows(weeks):
    """weeks: list of (date, basis, class, head, weight)."""
    return pd.DataFrame([
        {"report_date": pd.Timestamp(d), "current_period": "WEEKLY WEIGHTED AVERAGES",
         "selling_basis_desc": b, "class_description": c,
         "head_count": float(h), "weight_range_avg": float(w)}
        for d, b, c, h, w in weeks])


def test_weights_are_head_weighted_not_averaged():
    """A 50-head heifer lot is not half the signal of a 3,000-head steer lot.

    A plain mean of the two class figures would let a tiny heifer print drag
    the week, which is the same error the price combine avoids.
    """
    d = _price_rows([
        ("2026-10-05", "Live", "Steer", 3000, 1600),
        ("2026-10-05", "Live", "Heifer", 50, 1200),
    ])
    w = lev.weight_frame(d)
    assert len(w) == 1
    got = w.iloc[0]["Live"]
    assert got == pytest.approx((3000 * 1600 + 50 * 1200) / 3050)
    assert got > 1590                      # not the 1,400 a plain mean gives


def test_trend_is_fitted_on_the_same_week_of_prior_years():
    """Comparing against an annual mean would import the season.

    Cattle are heavier in some weeks than others; fitting week 41 against
    week 41 removes that without a separate seasonal adjustment.
    """
    rows = []
    for yr in range(2018, 2027):
        # week 41 climbs +10/yr; week 20 is 80 lb lighter and must not count
        rows.append((f"{yr}-10-10", "Live", "Steer", 1000, 1400 + 10 * (yr - 2018)))
        rows.append((f"{yr}-05-16", "Live", "Steer", 1000, 1320 + 10 * (yr - 2018)))
    w = lev.weight_frame(_price_rows(rows))
    # the newest row is the 2026 week-41 print, exactly on trend
    c = lev.weight_context(w.sort_values("report_date"), "Live")
    assert c["slope"] == pytest.approx(10.0, abs=0.5)
    assert c["vs_trend"] == pytest.approx(0.0, abs=1.5)


def test_the_year_ago_move_is_separated_from_ordinary_drift():
    """A raw year-ago delta counts two decades of genetics as market signal.

    The real series drifts about +10 lb a year, so "+67 on the year" is
    partly a market telling you cattle are backing up and partly a trend that
    was always going to happen. The page has to show both numbers or it
    overstates the signal by the drift.
    """
    rows = []
    for yr in range(2018, 2026):
        rows.append((f"{yr}-10-10", "Live", "Steer", 1000, 1400 + 10 * (yr - 2018)))
    rows.append(("2026-10-10", "Live", "Steer", 1000, 1550))   # +80 on the year
    c = lev.weight_context(lev.weight_frame(_price_rows(rows)).sort_values("report_date"),
                           "Live")
    assert c["vs_year_ago"] == pytest.approx(80.0, abs=1)
    assert c["slope"] == pytest.approx(10.0, abs=0.5)
    # the honest signal is the move MINUS the drift, not the raw move
    assert c["vs_trend"] == pytest.approx(70.0, abs=2)
    assert c["vs_trend"] < c["vs_year_ago"]


def test_too_little_history_declines_to_quote_a_trend():
    """Three prior years is no basis for a fitted expectation."""
    rows = [(f"{yr}-10-10", "Live", "Steer", 1000, 1400) for yr in (2024, 2025, 2026)]
    c = lev.weight_context(lev.weight_frame(_price_rows(rows)).sort_values("report_date"),
                           "Live")
    assert "vs_trend" not in c and "weight" in c
    assert lev.weight_context(pd.DataFrame(), "Live") == {}
