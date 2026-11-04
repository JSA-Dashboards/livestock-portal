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


# ── which markets, and in what order ────────────────────────────────────────

def test_soybeans_sit_directly_under_corn():
    """
    THE LIST ORDER IS THE PAGE ORDER. render.am_blocks walks ctx["outside"] as
    it comes, so the only thing putting Soybeans under Corn is its position
    here -- there is no sort anywhere downstream to restore it. Added
    2026-09-28 at Ross's request; the two are read together.
    """
    codes = [c for c, _label, _style in sources.OUTSIDE_MARKETS]
    assert codes.index("ZS") == codes.index("ZC") + 1, codes


def test_each_market_quotes_the_way_its_contract_ticks():
    """
    1283.75 must print as 1283'6, not 1283.75. Corn, wheat, oats and soybeans
    trade in eighths; giving beans the wrong style would print a grain quote
    in a shape nobody at a desk reads.

    THREE STYLES SINCE 2026-11-04, not two. This test was named "...and the
    rest do not" and its docstring said "equities and crude are plain
    decimals" -- half false the moment an equity index arrived that ticks in
    whole points. The rule is not grain-versus-the-rest; it is that each
    market is quoted the way its own contract ticks.
    """
    style = {code: st for code, _label, st in sources.OUTSIDE_MARKETS}
    assert style["ZS"] == "eighths"          # 1/8 cent
    assert style["ZC"] == "eighths"
    assert style["ES"] == "decimal"          # 0.25 index points
    assert style["CL"] == "decimal"          # $0.01
    assert style["YM"] == "points"           # 1 whole index point


def test_the_dow_sits_directly_under_the_sp():
    """
    The order of OUTSIDE_MARKETS IS the order on the page -- there is no sort
    anywhere downstream -- and the two equity lines are one reading. Same
    reasoning that puts Soybeans under Corn, and Ross asked for the Dow
    "like we have the SP".
    """
    codes = [c for c, _label, _style in sources.OUTSIDE_MARKETS]
    assert codes.index("YM") == codes.index("ES") + 1, codes


def test_every_style_has_a_formatter():
    """
    A style with no entry in render._OUTSIDE_FMT falls back to decimals, so
    it prints a plausible number in the wrong shape rather than raising --
    the failure nobody reports. Adding a market with a new style and
    forgetting the formatter is the obvious way to do that.
    """
    from letter import render

    declared = {st for _c, _l, st in sources.OUTSIDE_MARKETS}
    assert declared <= set(render._OUTSIDE_FMT), (
        f"no formatter for {sorted(declared - set(render._OUTSIDE_FMT))}")


def test_an_index_prints_in_whole_points():
    """
    YM ticks in one index point, so money()'s two decimals are always ".00"
    -- two characters of noise on the longest number in the block, directly
    above an S&P whose .25 ticks make its decimals mean something.

    The separator is the other half: 53025 unseparated is a five-digit run a
    reader has to count.
    """
    from letter import render

    assert render.points(53025.0) == "53,025"
    assert render.points(-1130.0) == "-1,130"
    assert render.points(None) == render.MISSING
    # Rounds rather than truncating, if Massive ever serves a fractional one.
    assert render.points(53025.6) == "53,026"


def test_the_dow_row_carries_no_decimal_point():
    """
    End to end through the real renderer, because the formatter being right
    and the block reaching for it are different claims -- the dispatch table
    was defined ABOVE the functions it names on the first attempt and the
    module would not import at all.
    """
    from datetime import date

    from letter import render

    ctx = {"kind": "am", "issue_date": date(2026, 11, 4), "change_basis": "day",
           "commentary": {}, "live_cattle": [], "feeder_cattle": [], "cash": {},
           "cutout": {}, "slaughter": {}, "fci": {}, "calendar": [], "chart": {},
           "outside": [
               {"code": "ES", "label": "S&P", "style": "decimal", "month": "Dec",
                "price": 7686.0, "change": 89.25},
               {"code": "YM", "label": "Dow", "style": "points", "month": "Dec",
                "price": 53025.0, "change": 1130.0},
           ]}
    block = render.build_html(ctx, disclaimer=False).split("Overnight Markets")[1]
    block = block.split("<h2>")[0]
    assert "Dec Dow: +1,130 at 53,025" in block, block
    assert "53,025.00" not in block
    # ...and the S&P beside it KEEPS its decimals.
    assert "+89.25 at 7,686.00" in block, block


