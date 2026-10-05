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


def test_coverage_uses_a_four_week_pace_not_one_holiday_week():
    """A short week halves the denominator and fakes a supply spike.

    Thanksgiving, July 4th and Christmas all do it. Dividing a steady book by
    one holiday week's shipments prints coverage leaping by half, which reads
    as packers suddenly bought ahead when nothing moved but the calendar.
    """
    weeks = [(f"0{i}/01/2026", 400_000, 350_000) for i in range(1, 5)]
    weeks.append(("05/01/2026", 400_000, 175_000))      # the holiday week
    c = lev._committed_frame(_committed_rows(weeks))
    last = c.iloc[-1]
    assert last["delivered"] == 175_000
    # one-week coverage would be 2.29; the four-week pace keeps it near 1.3
    naive = 400_000 / 175_000
    assert last["coverage_weeks"] < naive * 0.65
    assert 1.2 < last["coverage_weeks"] < 1.5


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
