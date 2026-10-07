"""
One declaration per signal. The board renders these; nothing else defines them.

WHY A REGISTRY AND NOT TWENTY TILES WRITTEN OUT. Two consumers read the same
list -- the live board, and (later) the historical layer that asks what a
reading like today's has meant for cash. A second list would drift from the
first, and the drift would be invisible: both would render, both would be
defensible, and they would describe different signals. That is the
letter-versus-dashboard failure CLAUDE.md records twice, and this is the
generalisation of the fix `letter/rundown.py` already applies -- one assembly,
many renderers.

**`pick` MAY NOT DO ARITHMETIC ON MARKET NUMBERS.** It reaches into the bundle
and returns a value some upstream module already computed. The moment a tile
computes its own figure, this page becomes a second implementation of a number
another page already shows, and the two can disagree while both look right.
`tests/test_market_board.py` asserts it by AST: no `BinOp` anywhere in this
file. Where a figure genuinely needs deriving -- the packer-owned SHARE, which
`leverage` returns as head -- the derivation belongs in the module that owns
the data, with its own test, or the tile does not ship. It does not ship.

**EVERY SIGNAL CARRIES A BASIS STRING AND IT IS NOT OPTIONAL.** Half the traps
in CLAUDE.md are two correct numbers on different populations or different
clocks: head PURCHASED in a week against head SLAUGHTERED in it, a 7-day
rolling index window against a daily count, a 5-Area negotiated weight against
a national FI average. A tile without its basis invites exactly that
arithmetic from the reader.

**`max_age_days` IS MEASURED FROM WHEN THE NEXT PUBLICATION IS DUE**, never
from the report date. LM_CT153 reports the PRIOR week by schedule, so a
report-date rule marks it stale every Thursday on perfectly fresh data -- and
a panel that cries every week is one nobody reads in the week it matters.

**`depth` IS THE BACKTEST VERDICT, DECLARED HERE RATHER THAN DISCOVERED.**
`full` means the measured history spans the window a conditional study needs;
`partial` means it runs but over a span short enough that the page must say so
on every cell; `none` means no history claim may be made at all. Every value
below was established by live probe on 2026-10-07, not inferred from how old a
report looks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

# -- the four questions, in the market's own causal order ---------------------
#
# What beef is worth sets what the packer earns, which sets what he can pay for
# a fat, which sets what a feeder is worth. Supply is the slow backdrop behind
# all three. Ordering the cards any other way -- alphabetically, or by how
# interesting the number is -- breaks the only through-line the page has.
Q_BEEF = "What is beef worth?"
Q_PACKER = "What is the packer's position?"
Q_FEEDER = "What is a feeder worth?"
Q_SUPPLY = "What is supply doing?"

QUESTIONS = (Q_BEEF, Q_PACKER, Q_FEEDER, Q_SUPPLY)

FULL, PARTIAL, NONE = "full", "partial", "none"


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    question: str
    #: What this number IS -- report, population, unit, clock. Mandatory.
    basis: str
    #: The feed, for the provenance footer.
    source: str
    #: bundle -> value. No arithmetic; see the module docstring.
    pick: Callable
    #: "money" | "pct" | "frac" | "head" | "lb" | "date" | "ratio"
    fmt: str
    cadence: str
    #: Days past the EXPECTED next publication before the figure is stale.
    max_age_days: int
    #: bundle -> date | None, the observation this value describes.
    as_of: Callable
    depth: str
    depth_note: str
    #: Which dashboard owns this number, for the "see it in full" link.
    page: str = ""


def _g(d, *path, default=None):
    """
    Walk nested dicts/Series without arithmetic and without raising.

    A missing key returns None so the tile renders as MISSING and the page says
    so. It never substitutes zero: CLAUDE.md records that a withheld cash
    region shown as "0 head" reads as "nobody traded", which is a statement and
    a wrong one.
    """
    cur = d
    for k in path:
        if cur is None:
            return default
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            return default
    return default if cur is None else cur


# ── the signals ──────────────────────────────────────────────────────────────

SIGNALS: tuple = (

    # -- Q_BEEF ---------------------------------------------------------------
    Signal(
        key="choice_cutout",
        label="Choice cutout",
        question=Q_BEEF,
        basis="LM_XB403 PM close · 600–900 lb Choice carcass composite · $/cwt",
        source="LM_XB403",
        pick=lambda b: _g(b, "cutout", "choice", "value"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "cutout", "report_date"),
        depth=FULL,
        depth_note="2004-01-05, 22 yrs. Rows dated 2001–2003 carry a date and a null.",
        page="Beef Cutout",
    ),
    Signal(
        key="choice_5day",
        label="Choice 5-day average",
        question=Q_BEEF,
        basis="LM_XB403 · the five sessions BEFORE this print, not including it "
              "· $/cwt",
        source="LM_XB403",
        pick=lambda b: _g(b, "cutout", "choice", "avg5"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "cutout", "report_date"),
        depth=FULL,
        depth_note="Window changed to iloc[-6:-1] on 2026-10-06; it needs six rows.",
        page="Beef Cutout",
    ),
    Signal(
        key="select_cutout",
        label="Select cutout",
        question=Q_BEEF,
        basis="LM_XB403 PM close · 600–900 lb Select carcass composite · $/cwt",
        source="LM_XB403",
        pick=lambda b: _g(b, "cutout", "select", "value"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "cutout", "report_date"),
        depth=FULL, depth_note="2004-01-05, 22 yrs.",
        page="Beef Cutout",
    ),
    Signal(
        key="grading_pct",
        label="Choice & higher grading",
        question=Q_BEEF,
        basis="LSWFEDCC · % of graded carcasses · weekly · USDA's own prior-week "
              "column, never the preceding row we happen to hold",
        source="LSWFEDCC",
        pick=lambda b: _g(b, "cutout", "grading", "pct"),
        fmt="pct", cadence="weekly", max_age_days=14,
        as_of=lambda b: _g(b, "cutout", "grading", "report_date"),
        depth=PARTIAL,
        depth_note="Not probed to its start; treat any history claim as unverified.",
        page="Beef Cutout",
    ),

    # -- Q_PACKER -------------------------------------------------------------
    Signal(
        key="negotiated_share",
        label="Negotiated share of the kill",
        question=Q_PACKER,
        basis="LM_CT153 §B · cash alone, grid EXCLUDED · share of USDA's "
              "published total REPORTED kill · reports the prior week",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "lev", "mix", "negotiated_pct"),
        fmt="frac", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "mix", "week"),
        depth=FULL,
        depth_note="2008-07-21, 950 wks. The four-way split does not exist before it.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="must_buy_share",
        label="Must-buy share (cash + neg. grid)",
        question=Q_PACKER,
        basis="LM_CT153 §B · negotiated + negotiated grid ÷ published total · "
              "the wider reading, shown beside the strict one, never folded in",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "lev", "mix", "must_buy_pct"),
        fmt="frac", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "mix", "week"),
        depth=FULL, depth_note="2008-07-21, 950 wks.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="committed_share",
        label="Already-bought share (formula + forward)",
        question=Q_PACKER,
        basis="LM_CT153 §B · formula + forward ÷ published total · the kill "
              "nobody had to bid for this week",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "lev", "mix", "committed_pct"),
        fmt="frac", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "mix", "week"),
        depth=FULL, depth_note="2008-07-21, 950 wks.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="forward_book",
        label="Forward book, next 3 delivery months",
        question=Q_PACKER,
        basis="LM_CT153 §C Breakdown · head COMMITTED and not yet delivered, "
              "vs the same months a year ago · a STOCK, not a weekly flow",
        source="LM_CT153 §C",
        pick=lambda b: _g(b, "near", "change"),
        fmt="frac_signed", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "forward", "week"),
        depth=PARTIAL,
        depth_note="A 100,000-row cap truncates the OLD end: the feed reports "
                   "MIN 2011-10-03 where the real start is 2009-02-16.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="cash_need",
        label="Cash need, 4-week run rate",
        question=Q_PACKER,
        basis="LM_CT153 §B · head/wk packers HAD to transact for over the last "
              "four weeks · a RUN RATE, not a forecast of this week",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "need", "cash"),
        fmt="head", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "need", "to"),
        depth=FULL, depth_note="2008-07-21, 950 wks.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="weight_vs_trend",
        label="Live weight vs 8-yr same-week trend",
        question=Q_PACKER,
        basis="LM_CT150 · head-weighted steer+heifer live weight · against a fit "
              "on the SAME ISO WEEK of the prior 8 years, NOT against last year",
        source="LM_CT150",
        pick=lambda b: _g(b, "weight", "vs_trend"),
        fmt="lb_signed", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "weight", "week"),
        depth=FULL,
        depth_note="LM_CT150 runs to 2004-05-03, but the 8-yr trend needs eight "
                   "prior same-week points, so fitted values start ~2012.",
        page="Cash Cattle Trade",
    ),

    # -- Q_FEEDER -------------------------------------------------------------
    Signal(
        key="feeder_index",
        label="CME Feeder Cattle Index",
        question=Q_FEEDER,
        basis="Pound-weighted 12-state #1 and #1-2 M&L steers 700–899 lb · "
              "rolling 7-day window · $/cwt",
        source="JSA.CME_FEEDER_CATTLE",
        pick=lambda b: _g(b, "fci", "value"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "fci", "date"),
        depth=FULL,
        depth_note="CME_FTP_DAILY 2015-01-01, 11.75 yrs. RESTATED values only — "
                   "one row per date, no as-of column. Point-in-time starts "
                   "2026-08-19 with FCI_SNAPSHOTS.",
        page="CME Feeder Cattle Index",
    ),
    Signal(
        key="feeder_index_change",
        label="Feeder index, day on day",
        question=Q_FEEDER,
        basis="Values rounded first, THEN differenced — so a reader holding two "
              "days' prints can subtract them and get this",
        source="JSA.CME_FEEDER_CATTLE",
        pick=lambda b: _g(b, "fci", "change"),
        fmt="money_signed", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "fci", "date"),
        depth=FULL, depth_note="As the index.",
        page="CME Feeder Cattle Index",
    ),
    Signal(
        key="corn_delivered",
        label="Delivered corn, Nebraska",
        question=Q_FEEDER,
        basis="Elevator bid plus a delivery adder · $/bu DELIVERED to the "
              "feedyard, not an elevator bid · nearby delivery only",
        source="JSA.BASIS_TRACKER",
        pick=lambda b: _g(b, "corn", "NE", "price"),
        fmt="money", cadence="daily", max_age_days=14,
        as_of=lambda b: _g(b, "asof", "corn"),
        depth=PARTIAL,
        depth_note="Snapshot history not probed to its start. The ZC settlement "
                   "chain in BASIS_TRACKER reaches 2007-01-05 if a study needs one.",
        page="Fed Cattle Crush",
    ),

    # -- Q_SUPPLY -------------------------------------------------------------
    Signal(
        key="weekly_kill",
        label="Weekly FI cattle slaughter",
        question=Q_SUPPLY,
        basis="SJ_LS712 · ESTIMATE — Saturday and most of Friday are projected · "
              "week ending the Saturday AFTER publication",
        source="SJ_LS712",
        pick=lambda b: _g(b, "slaughter", "weekly", "value"),
        fmt="head", cadence="weekly", max_age_days=10,
        as_of=lambda b: _g(b, "slaughter", "weekly", "week_ending"),
        depth=NONE,
        depth_note="SJ_LS712 keeps ONE week — a 3.8 KB file, absent from both "
                   "report catalogs. A study must use NASS weekly head (1978-) "
                   "instead, which lags this by about two weeks.",
        page="Cattle Weights",
    ),
    Signal(
        key="kill_ytd",
        label="Slaughter, year to date",
        question=Q_SUPPLY,
        basis="SJ_LS712 · USDA's OWN published Change row, not our arithmetic",
        source="SJ_LS712",
        pick=lambda b: _g(b, "slaughter", "weekly", "ytd_chg_pct"),
        fmt="pct_signed", cadence="weekly", max_age_days=10,
        as_of=lambda b: _g(b, "slaughter", "weekly", "week_ending"),
        depth=NONE, depth_note="As the kill.",
        page="Cattle Weights",
    ),
    Signal(
        key="beef_production_ytd",
        label="Beef production, year to date",
        question=Q_SUPPLY,
        basis="SJ_LS712 · USDA's OWN published Change row · million lb",
        source="SJ_LS712",
        pick=lambda b: _g(b, "slaughter", "beef_production", "ytd_chg_pct"),
        fmt="pct_signed", cadence="weekly", max_age_days=10,
        as_of=lambda b: _g(b, "slaughter", "beef_production", "week_ending"),
        depth=NONE, depth_note="As the kill.",
        page="Cattle Weights",
    ),
    Signal(
        key="cash_5area",
        label="5-Area live cash",
        question=Q_SUPPLY,
        basis="LM_CT150 · head-weighted, steer+heifer combined · $/cwt · the "
              "headline price is NOT discounted for shrink; the WEIGHT is",
        source="LM_CT150",
        pick=lambda b: _g(b, "cash", "live", "this_week"),
        fmt="money", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "cash", "report_date"),
        depth=FULL,
        depth_note="2004-05-03, 1,169 wks, one hole (the Oct 1-16 2013 shutdown). "
                   "The negotiated head this price is discovered in fell 75% "
                   "between 2005 and 2025.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="negotiated_head",
        label="National negotiated head",
        question=Q_SUPPLY,
        basis="LM_CT154 · head PURCHASED in the week just ended — a DIFFERENT "
              "clock from LM_CT153's head SLAUGHTERED. Never divide one by the "
              "other: that ratio wandered 0.83–1.32 over six weeks.",
        source="LM_CT154",
        pick=lambda b: _g(b, "cash", "volume", "confirmed"),
        fmt="head", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "cash", "volume", "report_date"),
        depth=FULL, depth_note="2002-11-18, 24 yrs.",
        page="Cash Cattle Trade",
    ),
)

BY_KEY = {s.key: s for s in SIGNALS}
ALL_KEYS = frozenset(BY_KEY)


def for_question(question: str) -> tuple:
    return tuple(s for s in SIGNALS if s.question == question)
