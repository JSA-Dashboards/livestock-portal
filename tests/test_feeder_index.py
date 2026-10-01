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
