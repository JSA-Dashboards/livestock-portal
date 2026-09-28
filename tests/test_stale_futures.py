"""
The morning the letter quoted seventeen-day-old futures as today's.

WHAT HAPPENED. On 2026-09-28 the Monday AM brief printed "Cattle Futures --
Settlement on 9/11/26": Oct LC 219.675, Dec LC 222.225, Oct FC 332.50, Nov FC
328.175, with a "daily" move of +4.95 on the Oct feeder. Friday 2026-09-25 had
settled 218.85, 222.10, 335.00 and 332.00, and the market had moved a fraction
of a cent. gather() returned an EMPTY error list the whole time.

WHY NOTHING CAUGHT IT. Massive's /aggs for CME cattle at resolution 1session
and 1day stopped at 2026-09-11 -- 343 bars for LEV6 and nothing after -- while
the same ticker at 1hour carried 2026-09-25, and CL, ZC and ES were current at
every resolution. Bars that had been served on Friday were RETRACTED over the
weekend; letter/data/settle_log.json still held 09-23 and 09-24 values the API
no longer returned. Every guard in the build asked whether data came back, and
the answer was yes: the newest bar of a stale series is a perfectly good bar.

The three things pinned here are the three that were missing:

  * staleness is DETECTED, because "it parsed" is not "it is current";
  * a change is never SUBTRACTED ACROSS A HOLE, because the bar before 09-25 is
    09-11 and that difference is a fortnight dressed as a day;
  * the hourly bars RECOVER the sessions the daily series lost, without ever
    overwriting a real settlement with a last trade.

And one trap found while fixing it, pinned in test_the_snapshot_change_field_is_never_used:
Massive's snapshot previous_settlement and change are computed off the same
broken series. At 08:52 that morning, with Friday settled at 335.00, GFV6's
snapshot reported previous_settlement 332.50 and change +2.25 -- the 09-11 bar
and a seventeen-day move, offered under the exchange's own field names.

    python -m pytest tests/test_stale_futures.py -q

Offline. massive_api is faked at sources._massive; nothing touches the network.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from letter import build, settle_log, sources  # noqa: E402

MONDAY = date(2026, 9, 28)
FRIDAY = date(2026, 9, 25)

# The real shape of the outage: a run of sessions, then a fortnight of nothing.
BEFORE_THE_HOLE = {
    date(2026, 9, 9): 215.85,
    date(2026, 9, 10): 217.825,
    date(2026, 9, 11): 219.675,
}
# 09-25 exists only at hourly resolution. Its close is a shade off the settle,
# which is the entire reason it is a fallback and not a replacement.
HOURLY_ONLY = {date(2026, 9, 25): 218.85}

# A healthy week, for the cases that must stay silent. Worth stating plainly:
# the first draft of this file reused BEFORE_THE_HOLE for these, so three tests
# asserted healthy behaviour against a series with a fortnight missing from it.
CONTIGUOUS = {
    date(2026, 9, 22): 217.40,
    date(2026, 9, 23): 218.30,
    date(2026, 9, 24): 219.675,
    date(2026, 9, 25): 218.85,
}
THROUGH_THURSDAY = {d: v for d, v in CONTIGUOUS.items() if d < date(2026, 9, 25)}


class FakeMassive:
    """Only the four entry points sources.py reaches for."""

    def __init__(self, session=None, hourly=None, snapshot=None, ticker="LEV6"):
        self.ticker = ticker
        self.session = dict(session or {})
        self.hourly = dict(hourly or {})
        self.snapshot = snapshot
        self.hourly_calls = 0

    def get_active_contract_tickers(self, product_code, api_key, as_of, limit=None):
        return [{"ticker": self.ticker}]

    def get_settlement_histories(self, tickers, api_key):
        return {t: pd.Series(self.session).sort_index() for t in tickers}

    def get_snapshots(self, tickers, api_key):
        return {t: self.snapshot for t in tickers} if self.snapshot else {}

    def _get(self, path, api_key, params=None):
        self.hourly_calls += 1
        assert (params or {}).get("resolution") == "1hour", params
        return {"results": [
            # window_start deliberately out of order: these bars carry no
            # "timestamp" field, and the first version of this code sorted on
            # one, which is not an error -- it silently leaves the API's order.
            {"session_end_date": d.isoformat(), "close": v, "window_start": -i}
            for i, (d, v) in enumerate(sorted(self.hourly.items(), reverse=True))
        ]}


@pytest.fixture
def fake(monkeypatch):
    """
    STUBS THE SETTLE LOG TOO, and that is not optional. fetch_futures reads
    letter/data/settle_log.json as a recovery tier, so without this the tests
    pick up whatever real settles the machine running them happens to have
    banked -- and three of them duly went green on a developer box and would
    have failed in CI. `banked` supplies it explicitly instead.
    """
    def _install(banked=None, **kw):
        api = FakeMassive(**kw)
        monkeypatch.setattr(sources, "_massive", lambda: api)
        monkeypatch.setattr(sources.settle_log, "load", lambda *a, **k: banked or {})
        return api
    return _install


def _one(product="LE", as_of=MONDAY, completed_only=True):
    rows = sources.fetch_futures(product, "key", as_of, n=1, completed_only=completed_only)
    return rows[0] if rows else None


# ── staleness is detected at all ─────────────────────────────────────────────

def test_a_seventeen_day_old_settle_is_marked_stale(fake):
    """The exact failure. Nothing recoverable, so it must at least be flagged."""
    fake(session=BEFORE_THE_HOLE, hourly={})
    con = _one()
    assert con["settle_date"] == "2026-09-11"
    assert con["settle_stale"] is True


def test_a_normal_friday_to_monday_gap_is_not_stale(fake):
    """Three days over a weekend is every Monday, and must stay silent."""
    fake(session=CONTIGUOUS)
    con = _one()
    assert con["settle_date"] == "2026-09-25"
    assert con["settle_stale"] is False
    assert con["settle_recovered"] is False


def test_a_holiday_monday_is_not_stale_either(fake):
    """
    Friday to Tuesday is four days and must not raise the alarm.

    The recovery TRIGGER does fire here -- Monday is a weekday with no bar, so
    the series looks behind -- and that is the deliberate asymmetry: trying the
    hourly bars on a holiday costs a request and finds nothing, while a
    tolerance loose enough to silence it would hide a feed one session behind.
    """
    fake(session=CONTIGUOUS)
    con = _one(as_of=date(2026, 9, 29))
    assert con["settle_stale"] is False


# ── the move is never measured across the hole ───────────────────────────────

def test_no_daily_change_is_printed_across_a_fortnight(fake):
    """
    THE WORST NUMBER ON THE PAGE. 332.50 - 327.55 gave the Oct feeder a "+4.95
    daily move" on a session that moved 0.075. A missing change marks itself
    [[?]] through signed(); a wrong one looks exactly like a right one.
    """
    fake(session=BEFORE_THE_HOLE, hourly=HOURLY_ONLY)
    con = _one()
    assert con["change_day"] is None
    assert con["change_missing"] is True


def test_an_ordinary_session_change_is_still_computed(fake):
    """The guard must not cost the normal case its move."""
    fake(session=CONTIGUOUS)
    con = _one()
    assert con["change_day"] == round(218.85 - 219.675, 4)


# ── recovery from the hourly bars ────────────────────────────────────────────

def test_the_hourly_bars_recover_the_session_the_daily_series_lost(fake):
    """9/25 exists at 1hour and nowhere else. That is the whole fix."""
    fake(session=BEFORE_THE_HOLE, hourly=HOURLY_ONLY)
    con = _one()
    assert con["settle_date"] == "2026-09-25"
    assert con["settle"] == 218.85
    assert con["settle_recovered"] is True
    assert con["settle_source"] == "hourly close"
    assert con["settle_stale"] is False


def test_recovery_never_overwrites_a_real_settlement(fake):
    """
    An hourly close is a last trade and a settlement is a closing range. On
    2026-09-11 GFX6 closed 328.475 and settled 328.175. Filling a session that
    already has a settlement would swap the better number for the worse one.
    """
    api = fake(session=THROUGH_THURSDAY,
               hourly={date(2026, 9, 24): 219.625},
               banked={"LEV6": {"2026-09-25": 218.85}})
    con = _one()
    assert con["settle_date"] == "2026-09-25"
    # 09-24 keeps its SETTLEMENT of 219.675 and does not take the hourly close
    # of 219.625, so the move is measured off the better number. Had the close
    # won, this would read -0.775.
    assert con["change_day"] == round(218.85 - 219.675, 4)
    assert api.hourly_calls == 1


def test_the_hourly_bars_are_not_fetched_when_the_series_is_healthy(fake):
    """Two extra requests per contract, every build, for nothing."""
    api = fake(session=CONTIGUOUS)
    _one()
    assert api.hourly_calls == 0


def test_a_feed_one_session_behind_is_recovered_not_quietly_accepted(fake):
    """
    THE SMALL VERSION OF THE SAME BUG, and the reason the recovery trigger is
    not a day count. On a Monday, a feed whose newest bar is Thursday is only
    four days old -- inside any tolerance wide enough for a holiday -- and the
    brief would print Thursday's settle as Friday's with nothing but the date
    line to say so. That is how the original failure would come back.
    """
    fake(session=THROUGH_THURSDAY, hourly=HOURLY_ONLY)
    con = _one()
    assert con["settle_date"] == "2026-09-25"
    assert con["settle_recovered"] is True


def test_a_back_month_that_did_not_trade_does_not_trigger_recovery(fake):
    """
    Judged on the freshest contract. An illiquid January feeder goes days
    without a bar for ordinary reasons, and asking "is ANY contract behind"
    would fetch hourly bars every day of the year on its account.
    """
    api = fake(session=CONTIGUOUS)
    rows = sources.fetch_futures("LE", "key", MONDAY, n=1, completed_only=True)
    assert rows and api.hourly_calls == 0


def test_an_end_adjacent_hole_is_recovered_for_the_evening_letter(fake):
    """
    The PM version of the same outage: the newest bar is TODAY, so nothing is
    stale, but the one before it is three weeks back and the letter would carry
    a settle with no move. Checking only the newest bar fixed the morning brief
    and left the evening one changeless.
    """
    fake(session={**BEFORE_THE_HOLE, MONDAY: 219.125},
         banked={"LEV6": {"2026-09-25": 218.875}})
    con = _one(completed_only=False)
    assert con["settle_date"] == "2026-09-28"
    assert con["settle_source"] == "settlement history"   # today's is real
    assert con["change_day"] == round(219.125 - 218.875, 4)
    assert con["change_recovered"] is False               # both ends settled


# ── the snapshot: official settlement yes, its change no ─────────────────────

def _snap(close, settlement, prev, change):
    return {"session": {"close": close, "settlement_price": settlement,
                        "previous_settlement": prev, "change": change}}


def test_the_snapshot_is_never_a_settlement_source(fake):
    """
    IT WAS, FOR ABOUT AN HOUR, AND IT WAS WRONG. The first fix read the
    snapshot's settlement_price when its close proved it described the session
    just recovered. On 2026-09-25 that field said 335.00 for GFV6 and the
    contract settled 334.925: 335.00 is the last TRADE. CME settles on a
    weighted average of the closing range, so the two differ routinely -- by
    0.025 to 0.075 across all four contracts that day -- and reading one as the
    other produced a wrong number wearing the word "settlement".
    """
    fake(session=BEFORE_THE_HOLE, hourly=HOURLY_ONLY,
         snapshot=_snap(close=218.85, settlement=999.0, prev=219.675, change=-0.775))
    con = _one()
    assert con["settle"] == 218.85, "the snapshot must not supply the settle"
    assert con["settle_source"] == "hourly close"


def test_the_snapshot_change_field_is_never_used(fake):
    """
    previous_settlement and change come off the same broken daily series. At
    08:52 on 2026-09-28, Friday having settled 334.925, GFV6's snapshot said
    previous_settlement 332.50 and change +2.25 -- the 09-11 bar and a
    seventeen-day move under the exchange's own field names. The same field had
    read 334.925 at 07:30. A source that is right before the open and wrong
    after it is not a source, and the morning brief is built in that window.
    """
    fake(session=BEFORE_THE_HOLE, hourly=HOURLY_ONLY,
         snapshot=_snap(close=218.85, settlement=218.85, prev=219.675, change=+2.25))
    con = _one()
    assert con["change_day"] is None


# ── a settlement and a close are different kinds of number ──────────────────

def test_a_banked_settlement_outranks_an_hourly_close(fake):
    """
    The settle log holds real settlements, so it fills a missing session in
    preference to the hourly bars. Its 09-23 and 09-24 values outlived Massive:
    they were recorded from bars the API has since retracted, and public market
    reports confirm them to the half cent.
    """
    fake(session=BEFORE_THE_HOLE, hourly={FRIDAY: 218.85},
         banked={"LEV6": {"2026-09-25": 218.875}})
    con = _one()
    assert con["settle"] == 218.875
    assert con["settle_source"] == "banked settlement"
    assert con["settle_basis"] == sources.SETTLED


def test_a_move_is_never_measured_from_a_settle_to_a_close(fake):
    """
    THE SUBTLE ONE, and the reason settle_basis exists. Once the settle log
    fills 09-24 the two ends are adjacent again -- but Friday's last trade
    against Thursday's settlement gives +3.25 where the true settle-to-settle
    move is +3.175. Adjacent, plausible, and wrong.
    """
    fake(session={}, hourly={FRIDAY: 335.00},
         banked={"LEV6": {"2026-09-24": 331.75}}, ticker="LEV6")
    con = _one()
    assert con["settle"] == 335.00
    assert con["settle_basis"] == sources.CLOSE_ONLY
    assert con["change_day"] is None, "settle-to-close is not a daily move"


def test_two_settled_ends_still_give_a_move(fake):
    """The basis rule must not cost the recoverable case its change."""
    fake(session={}, hourly={},
         banked={"LEV6": {"2026-09-24": 331.75, "2026-09-25": 334.925}})
    con = _one()
    assert con["change_day"] == round(334.925 - 331.75, 4)


# ── the build says so ────────────────────────────────────────────────────────

def test_a_stale_settle_reaches_the_error_list(fake):
    """gather() returned [] through the whole incident. That was the real bug."""
    errors = []
    ctx = {"live_cattle": [{"month": "Oct", "settle_date": "2026-09-11",
                            "settle_stale": True, "settle_recovered": False,
                            "change_missing": False}]}
    build.report_futures_health(ctx, MONDAY, errors)
    joined = " ".join(errors)
    assert "STALE" in joined and "2026-09-11" in joined
    assert "do not send" in joined.lower()


def test_a_recovered_settle_and_a_missing_move_are_each_reported(fake):
    errors = []
    ctx = {"feeder_cattle": [{"month": "Oct", "settle_date": "2026-09-25",
                              "settle_stale": False, "settle_recovered": True,
                              "settle_source": "hourly close", "change_missing": True}]}
    build.report_futures_health(ctx, MONDAY, errors)
    joined = " ".join(errors)
    assert "hourly close" in joined
    assert "No daily change for Oct" in joined


def test_a_healthy_build_says_nothing(fake):
    """The list is read by a human every morning; noise costs it its meaning."""
    errors = []
    ctx = {"live_cattle": [{"month": "Oct", "settle_date": "2026-09-25",
                            "settle_stale": False, "settle_recovered": False,
                            "change_missing": False}]}
    build.report_futures_health(ctx, MONDAY, errors)
    assert errors == []


# ── the settle log must not inherit a close ──────────────────────────────────

def test_a_recovered_close_is_not_filed_as_a_settlement(tmp_path):
    """
    This file is the authority for the prior-Friday base once a value lands in
    it. An hourly close written here makes next Friday's week-over-week change
    a few ticks wrong, unmarked -- the quiet error the module exists to stop.
    """
    p = tmp_path / "settle_log.json"
    ctx = {"live_cattle": [
        {"ticker": "LEV6", "settle": 218.85, "settle_date": "2026-09-25",
         "settle_source": "hourly close"},
        {"ticker": "LEZ6", "settle": 222.10, "settle_date": "2026-09-25",
         "settle_source": "snapshot settlement"},
    ]}
    settle_log.record(ctx, p)
    log = settle_log.load(p)
    assert "LEV6" not in log, "a last trade was filed as a settlement"
    assert log["LEZ6"]["2026-09-25"] == 222.10

# ── the chart must not illustrate a market with a hole in it ────────────────

def test_the_chart_refuses_a_stale_series(fake, monkeypatch):
    """
    It would be printed beside the numbers it illustrates. On 2026-09-28 this
    returned GFV6's 60 sessions ending 09-11 at 332.50, to be drawn on the same
    page as "Oct feeders: 334.925" -- a picture contradicting the text.
    """
    api = fake(session=BEFORE_THE_HOLE)
    monkeypatch.setattr(sources, "front_contracts",
                        lambda *a, **k: [{"ticker": "GFV6"}])
    assert sources.fetch_front_history("GF", "key", MONDAY, sessions=60) == {}
    assert api is not None


def test_the_chart_refuses_a_series_with_a_hole_in_the_middle(fake, monkeypatch):
    """
    Recovery cannot help here and filling would be worse: Massive's /trades has
    ZERO ticks for every day of 09-14..09-24, so the best a filled series could
    do is join 09-11 to 09-25 with a straight line through a fortnight that is
    not there. build_chart falls through to corn, crude or the S&P, all of
    which were current throughout.
    """
    holed = {**BEFORE_THE_HOLE, date(2026, 9, 24): 219.675, FRIDAY: 218.85}
    fake(session=holed)
    monkeypatch.setattr(sources, "front_contracts",
                        lambda *a, **k: [{"ticker": "LEV6"}])
    assert sources.fetch_front_history("LE", "key", MONDAY, sessions=60) == {}


def test_the_chart_still_draws_a_healthy_series(fake, monkeypatch):
    """The guard must not cost the ordinary case its chart."""
    healthy = {date(2026, 9, 14 + i): 210.0 + i for i in (0, 1, 2, 3, 4)}
    healthy.update(CONTIGUOUS)
    fake(session=healthy)
    monkeypatch.setattr(sources, "front_contracts",
                        lambda *a, **k: [{"ticker": "LEV6"}])
    got = sources.fetch_front_history("LE", "key", MONDAY, sessions=60)
    assert got and got["ticker"] == "LEV6"
    assert got["dates"][-1] == FRIDAY


# ── the morning draft gets the morning's figures ────────────────────────────

def _am_ctx():
    return {
        "change_basis": "day",
        "live_cattle": [{"month": "Oct", "settle": 218.875, "change_day": -0.2}],
        "feeder_cattle": [{"month": "Oct", "settle": 334.925, "change_day": 3.175}],
        "tech_lc": None, "tech_fc": None,
        "cash": {}, "cutout": {}, "slaughter": {}, "daily_slaughter": {},
        "carcass_weights": {}, "fci": {}, "douglas": {}, "cftc": {},
        "cof": {}, "outside": [], "calendar": [],
    }


def test_the_am_draft_carries_the_contract_figures():
    """
    IT NEVER HAS. The AM format's only section key is "headlines", which was
    missing from the `lead` tuple, so add() discarded every computed figure --
    all six settles, the slaughter, the cash, the YTD -- from the very commit
    that wrote the tuple. No test called hints() with kind="am" until this one.
    """
    out = build.hints(_am_ctx(), "am")
    assert "headlines" in out
    blob = " ".join(out["headlines"])
    assert "218.875" in blob and "334.925" in blob, out


def test_the_evening_formats_keep_their_figures_under_market_action():
    """
    "headlines" sits LAST in the tuple so it never steals from Market Action.
    Every evening format has a headlines section too, and a Monday morning is
    no time to move the evening letter's furniture.
    """
    ctx = _am_ctx()
    out = build.hints(ctx, "recap")
    assert " ".join(out.get("market_action", [])).count("218.875") == 1
    assert not any("218.875" in line for line in out.get("headlines", []))
