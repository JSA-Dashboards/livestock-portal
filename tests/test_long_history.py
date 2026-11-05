"""
The seasonal page's nearby charts reach 2001, and the two sources stay apart.

Massive floors at 2021-11-08 and its single-digit year symbology cannot even
address an older contract, so everything before that comes from a second feed.
Four things in that arrangement are silent when wrong, and each has a test here:

  * `range=max` comes back 200 with MONTHLY bars. 264 of them span 25 years and
    read as a working daily series.
  * `meta.gmtoffset` is in the payload and is the right thing to apply on the
    other Yahoo caller in this repo. Applied here it dates every bar a day
    early for the eight months of the year that are EDT, and is a no-op through
    EST -- so a winter spot check passes.
  * the newest bar is a session in progress, not a settlement.
  * a null close read as a number charts as a crash to zero.

Plus the splice itself, where the failure is not visible at all: the two feeds
agree to the thousandth over their 1,255-day overlap, so a duplicated date
would not look wrong -- it would quietly give those five years twice the weight
in every average and high/low count computed off the series.
"""
from __future__ import annotations

import ast
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE_DIR = ROOT / "apps" / "livestock_seasonal"
sys.path.insert(0, str(PAGE_DIR))

import long_history  # noqa: E402

APP = PAGE_DIR / "app.py"
ENCODING = "utf-8-sig"


# ---------------------------------------------------------------- helpers

def _stamp(y: int, m: int, d: int, hour: int) -> int:
    """A Yahoo daily stamp: midnight New York, which is 04:00 UTC on an EDT
    date and 05:00 UTC on an EST one."""
    return int(datetime(y, m, d, hour, tzinfo=timezone.utc).timestamp())


def _payload(stamps, closes, gmtoffset=-18000):
    return {"chart": {"result": [{
        "meta": {"gmtoffset": gmtoffset, "exchangeTimezoneName": "America/New_York"},
        "timestamp": list(stamps),
        "indicators": {"quote": [{"close": list(closes)}]},
    }]}}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code != 200:
            raise long_history.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def _fetch(monkeypatch, payload, status=200, as_of=date(2026, 11, 5), code="LE"):
    seen = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        seen["url"] = url
        seen["params"] = params or {}
        seen["headers"] = headers or {}
        return _Resp(payload, status)

    monkeypatch.setattr(long_history.requests, "get", fake_get)
    series = long_history.fetch_nearby(code, as_of)
    return series, seen


# ------------------------------------------------------- the request shape

def test_the_request_pins_a_period_because_range_max_returns_monthly_bars(monkeypatch):
    """
    THE TRAP THIS WHOLE MODULE EXISTS NOT TO FALL INTO. `range=max&interval=1d`
    is the obvious spelling and answers 200 with `dataGranularity: 1mo` -- 264
    bars over 25 years, which charts perfectly and silently turns any seasonal
    statistic into twelve observations a year. Measured both ways against the
    live endpoint: explicit period1/period2 returns 6,438.
    """
    _, seen = _fetch(monkeypatch, _payload([_stamp(2026, 11, 4, 5)], [218.0]))
    params = seen["params"]
    assert params["interval"] == "1d"
    assert "range" not in params, "range= reintroduces the monthly downgrade"
    assert params["period1"] < params["period2"]
    # period1 must predate every series this module serves, so the start date
    # the page prints is the feed's own rather than this constant's.
    assert datetime.fromtimestamp(params["period1"], tz=timezone.utc).year <= 1990


def test_it_identifies_itself(monkeypatch):
    """Yahoo 404s an unidentified client often enough to be worth setting."""
    _, seen = _fetch(monkeypatch, _payload([_stamp(2026, 11, 4, 5)], [218.0]))
    assert seen["headers"].get("User-Agent")


# ------------------------------------------------------------- the dating

def test_the_utc_date_is_the_session_date_and_gmtoffset_is_not_applied(monkeypatch):
    """
    An EDT bar: stamped 04:00 UTC on 2026-10-26, which is midnight New York on
    the 26th. The session date is the 26th. Applying `meta.gmtoffset` (-5h)
    lands it on 23:00 on the 25th -- a SUNDAY, and one day early.

    On the live feed that cost 792 Sunday-dated bars and dropped agreement with
    this page's own Massive series from 1,254 of 1,254 to 440 of 1,081.
    """
    series, _ = _fetch(monkeypatch, _payload([_stamp(2026, 10, 26, 4)], [229.975]))
    assert list(series.index) == [pd.Timestamp(2026, 10, 26)]
    assert series.index[0].weekday() < 5, "a session date is never a weekend"


def test_an_est_bar_lands_on_its_own_day_too(monkeypatch):
    """
    05:00 UTC, the EST stamping. The offset is a no-op here, which is exactly
    why the bug survived a spot check: it is wrong through EDT and right
    through EST.
    """
    series, _ = _fetch(monkeypatch, _payload([_stamp(2026, 11, 3, 5)], [218.15]))
    assert list(series.index) == [pd.Timestamp(2026, 11, 3)]


