"""
Which report the authoring page opens on.

THE TRAP IS THE CLOCK, NOT THE HOUR. Streamlit Cloud runs UTC. At 07:30 in
Anthon it is 12:30 UTC, already past a noon switch, so a plain datetime.now()
on the deployed app would open on PM every single morning -- the exact case the
feature exists to handle, failing in the exact place it is needed.

The tests below pin both halves: the split itself, and that it is read in
Central rather than whatever the host thinks the time is.

    python -m pytest tests/test_session_default.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from letter import config

CENTRAL = ZoneInfo(config.LETTER_TZ)


def _central(h, m=0, day=24):
    return datetime(2026, 9, day, h, m, tzinfo=CENTRAL)


@pytest.mark.parametrize("hour", [0, 6, 7, 9, 11])
def test_morning_opens_on_am(hour):
    assert config.session_for_now(_central(hour)) == "AM"


@pytest.mark.parametrize("hour", [12, 13, 17, 20, 23])
def test_afternoon_opens_on_pm(hour):
    assert config.session_for_now(_central(hour)) == "PM"


def test_noon_exactly_is_pm():
    """The boundary belongs to the afternoon; the switch is 'before noon'."""
    assert config.session_for_now(_central(11, 59)) == "AM"
    assert config.session_for_now(_central(12, 0)) == "PM"


def test_the_utc_trap():
    """
    07:30 Central is 12:30 UTC. Reading the server's clock would call that PM.
    This asserts the function is given a Central time and answers AM for it --
    the deployed failure this whole thing is about.
    """
    morning = _central(7, 30)
    assert morning.astimezone(timezone.utc).hour == 12      # past a naive switch
    assert config.session_for_now(morning) == "AM"


def test_it_is_not_reading_the_hosts_timezone():
    """A UTC-stamped 13:00 is 08:00 Central and must read as morning."""
    utc_1pm = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)
    assert config.session_for_now(utc_1pm.astimezone(CENTRAL)) == "AM"


def test_no_tz_database_falls_back_rather_than_raising(monkeypatch):
    """One click lost, not a page. The gate is the try/except in config."""
    import letter.config as cfg

    def _boom(*a, **k):
        raise KeyError("no tz database")

    monkeypatch.setattr("zoneinfo.ZoneInfo", _boom)
    assert cfg.session_for_now() == cfg.DEFAULT_SESSION


def test_live_call_returns_a_real_session():
    assert config.session_for_now() in config.SESSIONS