def test_the_dow_stays_out_of_the_chart_rotation():
    """
    Adding a market to the overnight block does NOT add it to the chart of
    the day, exactly as for soybeans above: chart_movers maps only codes with
    a CHART_POOL entry, and a mover key with no pool entry can never be
    picked. Ross asked for a price line, not a chart.
    """
    import inspect

    from letter import build as letter_build
    from letter import config

    pool_keys = {e["key"] for e in config.CHART_POOL}
    src = inspect.getsource(letter_build.chart_movers)
    assert '"YM"' not in src, "YM was mapped into chart_movers without a pool entry"
    assert "dow" not in pool_keys


def test_soybeans_stay_out_of_the_chart_rotation():
    """
    Adding a market to the overnight block does NOT add it to the chart of the
    day. build.chart_movers maps only the codes that have a CHART_POOL entry,
    and a mover key with no pool entry can never be picked -- so the two lists
    have to stay consistent on purpose rather than by accident.
    """
    import inspect

    from letter import build as letter_build
    from letter import config

    pool_keys = {e["key"] for e in config.CHART_POOL}
    src = inspect.getsource(letter_build.chart_movers)
    assert '"ZS"' not in src, "ZS was mapped into chart_movers without a pool entry"
    assert "beans" not in pool_keys


# -- The Dollar Index, which is not a contract --------------------------------
#
# Massive carries four venues and all four are CME Group (XNYM, XCME, XCBT,
# XCEC, ~25,000 products, zero ICE), so DX -- an ICE Futures U.S. contract --
# can never come from it. The index comes from Yahoo's DX-Y.NYB instead, and
# the payload below is the real one, trimmed, as served on 2026-11-04.

NY = -18000                       # meta.gmtoffset, EST


def _bar(y, m, d, hour=9):
    """A daily bar stamped at the session open, in EXCHANGE-local terms."""
    from datetime import datetime, timezone
    local = datetime(y, m, d, hour, tzinfo=timezone.utc)
    return int(local.timestamp()) - NY


# 10-31 is a Saturday and Yahoo serves it with a null close; 11-04 is today's
# bar, in progress. Both have to be handled and neither is hypothetical.
DXY_STAMPS = [_bar(2026, 10, 29), _bar(2026, 10, 31), _bar(2026, 11, 2),
              _bar(2026, 11, 3), _bar(2026, 11, 4)]
DXY_CLOSES = [101.88, None, 101.75, 101.87, 101.451]


def _dxy_payload(stamps=None, closes=None, **meta):
    base = {"gmtoffset": NY, "regularMarketPrice": 101.451,
            # NOT yesterday's close -- the close before the window began.
            "chartPreviousClose": 102.17}
    base.update(meta)
    return {"chart": {"result": [{
        "meta": base,
        "timestamp": list(DXY_STAMPS if stamps is None else stamps),
        "indicators": {"quote": [{"close": list(DXY_CLOSES if closes is None
                                                else closes)}]},
    }]}}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _Sess:
    def __init__(self, payload, status=200):
        self._payload, self._status = payload, status

    def get(self, *_a, **_kw):
        return _Resp(self._payload, self._status)


def _fetch(monkeypatch, payload, status=200, when=date(2026, 11, 4)):
    monkeypatch.setattr(sources, "_session", lambda *a, **k: _Sess(payload, status))
    return sources.fetch_dollar_index(when)


def test_the_dollar_index_prices_off_the_dated_series(monkeypatch):
    row = _fetch(monkeypatch, _dxy_payload())
    assert row["price"] == 101.451
    assert row["prior_settle"] == 101.87
    assert row["prior_settle_date"] == "2026-11-03"
    assert row["change"] == round(101.451 - 101.87, 4)


def test_chart_previous_close_is_not_yesterdays_close(monkeypatch):
    """
    THE TRAP, WITH THE REAL NUMBERS, and it fired on the first live day.

    On a ranged request Yahoo's `chartPreviousClose` is the close BEFORE THE
    WINDOW BEGINS, not the prior session: it read 102.17 on 2026-11-04, which
    is the 2026-10-04 close, while the real 11-03 close in the same payload
    was 101.87.

    Trusting it prints the Dollar Index down 0.73 where the overnight move is
    0.43 -- a 70% overstatement, every day, and never on a day anyone would
    notice. Exactly the shape of the crude miss above, from a different
    vendor.
    """
    row = _fetch(monkeypatch, _dxy_payload())
    assert row["change"] == -0.419                      # against 101.87
    assert round(101.451 - 102.17, 3) == -0.719         # what the field gives
    assert row["vendor_prior_close"] == 102.17
    assert row["vendor_disagrees"] is True


