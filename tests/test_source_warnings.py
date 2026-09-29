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


def test_the_pages_reload_path_reports_both_health_checks():
    """
    THE HALF THAT WAS MISSED. The structural test above pins gather(), which is
    the FETCH path -- and that half worked from the start. The page also has a
    cached-reload path (_load_ctx), which re-derives the warnings because
    st.session_state does not survive a refresh or a second browser tab. That
    path called only report_futures_health for a few hours on 2026-09-28, so
    pressing Fetch showed the full panel and reloading silently dropped the
    boxed-beef 3pm trap, the AMS 3208 PRELIMINARY note, the back-dated-build
    check and Friday's CFTC warning.

    Reading the page's source rather than importing it: apps/weekly_reports/app.py
    is a Streamlit script and executes on import.
    """
    from pathlib import Path

    app = (Path(__file__).resolve().parent.parent
           / "apps" / "weekly_reports" / "app.py").read_text(encoding="utf-8")
    start = app.index("def _load_ctx(")
    body = app[start:app.index("\nif fetch", start)]
    assert "report_futures_health" in body
    assert "report_source_health" in body, \
        "a reloaded page would show no source warnings over stale numbers"


# ── gaps the source audit found, 2026-09-28 ────────────────────────────────

def test_the_friday_letter_demands_that_fridays_kill_be_fridays():
    """
    sj_ls712.txt is a static "newest report" URL with no date filter, and
    fetch_slaughter takes the top week row of whatever it is served. On
    2026-09-25 an unrefreshed file would have printed 529,000 against a true
    484,000 -- a 45,000 head error flipping the week from -8.5% to +4.8%, with
    nothing on the page to suggest it.
    """
    friday = date(2026, 9, 25)
    ctx = healthy()
    ctx["cutout"]["report_date"] = "2026-09-25"
    ctx["daily_slaughter"]["report_date"] = "2026-09-25"
    ctx["cash"]["report_date"] = "2026-09-21"

    ctx["slaughter"] = {"report_date": "2026-09-25"}
    assert not any("Weekly slaughter" in e for e in warn(ctx, "friday", issue=friday))

    ctx["slaughter"] = {"report_date": "2026-09-18"}
    hits = [e for e in warn(ctx, "friday", issue=friday) if "Weekly slaughter" in e]
    assert len(hits) == 1
    assert "2026-09-18" in hits[0]


def test_only_friday_demands_equality():
    """
    On every other weekday the newest file IS last Friday's, and that is
    correct. Demanding equality there would fire four mornings out of five.
    """
    ctx = healthy()
    ctx["slaughter"] = {"report_date": "2026-09-25"}
    for kind in ("am", "recap", "tuesday"):
        assert not any("Weekly slaughter" in e for e in warn(ctx, kind))


def test_a_frozen_weekly_feed_is_caught_on_any_day():
    """The equality check is Friday-only, so the lag table covers the rest."""
    ctx = healthy()
    ctx["slaughter"] = {"report_date": "2026-09-11"}
    hits = [e for e in warn(ctx, "am") if "Built for" in e]
    assert len(hits) == 1
    assert "weekly slaughter is from 2026-09-11" in hits[0]


def test_grading_last_week_comes_from_usdas_own_field():
    """
    Pct_Choice_PW sits on the same row as Pct_Choice_CW. The old code took the
    previous ROW of the fetched window instead, which is only the prior week
    while the series is contiguous -- and the live LSWFEDCC history has a
    561-day hole between 2024-09-16 and 2026-03-31. Replaying the old code at
    that boundary printed "89.3 versus 82.6 LW", a fabricated 6.7-point swing
    where USDA's own field on that row said flat.
    """
    import pandas as pd

    rows = [  # the hole, as the API actually serves it
        {"report_date": "09/16/2024", "Pct_Choice_CW": "82.6", "Pct_Choice_PW": "82.4"},
        {"report_date": "03/31/2026", "Pct_Choice_CW": "89.3", "Pct_Choice_PW": "89.3"},
    ]
    g = pd.DataFrame(rows)
    g["report_date"] = pd.to_datetime(g["report_date"], errors="coerce")
    g["pct"] = pd.to_numeric(g.get("Pct_Choice_CW"), errors="coerce")
    g["pct_pw"] = pd.to_numeric(g.get("Pct_Choice_PW"), errors="coerce")
    g = g.dropna(subset=["report_date", "pct"]).sort_values("report_date")

    last = g.iloc[-1]
    assert round(float(last["pct_pw"]), 1) == 89.3, "USDA says flat"
    assert round(float(g.iloc[-2]["pct"]), 1) == 82.6, "the previous ROW is 18 months back"


