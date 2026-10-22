"""
The FCI line: whose number is it, for which date.

fci_daily is JSA's MARS RECONSTRUCTION. Its job is the trailing day or two
CME has not printed yet -- a prediction, not a stand-in for data CME has
already released. The dashboard's load_data() says so in its priority order
and honours it; this function read cme_ftp_daily for its DATE and threw the
value away, so a superseded estimate stayed in the arithmetic.

What it cost, reported by Ross on 2026-10-01 as "the daily fci estimate is
1.02 higher". CME published 2026-09-29 at 338.03; our own estimate for that
date was 338.68 and was never replaced:

    339.05 - 338.68 (our stale estimate) = +0.37   <- the brief printed this
    339.05 - 338.03 (CME's published)    = +1.02   <- the dashboard showed this

Both numbers were real, so nothing raised. A change that contradicts the
dashboard is wrong however it was computed.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from letter import sources  # noqa: E402

# The real rows, straight from JSA.CME_FEEDER_CATTLE on 2026-10-01.
OURS = pd.DataFrame({
    "date": ["2026-09-28", "2026-09-29", "2026-09-30"],
    "fci_value": [337.771262, 338.683398, 339.052830],
})
PUBLISHED = pd.DataFrame({
    "date": ["2026-09-28", "2026-09-29"],
    "fci_value": [337.77, 338.03],
})


class _FakeConn:
    def close(self):
        pass


def _install(monkeypatch, ours, published):
    """Stub the two private module loaders fetch_feeder_index uses."""
    class DB:
        @staticmethod
        def get_conn():
            return _FakeConn()

        @staticmethod
        def read_sql_lower(sql, conn):
            if "cme_ftp_daily" in sql:
                if published is None:
                    raise RuntimeError("no such table")
                return published.copy()
            return ours.copy()

    monkeypatch.setattr(sources, "_load_fci_db", lambda: DB)
    # index_dates is NOT stubbed. It has no database of its own, so the real
    # headline rule runs here -- since 2026-10-22, "the freshest complete
    # estimate": the most recent weekday strictly before today. These tests
    # would catch a change to it rather than quietly re-implementing it in a
    # fake, which is how they caught that change.


def test_the_change_uses_cmes_published_prior_not_our_estimate(monkeypatch):
    """The reported bug, with the real numbers."""
    _install(monkeypatch, OURS, PUBLISHED)
    out = sources.fetch_feeder_index()
    assert out["value"] == 339.05
    assert out["change"] == 1.02, (
        f"got {out['change']} -- a superseded estimate is still in the subtraction"
    )


def test_the_headline_value_stays_our_own_estimate(monkeypatch):
    """
    The headline must stay JSA's number whenever CME has not printed that date,
    and only the PRIOR date gets overridden.

    NOT "by definition" ANY MORE. Until 2026-10-22 the headline was the first
    business day AFTER CME's last file, so it could never be a printed date and
    this held for free. The rule now follows the calendar instead, so once CME
    catches up the headline CAN be a date CME has published -- and then the
    value is rightly CME's, and the page relabels the tile "Current Index".
    Here CME stops at 09-29 and the headline is 09-30, so ours still wins.
    """
    _install(monkeypatch, OURS, PUBLISHED)
    out = sources.fetch_feeder_index()
    assert out["value"] == 339.05            # ours, rounded
    assert out["date"] == "2026-09-30"
    assert out["cme_last_published"] == "2026-09-29"


def test_no_cme_table_degrades_to_our_own_series(monkeypatch):
    """
    A missing or unreadable cme_ftp_daily must not take the line down; it
    falls back to estimate-to-estimate, which is what it always was.
    """
    _install(monkeypatch, OURS, None)
    out = sources.fetch_feeder_index()
    assert out["value"] == 339.05
    assert out["change"] == 0.37


def test_values_are_still_rounded_before_differencing(monkeypatch):
    """
    The convention from 2026-09-29 survives: round both, then subtract, so a
    reader holding two of our letters can subtract the printed figures and
    get the printed change. Raw 338.683398 -> 338.68, and 339.052830 ->
    339.05, so an unpublished prior gives exactly 0.37 and not 0.369432.
    """
    _install(monkeypatch, OURS, None)
    assert sources.fetch_feeder_index()["change"] == 0.37


@pytest.mark.parametrize("published_value,expected", [
    (338.03, 1.02),
    (338.68, 0.37),     # CME agreeing with us changes nothing
    (339.05, 0.00),
])
def test_the_prior_tracks_whatever_cme_actually_printed(monkeypatch, published_value, expected):
    pub = pd.DataFrame({"date": ["2026-09-29"], "fci_value": [published_value]})
    _install(monkeypatch, OURS, pub)
    assert sources.fetch_feeder_index()["change"] == expected


# -- Which session the letter quotes -------------------------------------
#
# Settled over two days and two reports from Ross.
#
# 2026-10-20, the Tuesday: the line printed 343.46 dated SUNDAY 10/18 --
# Friday's number -- where CME had published 342.16 for Monday that
# morning. fci_daily carries Friday forward over the weekend (10/17 and
# 10/18 both hold 343.45715454692953 to the digit) and the old rule took
# "the last date before the headline", which on a Tuesday is Sunday.
#
# 2026-10-21, the Wednesday: *"now my email for this afternoon isn't
# updating to today's fci estimate or the cme fci."* CME had computed
# 10/20 and it was on his QST screen, but the only channel this pipeline
# reads is the FTP settlement archive, which lands the next day about
# 13:00-14:35 CT and on that day had not landed at all by 16:14. Keying
# the line on CME's archive alone therefore froze it on Monday.
#
# Ross's call: the most recent COMPLETED session, CME's print where they
# have archived it and ours where they have not. Our reconstruction is
# within 0.022 of their print over the 21 days both cover (median 0.004),
# so that costs a rounding cent and buys a day of currency.
#
# Real rows throughout.
OURS_1021 = pd.DataFrame({
    "date": ["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18",
             "2026-10-19", "2026-10-20", "2026-10-21"],
    "fci_value": [343.5498980512278, 343.45715454692953, 343.45715454692953,
                  343.45715454692953, 342.16265226582874,
                  342.77714544819287, 342.0953710021258],
})
PUBLISHED_1021 = pd.DataFrame({
    "date": ["2026-10-15", "2026-10-16", "2026-10-19"],
    "fci_value": [343.54, 343.45, 342.16],
})
# The Tuesday, before our 10/20 and 10/21 rows existed.
OURS_1020 = OURS_1021.iloc[:5].copy()


def test_the_tuesday_printed_a_sundays_filler(monkeypatch):
    """2026-10-20. It read 343.46 for Sunday 10/18; CME had printed 342.16."""
    _install(monkeypatch, OURS_1020, PUBLISHED_1021)
    pub = sources.fetch_feeder_index(today=date(2026, 10, 20))["published"]
    assert pub["value"] == 342.16
    assert pub["date"] == "2026-10-19"
    assert pub["from_cme"] is True, "CME's print must win for a date they cover"


def test_the_change_matches_cmes_own_reported_change(monkeypatch):
    """
    THE FREE AUDIT. cme_ftp_daily carries REPORTED_CHANGE and CME printed
    -1.29 for 10/19. Differenced against Sunday's filler it came out -1.30,
    because merged holds CME's rounded 343.45 for Friday and our unrounded
    343.457 for the filler. One cent, on the figure the letter and the
    dashboard must agree about.
    """
    _install(monkeypatch, OURS_1020, PUBLISHED_1021)
    fci = sources.fetch_feeder_index(today=date(2026, 10, 20))
    assert fci["published"]["change"] == -1.29
    assert fci["change"] == -1.29


def test_the_wednesday_moves_on_without_cmes_archive(monkeypatch):
    """
    2026-10-21. CME's archive still stops at 10/19, but Tuesday is a
    finished session and we hold it, so that is what the letter quotes.
    """
    _install(monkeypatch, OURS_1021, PUBLISHED_1021)
    fci = sources.fetch_feeder_index(today=date(2026, 10, 21))
    pub = fci["published"]
    assert pub["value"] == 342.78
    assert pub["date"] == "2026-10-20"
    assert pub["from_cme"] is False, "ours, and the source line must say so"
    # against Monday, which is CME's own print -- 342.78 - 342.16
    assert pub["change"] == 0.62


def test_it_is_never_todays_unfinished_session(monkeypatch):
    """
    THE PROPERTY THE OLD RULE WAS REALLY PROTECTING. Today's row exists
    from the first barn report -- 10/21 stood at 248 locations and 868
    same-day head against Tuesday's 303 and 19,504 -- and quoting it as
    the index is the 2026-10-07 defect over again.
    """
    _install(monkeypatch, OURS_1021, PUBLISHED_1021)
    for day in (date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)):
        pub = sources.fetch_feeder_index(today=day)["published"]
        assert pub["date"] < day.isoformat(), f"quoted an unfinished session on {day}"


def test_the_date_is_never_a_weekend(monkeypatch):
    """Monday and Tuesday both reach back past the carry-forward rows."""
    _install(monkeypatch, OURS_1021, PUBLISHED_1021)
    for day in (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)):
        pub = sources.fetch_feeder_index(today=day)["published"]
        assert date.fromisoformat(pub["date"]).weekday() < 5, f"weekend row on {day}"


def test_a_missing_cme_table_still_answers(monkeypatch):
    """
    The deployed app had no cme_ftp_daily on 2026-10-07, so this path is
    live. It must not blank the line and must not fall back to the forward
    estimate -- it is our own completed session, labelled as ours.
    """
    _install(monkeypatch, OURS_1021, None)
    fci = sources.fetch_feeder_index(today=date(2026, 10, 21))
    pub = fci["published"]
    assert pub is not None, "a missing CME table must not blank the line"
    assert pub["date"] == "2026-10-20"
    assert pub["value"] == 342.78
    assert pub["from_cme"] is False


def test_the_headline_is_still_our_own_estimate(monkeypatch):
    """Nothing here may move the morning brief's figure off fci_daily."""
    _install(monkeypatch, OURS_1021, PUBLISHED_1021)
    fci = sources.fetch_feeder_index(today=date(2026, 10, 21))
    assert fci["source"] == "JSA estimate (fci_daily)"


def test_today_is_injectable_so_the_tests_are_not_a_function_of_the_clock():
    """
    What counts as a completed session depends on today's date. A test
    reading the real clock passes in October and fails in November for no
    reason anyone will remember.
    """
    import inspect
    assert "today" in inspect.signature(sources.fetch_feeder_index).parameters