def test_todays_own_bar_is_not_the_base(monkeypatch):
    """Strictly before, the same rule _prior_settle applies to the futures."""
    row = _fetch(monkeypatch, _dxy_payload())
    assert row["prior_settle"] != 101.451
    assert row["prior_settle_date"] == "2026-11-03"


def test_a_null_close_is_skipped_not_read_as_zero(monkeypatch):
    """
    Yahoo serves 2026-10-31, a Saturday, with close null. Reading it as a
    number would make the base 0.00 and the change +101.45.
    """
    row = _fetch(monkeypatch, _dxy_payload(), when=date(2026, 11, 2))
    assert row["prior_settle"] == 101.88                # 10-29, skipping 10-31
    assert row["prior_settle_date"] == "2026-10-29"


def test_the_date_comes_from_the_exchange_offset_not_utc(monkeypatch):
    """
    A bar stamped 00:30 UTC is the PREVIOUS day in New York. Read as UTC it
    is 11-04 and becomes today's in-progress bar, excluded; read correctly it
    is 11-03 and is the base. One bar, two different letters.
    """
    from datetime import datetime, timezone
    midnight_utc = int(datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc).timestamp())
    row = _fetch(monkeypatch, _dxy_payload(stamps=[midnight_utc], closes=[101.87]))
    assert row["prior_settle_date"] == "2026-11-03", "the UTC date was used"
    assert row["change"] == round(101.451 - 101.87, 4)


def test_a_stale_base_yields_no_change_but_keeps_the_price(monkeypatch):
    """
    MAX_PRIOR_SETTLE_AGE_DAYS, the rule the futures path already applies: a
    multi-session move printed as an overnight one is a wrong number that
    looks right. The level is still true, so it still prints.
    """
    row = _fetch(monkeypatch, _dxy_payload(stamps=[_bar(2026, 10, 20)],
                                           closes=[99.0]))
    assert row["price"] == 101.451
    assert row["change"] is None
    assert row["prior_settle"] is None


def test_yahoo_failing_costs_one_line_and_never_the_letter(monkeypatch):
    """
    am_blocks drops any market whose price is None, so an outage at a host
    the rest of the brief does not use must not raise into gather().
    """
    for payload, status in ((_dxy_payload(), 503), ({"chart": {"result": []}}, 200),
                            ({}, 200), ({"chart": None}, 200)):
        row = _fetch(monkeypatch, payload, status)
        assert row["price"] is None and row["change"] is None
        assert row["label"] == "Dollar Index"


def test_the_dollar_index_sits_below_crude(monkeypatch):
    """
    Where Ross asked for it. It is appended after the OUTSIDE_MARKETS loop
    rather than listed in it -- there is no product code to fetch -- so the
    thing to pin is that the appended row lands last.
    """
    monkeypatch.setattr(sources, "front_contracts", lambda *a, **k: [])
    monkeypatch.setattr(sources, "fetch_dollar_index",
                        lambda _as_of: {"code": "DXY", "label": "Dollar Index",
                                        "style": "decimal", "price": 101.45})
    rows = sources.fetch_outside_markets("k", date(2026, 11, 4))
    codes = [r["code"] for r in rows]
    assert codes[-1] == "DXY", codes
    assert codes.index("DXY") == codes.index("CL") + 1, codes


def test_the_index_row_carries_no_contract_month(monkeypatch):
    """
    It is an index, not a curve. The bullet is built as "<month> <label>" and
    would open with a stray space if the renderer did not strip it.
    """
    from letter import render

    row = _fetch(monkeypatch, _dxy_payload())
    assert row["month"] is None
    ctx = {"kind": "am", "issue_date": date(2026, 11, 4), "change_basis": "day",
           "commentary": {}, "live_cattle": [], "feeder_cattle": [], "cash": {},
           "cutout": {}, "slaughter": {}, "fci": {}, "calendar": [], "chart": {},
           "outside": [row]}
    block = render.build_html(ctx, disclaimer=False).split("Overnight Markets")[1]
    block = block.split("<h2>")[0]
    assert "Dollar Index: -0.42 at 101.45" in block, block
    assert "<li> Dollar" not in block, "a month-shaped space opened the bullet"
