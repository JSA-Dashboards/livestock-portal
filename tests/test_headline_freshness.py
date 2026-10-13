"""
How old the headline candidate list is, and saying so.

THE LIST NEVER REFRESHES ITSELF. `headlines.candidates()` is a dozen HTTP
calls, so it runs on a button press and lives in session_state until the
button is pressed again. That is the right trade and it is invisible: a list
pulled at breakfast renders identically to one pulled a minute ago.

Sterling's Profit Tracker landed at 2:15pm on 2026-10-13 and was missing from
Ross's panel all afternoon. Nothing was broken -- the mailbox was connected,
the sender filter matched, and the mail was sitting at position 4 of 39 the
moment the button was pressed again. The panel simply had no way to say that
what it was showing predated the email.

So these tests are about one property: **the panel can always date itself**.
The phrase is cosmetic; the stamp, and the guard that every fetch writes one,
are not.

    python -m pytest tests/test_headline_freshness.py -q
"""
from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from letter import config  # noqa: E402

PAGE = REPO / "apps" / "weekly_reports" / "app.py"
SRC = PAGE.read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _ns():
    """The helpers, lifted out of a module that cannot be imported.

    app.py is a Streamlit script -- importing it runs the page. Exec'ing just
    these defs runs the REAL code rather than a copy of it, which is the whole
    point: a copy in a test file is the `snowflake_db.py`-times-five problem
    in miniature.
    """
    wanted = {"_age_minutes", "_age_phrase"}
    defs = [n for n in TREE.body
            if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {d.name for d in defs} == wanted, "the page no longer defines both helpers"
    consts = [n for n in TREE.body
              if isinstance(n, ast.Assign)
              and getattr(n.targets[0], "id", None) == "_HEADS_STALE_MIN"]
    assert consts, "_HEADS_STALE_MIN is gone"
    ns = {"config": config}
    exec(compile(ast.Module(body=consts + defs, type_ignores=[]), "<page>", "exec"), ns)
    return ns


NS = _ns()


# -- the sentence --------------------------------------------------------

def test_the_phrase_reads_on_its_own_at_every_scale():
    """The standing rule: a line a reader meets alone must be unambiguous."""
    phrase = NS["_age_phrase"]
    assert phrase(0) == "just now"
    assert phrase(1) == "1m ago"
    assert phrase(29) == "29m ago"
    assert phrase(59) == "59m ago"
    assert phrase(60) == "1h 00m ago"
    assert phrase(83) == "1h 23m ago"
    assert phrase(1440) == "24h 00m ago"


def test_an_unstamped_list_says_nothing_rather_than_guessing():
    """A list from before this existed carries no stamp. Printing '0m ago'
    over it would be worse than the silence it replaces."""
    assert NS["_age_phrase"](None) is None
    assert NS["_age_minutes"](None) is None


# -- the clock -----------------------------------------------------------

def test_the_age_is_measured_not_read_back_out_of_its_own_string():
    """`_age_phrase` takes MINUTES. The first draft parsed the number back out
    of 'Nh MMm ago' to decide whether to warn, so the sentence and the warning
    could disagree about the same list."""
    sig = next(n for n in TREE.body
               if isinstance(n, ast.FunctionDef) and n.name == "_age_phrase")
    assert [a.arg for a in sig.args.args] == ["mins"]


def test_it_measures_against_central_not_the_servers_clock():
    """Streamlit Cloud runs UTC. A naive now() against a Central stamp reads
    five hours stale every afternoon -- the trap session_for_now() exists for."""
    then = config.now_central() - timedelta(minutes=45)
    assert NS["_age_minutes"](then) == 45


def test_a_host_with_no_tz_database_is_dateless_not_broken():
    """now_central() falls back to a NAIVE datetime there, and subtracting an
    aware stamp from a naive now raises. A caption is not worth a page."""
    naive_now = datetime(2026, 10, 13, 15, 0)
    aware_then = datetime(2026, 10, 13, 14, 15, tzinfo=timezone.utc)
    assert NS["_age_minutes"](aware_then, naive_now) is None


def test_the_clock_never_runs_backwards():
    """A stamp from the future -- a DST step, a clock correction -- must not
    print '-1h 59m ago'."""
    assert NS["_age_minutes"](config.now_central() + timedelta(minutes=5)) == 0


def test_now_central_is_aware():
    assert config.now_central().tzinfo is not None


# -- the wiring, which is the part that actually failed ------------------

def test_every_fetch_stamps_when_it_happened():
    """THE REGRESSION GUARD. A third call site added later without a stamp
    leaves the panel dating the list from some other fetch -- older than it
    is, or newer. Both are worse than no date at all."""
    fn = next(n for n in TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "_fetch_heads")
    inside = set(map(id, ast.walk(fn)))          # the one legitimate writer
    direct = [n for n in ast.walk(TREE)
              if isinstance(n, ast.Subscript)
              and isinstance(n.slice, ast.Constant)
              and n.slice.value == "wcr_heads"
              and isinstance(getattr(n, "ctx", None), ast.Store)
              and id(n) not in inside]
    assert not direct, (
        "something assigns st.session_state['wcr_heads'] directly; go through "
        "_fetch_heads so the stamp cannot be forgotten")


def test_the_candidate_fetch_has_exactly_one_call_site():
    calls = [n for n in ast.walk(TREE)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "candidates"
             and getattr(n.func.value, "id", None) == "headlines"]
    assert len(calls) == 1, (
        f"headlines.candidates() is called {len(calls)} times; only _fetch_heads "
        "should call it, or a fetch lands unstamped")
    fn = next(n for n in TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "_fetch_heads")
    assert calls[0] in list(ast.walk(fn)), "the fetch moved out of _fetch_heads"


def test_fetch_heads_writes_both_the_list_and_the_stamp():
    fn = next(n for n in TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "_fetch_heads")
    body = ast.unparse(fn)
    assert "'wcr_heads'" in body and "'wcr_heads_at'" in body


def test_the_panel_dates_itself_above_the_rows():
    """Placement, not decoration. The age decides whether anything under it is
    worth reading, so it cannot be a footnote below thirty-nine checkboxes."""
    age_at = SRC.index('_age_minutes(st.session_state.get("wcr_heads_at"))')
    rows_at = SRC.index('for n, item in enumerate(found.get("items", []))')
    assert age_at < rows_at, "the age line moved below the candidate rows"


def test_the_stale_line_names_what_arrives_late():
    """A nudge that does not say WHY it is nudging gets dismissed. Sterling's
    Profit Tracker is the email that started this."""
    warn = SRC[SRC.index("_HEADS_STALE_MIN:"):]
    warn = warn[:warn.index("for err in found")]
    assert "Fetch headlines" in warn
    assert "Sterling" in warn


def test_the_threshold_is_shorter_than_an_afternoon():
    """Ross writes the evening letter over an hour or two. A threshold longer
    than that never fires inside the window it exists for."""
    assert 5 <= NS["_HEADS_STALE_MIN"] <= 45