def test_applying_the_offset_would_misdate_the_edt_bar():
    """
    The self-check: a guard that cannot fail is the thing it guards against.
    This asserts the REJECTED arithmetic really does produce the wrong day, so
    the two tests above are pinning a real distinction rather than agreeing
    with themselves.
    """
    stamp = _stamp(2026, 10, 26, 4)
    as_utc = datetime.fromtimestamp(stamp, tz=timezone.utc).date()
    with_offset = datetime.fromtimestamp(stamp + (-18000), tz=timezone.utc).date()
    assert as_utc == date(2026, 10, 26)
    assert with_offset == date(2026, 10, 25)
    assert with_offset.weekday() == 6, "the offset form lands on a Sunday"


# --------------------------------------------------------- bars and nulls

def test_a_null_close_is_skipped_not_read_as_a_number(monkeypatch):
    """float(None) raises and would cost the whole series; a zero charts as a
    crash to nothing. Yahoo does serve nulls -- letter/sources.py found a
    Saturday carrying one."""
    series, _ = _fetch(monkeypatch, _payload(
        [_stamp(2026, 11, 2, 5), _stamp(2026, 11, 3, 5), _stamp(2026, 11, 4, 5)],
        [219.7, None, 218.0]))
    assert list(series.index) == [pd.Timestamp(2026, 11, 2), pd.Timestamp(2026, 11, 4)]
    assert 0.0 not in list(series.values)


def test_the_in_progress_session_is_dropped(monkeypatch):
    """
    The newest bar is today's session, not a settlement -- the `completed_only`
    rule letter/sources.py already runs on, and the one day in the live overlap
    check where this feed and Massive disagreed.
    """
    series, _ = _fetch(monkeypatch, _payload(
        [_stamp(2026, 11, 4, 5), _stamp(2026, 11, 5, 5)], [218.0, 214.475]),
        as_of=date(2026, 11, 5))
    assert list(series.index) == [pd.Timestamp(2026, 11, 4)]


def test_an_unknown_product_asks_for_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(long_history.requests, "get",
                        lambda *a, **k: called.append(1) or _Resp(_payload([], [])))
    assert long_history.fetch_nearby("ZZ", date(2026, 11, 5)).empty
    assert not called


@pytest.mark.parametrize("payload,status", [
    ({"chart": {"result": []}}, 200),
    ({"chart": None}, 200),
    ({}, 200),
    ({"chart": {"result": [{"meta": {}, "timestamp": None,
                            "indicators": {"quote": [{}]}}]}}, 200),
    ({"chart": {"result": [{}]}}, 503),
])
def test_any_failure_costs_the_deep_history_and_never_the_page(monkeypatch, payload, status):
    """
    An undocumented endpoint with no SLA, on a deployment whose IPs are already
    blocked by one USDA host. The deep history is additive: without it the page
    must render exactly as it did before, so nothing here may raise.
    """
    series, _ = _fetch(monkeypatch, payload, status)
    assert isinstance(series, pd.Series) and series.empty


def test_a_raising_request_is_caught(monkeypatch):
    def boom(*a, **k):
        raise long_history.requests.ConnectionError("no route")

    monkeypatch.setattr(long_history.requests, "get", boom)
    assert long_history.fetch_nearby("LE", date(2026, 11, 5)).empty


# -------------------------------------------------------------- the splice

def _series(pairs):
    s = pd.Series(dict(pairs)).sort_index()
    s.index = pd.to_datetime(s.index)
    return s


def test_the_live_feed_wins_every_date_it_covers():
    """
    Massive is what the per-contract overlays, the spreads and the curve are
    built from, so handing it every date it can answer keeps the nearby chart
    reconcilable with the tabs beside it -- and makes this change unable to
    move a number already on the page.

    The values are made to DIFFER here on purpose. In production they agree to
    the thousandth, which is exactly why a test that used equal values would
    pass whichever source won.
    """
    recent = _series([(date(2021, 11, 8), 132.1), (date(2021, 11, 9), 133.0)])
    legacy = _series([(date(2021, 11, 5), 131.8), (date(2021, 11, 8), 999.0),
                      (date(2021, 11, 9), 999.0)])
    out = long_history.splice(recent, legacy)
    assert out.loc[pd.Timestamp(2021, 11, 8)] == 132.1
    assert out.loc[pd.Timestamp(2021, 11, 9)] == 133.0
    assert out.loc[pd.Timestamp(2021, 11, 5)] == 131.8


