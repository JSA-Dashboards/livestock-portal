"""
The overnight change on the morning brief's Outside Markets block.

WHY THIS FILE EXISTS. On 2026-09-24 the brief printed "Nov Crude +3.26" while
the real overnight move was +1.41. Massive's snapshot reported
previous_settlement 90.52 for CLX6 -- Tuesday 09-22 -- when Wednesday 09-23 had
settled 92.16. The code had been deliberately written to trust that field, and
corn and the S&P agreed with the history the same morning, so one instrument out
of three was wrong and nothing on the page suggested it.

The base now comes from the settlement history, which is dated, and the two
hazards below are the ones that make that safe. Both are real:

  today's own bar   The history's newest row is the in-progress session. The
                    first version of this code differenced against it and gave
                    corn -0.25 where the move was -9.00.

  a gap             Massive had no bars at all for 2026-09-14..09-18. Reaching
                    back across a hole computes a multi-session move and prints
                    it as an overnight one, which is a wrong number that looks
                    right. Past the cutoff the brief marks it instead.

    python -m pytest tests/test_outside_markets.py -q

Offline: the fake below stands in for Massive.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from letter import sources


class _Api:
    """Just enough Massive to answer _prior_settle."""

    def __init__(self, bars: dict):
        self._bars = bars

    def get_settlement_histories(self, tickers, api_key):
        return {t: pd.Series(self._bars) for t in tickers}


TODAY = date(2026, 9, 24)

# The real CLX6 series around the miss.
CRUDE = {
    date(2026, 9, 21): 92.37,
    date(2026, 9, 22): 90.52,
    date(2026, 9, 23): 92.16,
    date(2026, 9, 24): 93.67,      # today, in progress
}


def test_the_base_is_yesterdays_settle_not_todays_bar():
    settle, when = sources._prior_settle(_Api(CRUDE), "CLX6", "k", TODAY)
    assert (settle, when) == (92.16, date(2026, 9, 23))


def test_the_crude_miss_would_now_be_caught():
    """
    The exact numbers. Massive said the base was 90.52 and the brief printed
    +3.26; against the dated history it is +1.47 on a 93.63 print.
    """
    settle, _ = sources._prior_settle(_Api(CRUDE), "CLX6", "k", TODAY)
    assert round(93.63 - settle, 2) == 1.47
    assert round(93.63 - 90.52, 2) == 3.11      # what trusting the snapshot gave


def test_a_weekend_is_not_a_gap():
    """Friday to Monday is three calendar days and a perfectly ordinary move."""
    bars = {date(2026, 9, 18): 96.08, date(2026, 9, 21): 92.37}
    settle, when = sources._prior_settle(_Api(bars), "CLX6", "k", date(2026, 9, 21))
    assert (settle, when) == (96.08, date(2026, 9, 18))


def test_a_monday_holiday_is_not_a_gap():
    """Thursday settle read on the following Tuesday: four days, still one session."""
    bars = {date(2026, 9, 17): 97.23, date(2026, 9, 22): 90.52}
    settle, _ = sources._prior_settle(_Api(bars), "CLX6", "k", date(2026, 9, 22))
    assert settle == 97.23


def test_a_week_long_hole_is_marked_not_bridged():
    """
    Massive's 09-14..09-18 outage. The newest bar before 09-21 would be 09-11,
    ten days back -- a move over a week and a half, which must not be printed as
    an overnight change.
    """
    bars = {date(2026, 9, 11): 100.75, date(2026, 9, 21): 92.37}
    settle, when = sources._prior_settle(_Api(bars), "CLX6", "k", date(2026, 9, 21))
    assert settle is None and when is None


def test_no_history_at_all_yields_no_base():
    assert sources._prior_settle(_Api({}), "CLX6", "k", TODAY) == (None, None)


def test_the_cutoff_covers_a_long_weekend_but_not_a_lost_week():
    assert 4 <= sources.MAX_PRIOR_SETTLE_AGE_DAYS < 7


# -- The AM report must not read today's bar as a settle ----------------------

class _FuturesApi:
    """Enough of massive_api for fetch_futures."""

    def __init__(self, bars: dict, ticker: str = "GFU6"):
        self._bars, self._ticker = bars, ticker

    def get_active_contract_tickers(self, product_code, api_key, as_of):
        return [{"ticker": self._ticker}]

    def get_settlement_histories(self, tickers, api_key):
        return {t: pd.Series(self._bars) for t in tickers}


# Today's row exists from the moment the session opens; it is not a settle.
INTRADAY = {
    date(2026, 9, 22): 335.00,
    date(2026, 9, 23): 336.525,
    date(2026, 9, 24): 336.80,     # in progress
}


@pytest.fixture
def _patched(monkeypatch):
    monkeypatch.setattr(sources, "_massive", lambda: _FuturesApi(INTRADAY))


def test_the_evening_letter_takes_todays_settle(_patched):
    row = sources.fetch_futures("GF", "k", TODAY, 1)[0]
    assert (row["settle"], row["settle_date"]) == (336.80, "2026-09-24")


def test_the_morning_brief_takes_yesterdays(_patched):
    """
    The bug reported 2026-09-24: a brief rebuilt mid-session showed live prices
    under a heading that said "Settlement on 9/24/26". am_cattle_rows promises
    yesterday's settle and its move, and was getting neither.
    """
    row = sources.fetch_futures("GF", "k", TODAY, 1, completed_only=True)[0]
    assert (row["settle"], row["settle_date"]) == (336.525, "2026-09-23")
    # ...and the move is yesterday's, measured from the day before.
    assert row["change_day"] == pytest.approx(336.525 - 335.00)


def test_before_the_open_the_two_agree(_patched, monkeypatch):
    """
    With no bar for today yet, completed_only changes nothing -- which is why
    this went unnoticed for as long as the brief was built at 07:30 sharp.
    """
    bars = {k: v for k, v in INTRADAY.items() if k < TODAY}
    monkeypatch.setattr(sources, "_massive", lambda: _FuturesApi(bars))
    plain = sources.fetch_futures("GF", "k", TODAY, 1)[0]
    only = sources.fetch_futures("GF", "k", TODAY, 1, completed_only=True)[0]
    assert plain["settle_date"] == only["settle_date"] == "2026-09-23"


def test_the_am_format_is_the_one_that_asks_for_it():
    """gather() keys this off the kind, so a new AM-like format must opt in."""
    src = (sources.REPO / "letter" / "build.py").read_text(encoding="utf-8")
    assert 'settled_only = (kind == "am")' in src
    assert src.count("completed_only=settled_only") == 2