def test_the_previous_row_is_no_longer_read_for_grading():
    """Structural: iloc[-2] was the whole bug and must not come back."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "letter" / "sources.py").read_text(
        encoding="utf-8")
    block = src[src.index('if sec.get("reportSection")'):src.index("# -- Slaughter and")]
    # COMMENTS STRIPPED FIRST. The explanation of the bug names iloc[-2], so a
    # raw substring search matches the prose that documents the fix and fails.
    # Exactly the trap tests/test_mailbox.py records for "$orderby".
    code = "\n".join(ln.split("#", 1)[0] for ln in block.splitlines())
    assert "Pct_Choice_PW" in code
    assert "iloc[-2]" not in code, "grading is reading the previous row again"


# ── the letter and the dashboard must agree ────────────────────────────────

def test_the_fci_change_rounds_the_values_not_the_difference():
    """
    2026-09-29: the brief printed "-0.17 at 337.63" while the FCI dashboard
    showed the same 337.63 down 0.16. Neither was wrong in isolation -- the
    raw move was -0.169151, and the two differ only in WHERE they round.

    The dashboard rounds each value to display precision first, on purpose
    (see the day_chg comment in apps/cme_feeder_cattle/app.py). The letter now
    does the same, because the letter PRINTS 337.63 today and printed 337.79
    yesterday: a reader holding both subtracts them and gets 0.16. A change
    that disagrees with the letter's own published figures is wrong however it
    was computed.
    """
    a, b = 337.6253146459304, 337.7944658030682     # the real rows
    rounded_difference = round(a - b, 2)
    difference_of_rounded = round(round(a, 2) - round(b, 2), 2)
    assert rounded_difference == -0.17               # what the letter used to do
    assert difference_of_rounded == -0.16            # what the dashboard does

    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "letter" / "sources.py").read_text(
        encoding="utf-8")
    block = src[src.index("def fetch_feeder_index("):]
    block = block[:block.index("def fetch_douglas_ytd(")]
    code = "\n".join(ln.split("#", 1)[0] for ln in block.splitlines())
    assert "round(shown - prev_shown, 2)" in code
    assert "round(value - prev_val, 2)" not in code, \
        "the FCI change is rounding the difference again; it will disagree with the dashboard"


# ── the weekly kill is an estimate, and says so ────────────────────────────

def test_the_weekly_slaughter_line_names_its_week_and_marks_it_estimated():
    """
    SJ_LS712 publishes on the FRIDAY for the week ending the SATURDAY AFTER,
    so the headline count has two days still projected in it. Worse, the three
    figures on that line are not the same kind of number -- USDA marks the
    rows Estimate / Estimate / Actual in the file -- so the -8.5% that falls
    out of the first two reads as a measurement when it is a projection
    against a revised estimate.

    Verified live 2026-09-29: report_date 2026-09-25, week_ending 2026-09-26.
    """
    from letter import render

    assert render._week_tag("2026-09-26") == " (est., w/e 9/26)"
    row = (f"Weekly slaughter{render._week_tag('2026-09-26')}: 484,000")
    assert row.startswith("Weekly slaughter (est., w/e 9/26):")


def test_an_unparseable_week_still_says_estimate():
    """
    The date is the nicety; "est." is the part that stops a projection being
    read as a count. A label nobody can check is worse than none, so the date
    drops and the warning stays.
    """
    from letter import render

    for bad in (None, "", "garbage", "2026-13-45"):
        assert render._week_tag(bad) == " (est.)"


def test_the_docstring_no_longer_has_the_timing_backwards():
    """
    It said "covering the week ending the previous Saturday" until 2026-09-29,
    which is a week out in the wrong direction and is why nobody questioned
    the headline. A comment that is confidently wrong is worse than no comment.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "letter" / "sources.py").read_text(
        encoding="utf-8")
    block = src[src.index("def fetch_slaughter("):]
    block = block[:block.index('r = _session().get(AMS_SJ_LS712')]
    assert "SATURDAY AFTER IT" in block, "the corrected timing is missing"
    # THE OLD SENTENCE IS STILL IN THERE, ON PURPOSE -- the docstring quotes it
    # to say it was wrong. So this checks it appears ONCE and only as history,
    # not that it is absent. Searching for the bare phrase matched the very
    # correction it was meant to verify, which is the fourth time in two days
    # a test here has asserted against the prose explaining its own fix.
    assert block.count("the week ending the previous Saturday") == 1
    assert 'READ "the week ending the previous Saturday"' in block, \
        "the old timing must be marked as superseded, not left reading as current"
