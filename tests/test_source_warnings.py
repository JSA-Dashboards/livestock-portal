"""
The USDA sources' freshness warnings, and where they are allowed to appear.

WHY THIS FILE EXISTS. Every check in build.report_source_health was already
written and already correct -- as a print() inside build.main. Ross writes the
letter on the deployed Streamlit page, which renders the `errors` list and
nothing else, so he had never once seen "Boxed beef is the 2026-09-25 print,
not 2026-09-28's". It was being explained to a terminal nobody was looking at.
Found 2026-09-28, the same day the futures path turned out to have the same
gap, and fixed the same way.

THE HARDER HALF IS RESTRAINT. Two of these checks fire on a perfectly ordinary
day if you move them naively:

  the cutout      The MORNING brief quotes the previous session's cutout by
                  design -- a 07:30 letter has no 3pm print to quote. Warning
                  there would fire every single weekday about the letter
                  working correctly.

  cash trade      The 5-area weekly weighted average always describes the
                  PRIOR week, so it is seven days behind on a Monday by
                  design, not by failure.

A panel that cries every morning stops being read on the morning it matters,
which is exactly how the futures outage got into a letter. So the tests below
pin the silence as hard as they pin the warnings.

    python -m pytest tests/test_source_warnings.py -q

Offline: these build a ctx by hand and call the reporter. Nothing is fetched.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from letter import build  # noqa: E402

MONDAY = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def snowflake_on(monkeypatch):
    """Every test below is about a source, not about the Snowflake fallback."""
    monkeypatch.setenv("USE_SNOWFLAKE", "1")


def healthy():
    """Exactly what Monday 2026-09-28 looked like once the futures were fixed."""
    return {
        "cutout": {"report_date": "2026-09-25", "choice": {"value": 378.83}},
        "daily_slaughter": {"report_date": "2026-09-25", "status": "Final"},
        "cash": {"report_date": "2026-09-21"},
        "cftc": {},
    }


def warn(ctx, kind="am", issue=MONDAY):
    errors: list = []
    build.report_source_health(ctx, issue, kind, errors)
    return errors


# ── silence on an ordinary day ─────────────────────────────────────────────

def test_an_ordinary_morning_says_nothing():
    """
    THE MOST IMPORTANT TEST HERE. Cutout three days back, cash seven days back,
    slaughter final -- all correct, all normal, and the panel must be empty.
    """
    assert warn(healthy(), "am") == []


def test_the_morning_brief_never_warns_about_yesterdays_cutout():
    """
    A 07:30 letter cannot have a 3pm print. Firing here would put a warning on
    every weekday morning of the year.
    """
    assert not any("Boxed beef" in e for e in warn(healthy(), "am"))


def test_cash_seven_days_back_is_not_stale():
    """
    The 5-area weekly weighted average describes the prior week. Seven days on
    a Monday is the series, not a failure -- MAX_REPORT_LAG_DAYS gives it ten.
    """
    assert not any("cash trade" in e for e in warn(healthy(), "recap"))


# ── the warnings that should fire ──────────────────────────────────────────

def test_the_evening_letter_does_warn_about_yesterdays_cutout():
    """
    The PM letter is written after 3pm and wants today's print. An older one
    means the release has not landed -- which is why the 9/22 letter's Choice
    and Select had to be typed by hand.
    """
    hits = [e for e in warn(healthy(), "recap") if "Boxed beef" in e]
    assert len(hits) == 1
    assert "2026-09-25" in hits[0] and "3pm Central" in hits[0]


def test_a_preliminary_3208_is_flagged():
    ctx = healthy()
    ctx["daily_slaughter"]["status"] = "Preliminary"
    hits = [e for e in warn(ctx, "am") if "3208" in e]
    assert len(hits) == 1
    assert "PRELIMINARY" in hits[0] and "revised" in hits[0]


def test_a_missing_status_is_not_treated_as_preliminary():
    """Absent is not the same as provisional; do not invent an alarm."""
    ctx = healthy()
    ctx["daily_slaughter"].pop("status")
    assert not any("3208" in e for e in warn(ctx, "am"))


def test_cash_two_weeks_back_is_stale():
    """Past its own allowance it is a real problem, and it says which report."""
    ctx = healthy()
    ctx["cash"]["report_date"] = "2026-09-07"
    hits = [e for e in warn(ctx, "am") if "Built for" in e]
    assert len(hits) == 1
    assert "cash trade is from 2026-09-07" in hits[0]


def test_a_back_dated_rebuild_is_caught():
    """
    These AMS endpoints serve the newest report and take no date filter, so
    rebuilding an old letter silently reports today's numbers under its date.
    """
    hits = [e for e in warn(healthy(), "am", issue=date(2026, 9, 10))
            if "Built for" in e]
    assert len(hits) == 1
    assert "boxed beef" in hits[0] and "daily slaughter" in hits[0]


def test_cftc_is_checked_on_friday_and_only_friday():
    ctx = healthy()
    ctx["cftc"] = {"as_of": "2026-09-15"}
    assert any("CFTC" in e for e in warn(ctx, "friday", issue=date(2026, 9, 25)))
    assert not any("CFTC" in e for e in warn(ctx, "am"))
    assert not any("CFTC" in e for e in warn(ctx, "recap"))


def test_the_sqlite_fallback_is_loud(monkeypatch):
    """
    Without USE_SNOWFLAKE the feeder index comes from a committed SQLite file
    that is stale by construction. Silent on the deployed app, where it is set.
    """
    monkeypatch.delenv("USE_SNOWFLAKE", raising=False)
    hits = [e for e in warn(healthy(), "am") if "USE_SNOWFLAKE" in e]
    assert len(hits) == 1


# ── and it has to reach the page ───────────────────────────────────────────

def test_gather_reports_source_health_before_returning():
    """
    ORDER AND PLACE. The Streamlit page calls gather() directly and never goes
    through build.main, which is exactly how these warnings stayed invisible
    for as long as they lived in main. Structural, because both the function
    and the call exist either way -- only the location distinguishes the bug
    from the fix.
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "letter" / "build.py").read_text(
        encoding="utf-8")
    gather = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "gather")
    called = {n.func.id for n in ast.walk(gather)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "report_source_health" in called, "the page would see no source warnings"


def test_the_checks_are_not_also_printed_in_main():
    """
    They were moved, not copied. Two copies drift, and the CLI already prints
    everything in the errors list -- a duplicate would just read as two
    problems where there is one.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "letter" / "build.py").read_text(
        encoding="utf-8")
    assert src.count("LM_XB403 PM releases") == 1
    assert src.count("These AMS endpoints always") == 1
    assert "! Boxed beef is the" not in src