def test_no_date_is_carried_twice():
    """
    The failure that is invisible on the page. The feeds agree over their
    1,255-day overlap, so a duplicated index charts identically and simply
    double-weights five years in every mean and every high/low count.
    """
    recent = _series([(date(2021, 11, 8), 132.1), (date(2021, 11, 9), 133.0)])
    legacy = _series([(date(d.year, d.month, d.day), 1.0)
                      for d in pd.date_range("2021-11-01", "2021-11-09")])
    out = long_history.splice(recent, legacy)
    assert out.index.is_unique
    assert out.index.is_monotonic_increasing


def test_the_handover_is_the_live_feed_s_own_start_not_a_constant():
    """
    So it travels on its own as the vendor's retention window rolls forward --
    the shape herd.CHANNEL_LEGACY_THROUGH and the southeast retention build
    already use. A date typed in here would silently start dropping real days,
    or admitting duplicate ones, the moment Massive's floor moved.
    """
    legacy = _series([(date(2001, 3, 1), 77.75), (date(2010, 6, 1), 90.0),
                      (date(2024, 1, 2), 170.0)])
    for start in (date(2010, 6, 1), date(2024, 1, 2)):
        recent = _series([(start, 1.0)])
        out = long_history.splice(recent, legacy)
        assert out.index.min() == pd.Timestamp(2001, 3, 1)
        assert out.loc[pd.Timestamp(start)] == 1.0
        assert (out.index < pd.Timestamp(start)).sum() == len(
            [d for d in legacy.index if d < pd.Timestamp(start)])


def test_either_side_missing_is_handled():
    """No legacy -> the page is exactly what it was. No live feed -> the legacy
    series stands alone, which is complete and current rather than stale,
    because fetch_nearby already dropped the in-progress bar."""
    recent = _series([(date(2024, 1, 2), 170.0)])
    legacy = _series([(date(2001, 3, 1), 77.75)])
    empty = pd.Series(dtype=float)

    assert long_history.splice(recent, empty).equals(recent)
    assert long_history.splice(empty, legacy).equals(legacy)
    assert long_history.splice(recent, None).equals(recent)
    assert long_history.splice(empty, empty).empty


def test_a_legacy_feed_that_does_not_reach_back_adds_nothing():
    recent = _series([(date(2021, 11, 8), 132.1)])
    legacy = _series([(date(2021, 11, 8), 999.0), (date(2021, 11, 9), 999.0)])
    assert long_history.splice(recent, legacy).equals(recent)


# ------------------------------------------------------- wiring in the page

def _app_tree():
    return ast.parse(APP.read_text(encoding=ENCODING))


def test_the_schema_is_passed_at_every_call_site():
    """
    A default is not part of a cache key and an underscored argument is not
    hashed at all -- tests/test_cache_schema.py carries the full account. This
    pins the other half for this page: that the callers actually pass it.
    """
    tree = _app_tree()
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "build_continuous_series"]
    assert len(calls) == 3, f"expected 3 call sites, found {len(calls)}"
    for call in calls:
        passed = ast.unparse(call.args[-1])
        assert passed == "long_history.SCHEMA", ast.unparse(call)


def test_the_report_calendar_does_not_follow_the_chart():
    """
    It was `since = series.index.min()`, a ~5-year window only because that was
    all the feed had. Against a 2001 start that is four reports x 25 years of
    ESMIS pagination -- 25 releases a page, 29 pages for WASDE alone -- for a
    table of some 900 rows. Bounded on its own window, and the caption says so.
    """
    src = APP.read_text(encoding=ENCODING)
    assert "REPORT_CALENDAR_YEARS" in src
    assert "since = series.index.min().date().isoformat()" not in src
    tree = _app_tree()
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_continuous_chart")
    assign = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                  and ast.unparse(n.targets[0]) == "since")
    text = ast.unparse(assign.value)
    assert "REPORT_CALENDAR_YEARS" in text and "max(" in text, text


def test_the_page_level_note_no_longer_claims_the_page_starts_in_2021():
    """
    DATA_START_NOTE is a caption above EVERY tab. It said the history starts in
    2021, which is true of the per-contract overlays and, since the nearby
    chart reached 2001, false as a statement about the page -- the headline
    rule CLAUDE.md sets out, that a line must read correctly on its own.
    """
    note = ast.literal_eval(next(
        n.value for n in _app_tree().body
        if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "DATA_START_NOTE"))
    assert "2021" not in note, note
    assert "2001" in note
    assert "per-contract" in note.lower()
    # The overlays really are still capped, so the note must still say so.
    assert "overlay" in note.lower()


def test_the_module_names_no_hard_coded_series_start():
    """
    The page prints where the history begins; the three feeds start on three
    different dates and a fourth could be added. A constant here would be a
    second claim about the same fact, free to rot against the first.
    """
    src = (PAGE_DIR / "long_history.py").read_text(encoding=ENCODING)
    tree = ast.parse(src)
    starts = [n for n in tree.body if isinstance(n, ast.Assign)
              and ast.unparse(n.targets[0]) in {"FIRST_YEAR", "SERIES_START", "HANDOVER"}]
    assert not starts, "the start date belongs to the data, not to this module"
