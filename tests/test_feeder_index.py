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
    # headline rule runs here -- "the first business day after CME's last
    # published file" -- and these tests would catch a change to it rather
    # than quietly re-implementing it in a fake.


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
    CME has not printed the headline date by definition -- it is the first
    business day AFTER their last file -- so the headline must stay JSA's
    number. Only the PRIOR date gets overridden.
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


# -- The weekend carry-forward, 2026-10-20 --------------------------------
#
# Ross, writing the Tuesday letter: "the feeder cattle index isn't updating
# to either today's FCI - which the CME just released - or using our JSA
# Daily FCI Estimate. It's stale with yesterday's CME fci."
#
# Two things combined, and both of these rows are the real ones.
#
#   fci_daily CARRIES FRIDAY FORWARD. 10-17 and 10-18 hold Friday's
#   343.45715454692953 to the digit, with no same-day price on either. They
#   are filler; nothing trades on a Sunday.
#
#   THE HEADLINE DEGRADES ONTO A REAL SESSION. headline_index_date() returns
#   the business day after CME's last file only while we hold an estimate for
#   it. The MARS ingest had not produced 10-20 yet, so it fell back to
#   max(available) = 10-19 -- which is exactly the date CME had just
#   published, and "the last date before the headline" then skipped it for
#   Sunday's filler.
WEEKEND_OURS = pd.DataFrame({
    "date": ["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"],
    "fci_value": [343.5498980512278, 343.45715454692953, 343.45715454692953,
                  343.45715454692953, 342.16265226582874],
})
WEEKEND_PUBLISHED = pd.DataFrame({
    "date": ["2026-10-15", "2026-10-16", "2026-10-19"],
    "fci_value": [343.54, 343.45, 342.16],
})


def test_the_published_line_is_the_index_cme_actually_printed(monkeypatch):
    """What the evening letter prints. It read 343.46 for Sunday 10-18."""
    _install(monkeypatch, WEEKEND_OURS, WEEKEND_PUBLISHED)
    pub = sources.fetch_feeder_index()["published"]
    assert pub["value"] == 342.16
    assert pub["date"] == "2026-10-19"
    assert pub["from_cme"] is True


def test_the_published_change_matches_cmes_own_reported_change(monkeypatch):
    """
    THE FREE AUDIT. cme_ftp_daily carries REPORTED_CHANGE, and CME printed
    -1.29 for 10-19. Differenced against Sunday's filler it came out -1.30,
    because merged holds CME's rounded 343.45 for Friday and our unrounded
    343.457 for the filler. One cent, on the figure the letter and the
    dashboard must agree about.
    """
    _install(monkeypatch, WEEKEND_OURS, WEEKEND_PUBLISHED)
    fci = sources.fetch_feeder_index()
    assert fci["published"]["change"] == -1.29      # CME's REPORTED_CHANGE
    assert fci["change"] == -1.29                   # and the headline's too


def test_the_published_date_is_never_a_weekend(monkeypatch):
    """The property, rather than this one Tuesday's numbers."""
    import datetime as _dt
    _install(monkeypatch, WEEKEND_OURS, WEEKEND_PUBLISHED)
    pub = sources.fetch_feeder_index()["published"]
    assert _dt.date.fromisoformat(pub["date"]).weekday() < 5


def test_a_missing_cme_table_still_skips_the_filler(monkeypatch):
    """
    The deployed app had no cme_ftp_daily on 2026-10-07, so this path is
    live. It must not fall back to the forward estimate -- and it must not
    land on a Sunday either.
    """
    _install(monkeypatch, WEEKEND_OURS, None)
    fci = sources.fetch_feeder_index()
    pub = fci["published"]
    assert pub is not None, "a missing CME table must not blank the line"
    assert pub["from_cme"] is False
    # Friday, not Sunday: the headline degrades to 10-19 with no CME series,
    # so the last completed session before it is 10-16 and NOT 10-18.
    assert pub["date"] == "2026-10-16"
    assert pub["value"] == 343.46
    assert pub["change"] == -0.09


def test_the_headline_is_still_our_own_estimate_for_its_date(monkeypatch):
    """Nothing here may move the morning brief's figure off fci_daily."""
    _install(monkeypatch, WEEKEND_OURS, WEEKEND_PUBLISHED)
    fci = sources.fetch_feeder_index()
    assert fci["source"] == "JSA estimate (fci_daily)"
    assert fci["date"] == "2026-10-19"
