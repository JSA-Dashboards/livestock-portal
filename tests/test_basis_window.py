"""The border basis is bucketed by OPEN WINDOW, never by calendar year.

The tile read "2026 Avg Basis" over the mean spread of calendar 2026. Every
figure it printed was correct, and would have stayed correct until 1 January
-- when it would have rolled to a near-empty "2027 Avg Basis" while the window
that opened on 2026-08-24 ran on unbroken, and the table two tabs below split
that one window into two rows. Three means for one stretch of trade, each
honestly computed, nothing raising: the letter-versus-dashboard failure this
repo has shipped five times, arriving inside a single page.

The border is shut for long stretches -- screwworm closed it in Nov 2024, it
quoted Feb-May 2025, shut again, and reopened 2026-08-24 -- so a calendar year
splits one trading window and pools two others. It is not the unit.

    python -m pytest tests/test_basis_window.py -q
"""

import ast
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "mexican_feeder_imports")
sys.path.insert(0, _APP)

import border as bd  # noqa: E402

PAGE = os.path.join(_APP, "app.py")


def _page():
    # utf-8-sig: two pages in this repo carry a BOM and ast.parse rejects it.
    return open(PAGE, encoding="utf-8-sig").read()


def _code_of(fn):
    """A function's source with its DOCSTRING removed.

    This guard failed first against spread_windows()'s own docstring, which
    explains why it does NOT call reopening() -- the trap tests/test_rundown.py
    and tests/test_border_crossing_label.py both record. A guard that trips
    over the note describing the rule reads exactly like the rule being broken.
    """
    import inspect
    fnode = ast.parse(inspect.getsource(fn).lstrip()).body[0]
    body = fnode.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return chr(10).join(ast.unparse(n) for n in body)


# The real shape of the series, as measured against Snowflake on 2026-10-21:
# 84 quoted days in two runs separated by 470 days.
W1 = ("2025-02-20", "2025-05-12")
W2 = ("2026-08-25", "2026-10-20")


def _real_dates():
    """The two runs, as contiguous business-ish days -- enough to exercise the
    splitter without a warehouse. Only the GAP matters to it."""
    out = []
    d = date(2025, 2, 20)
    while d <= date(2025, 5, 12):
        out.append(d.isoformat())
        d = date.fromordinal(d.toordinal() + 1)
    d = date(2026, 8, 25)
    while d <= date(2026, 10, 20):
        out.append(d.isoformat())
        d = date.fromordinal(d.toordinal() + 1)
    return out


# ── the splitter ────────────────────────────────────────────────────────────

def test_the_splitter_is_pure_and_needs_no_connection():
    """Pure on purpose: the boundaries are the whole correctness of this
    change, and a test that needs a warehouse to check them is a test that
    does not run."""
    bounds = bd._window_bounds(_real_dates())
    assert len(bounds) == 2, bounds
    assert bounds[0][0] == W1[0] and bounds[0][1] == W1[1]
    assert bounds[1][0] == W2[0] and bounds[1][1] == W2[1]


def test_the_threshold_is_not_load_bearing():
    """Measured, not chosen. The series has exactly one gap of 20+ days and it
    is 470 long, so every threshold in that range gives the same two windows.
    If this ever starts failing, the data has changed shape and the constant
    needs re-deriving rather than nudging."""
    dates = _real_dates()
    for gap in (20, 30, 45, 60, 90, 120, 180, 400):
        assert bd._window_bounds(dates, gap) == bd._window_bounds(dates, 45), (
            f"gap_days={gap} changes the windows; the threshold has become "
            f"a fitted parameter")


def test_one_run_is_one_window():
    assert len(bd._window_bounds([d for d in _real_dates()
                                  if d.startswith("2026")])) == 1


def test_no_dates_no_windows():
    assert bd._window_bounds([]) == []


# ── the boundary comes from the UNFILTERED series ───────────────────────────

def test_bounds_are_computed_before_the_crossing_filter_is_applied():
    """THE SINGLE MOST IMPORTANT ASSERTION IN THIS FILE.

    Santa Teresa quotes on 12 of the current window's 32 days against
    Douglas's 29. Segmenting a crossing's OWN dates would let a crossing that
    skipped seven weeks split one window in two, and `basis_move` would then
    average a sub-window against a whole one -- a plausible number, shifted,
    with nothing raising. A window is a property of the BORDER.
    """
    src = ast.parse(__import__("inspect").getsource(bd.spread_by_window))
    calls = [n for n in ast.walk(src)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    bounds_calls = [c for c in calls if c.func.id == "spread_windows"]
    assert bounds_calls, "the bounds no longer come from spread_windows()"
    for c in bounds_calls:
        kw = {k.arg for k in c.keywords}
        assert "crossing" not in kw, (
            "spread_by_window passes `crossing` into the boundary "
            "computation; the bounds must come from the unfiltered series")


def test_the_window_source_is_the_priced_spread_not_the_crossings():
    """Crossings resumed for three days in July 2025 (07-07..07-10) with no
    index-rung price quoted at all, so a crossing-derived boundary makes a
    window holding zero priced days -- n=0, no mean, and a suppression rule
    that exists only because the boundary came from the wrong series.

    Worse, crossings run from 2023-05-05 while the index rung is quoted only
    from 2025-02-20, so crossing segmentation would propose an eighteen-month
    window with no basis figure in it. That would be the largest row in the
    table.
    """
    src = _code_of(bd.spread_windows)
    for forbidden in ("crossing_dates", "border_receipts", "border_reports",
                      "reopening"):
        assert forbidden not in src, (
            f"spread_windows() reads {forbidden}; the windows must be "
            f"segmented on the series being averaged")
    assert "index_spread" in src


# ── the thin-window guard ───────────────────────────────────────────────────

def test_a_thin_window_is_flagged_and_refused_rather_than_headlined():
    """A border that reopens, quotes three days and shuts is not hypothetical
    -- crossings did exactly that in July 2025. A 3-day mean set against a
    52-day one under a sentence saying the discount "has roughly halved" is a
    plausible claim about nothing."""
    assert bd.MIN_WINDOW_DAYS >= 5
    src = __import__("inspect").getsource(bd.basis_move)
    assert '["thin"]' in src or "'thin'" in src, (
        "basis_move does not refuse a thin window, so a roster decomposition "
        "can be computed across three observations")


def test_the_thin_flag_is_set_from_the_sample_not_the_span():
    src = __import__("inspect").getsource(bd.spread_by_window)
    assert '"thin": n < MIN_WINDOW_DAYS' in src, (
        "thin must count QUOTED DAYS. A window can span six weeks and carry "
        "four quotes, and it is the sample that makes a mean meaningless")


# ── the page reads one dict ─────────────────────────────────────────────────

def test_the_calendar_year_bucketing_is_gone_everywhere():
    assert not hasattr(bd, "spread_by_year")
    page = _page()
    for dead in ("spread_yr", "spread_by_year", "cur_yr_s", "prev_yr_s"):
        assert dead not in page, (
            f"{dead} survives on the page; two bucketings of one series is "
            f"how the tile and the table come to disagree")


def test_the_tile_and_the_table_read_the_same_dict():
    """Not merely unlikely to disagree -- unable to. Both index the one
    `spread_win` the loader stores."""
    page = _page()
    assert "spread_win = D.get(\"spread_win\")" in page
    assert "for d in reversed(" in page and "spread_win.values()" in page, (
        "the by-window table is not built from spread_win")


def test_the_tile_label_is_never_a_hardcoded_year():
    """The label is the whole point of the change: a screenshot of this tile
    outlives the week it describes."""
    page = _page()
    i = page.index("# ── Border prices")
    j = page.index("# ── Daily crossings")
    block = "\n".join(l for l in page[i:j].splitlines()
                      if not l.lstrip().startswith("#"))
    assert "Avg Basis" in block
    assert "this_yr} Avg Basis" not in block
    assert "{this_yr}" not in block.split("st.tabs")[0], (
        "the tile block still interpolates the calendar year")


def test_the_label_does_not_claim_a_shut_window_is_current():
    """'Since Aug 2026' asserts the window is still running. Once the border
    shuts again that is the one thing the label must not say."""
    page = _page()
    assert 'cur_w["open"]' in page or "cur_w['open']" in page, (
        "the label does not branch on whether the window is still open")


def test_the_crossing_count_stayed_on_the_tile():
    """This page's documented failure is a roster change reading as a market
    move, so the size of the roster behind the figure belongs beside it."""
    page = _page()
    i = page.index("# ── Border prices")
    j = page.index("# ── Daily crossings")
    assert "crossing{'s' if _nx != 1 else ''}" in page[i:j]


# ── the cache key ───────────────────────────────────────────────────────────

def test_the_loader_keys_on_border_schema_and_the_call_site_passes_it():
    """st.cache_data serves SHAPE, not freshness. The page now reads this
    module's window dicts BY KEY, so a reshaped return served from an older
    cache renders an em dash with nothing raising -- the leverage.SCHEMA trap.

    Both halves: no leading underscore (Streamlit excludes those from the key)
    AND the call site must pass it, because a default is not part of the key.
    """
    assert isinstance(bd.SCHEMA, int)
    page = _page()
    tree = ast.parse(page)
    loader = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "load_all"),
                  None)
    assert loader is not None
    args = [a.arg for a in loader.args.args]
    assert "schema" in args, "load_all does not take a schema key"
    assert not any(a.startswith("_") for a in args), (
        "an underscore-prefixed argument is excluded from the cache key")
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "load_all"]
    assert calls, "load_all is never called"
    for c in calls:
        passed = bool(c.args) or any(k.arg == "schema" for k in c.keywords)
        assert passed, (
            "load_all() is called without its schema; a parameter sitting at "
            "its default contributes nothing to the cache key")


# ── the computed verb ───────────────────────────────────────────────────────

def test_the_narrowing_verb_is_computed_from_the_two_figures():
    """'has roughly halved' is printed in the same breath as the two numbers
    it describes, so it has to be derived from them -- the southeast retention
    caption is this page's precedent for prose going stale against the chart
    directly above it."""
    page = _page()
    assert "def narrowing_phrase(" in page
    assert "narrowing_phrase(cur_w['mean'], prev_w['mean'])" in page
    ns = {}
    tree = ast.parse(page)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "narrowing_phrase")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<t>", "exec"), ns)
    f = ns["narrowing_phrase"]
    # Today's figures must still produce today's sentence.
    assert f(-23.8546, -42.2677) == "has roughly halved"
    # And the bands either side must not also say "halved".
    assert f(-40.0, -42.2677) != "has roughly halved"
    assert f(-5.0, -42.2677) != "has roughly halved"
    assert f(+3.0, -42.2677) == "has flipped to a premium"
    assert f(-23.85, 0) == "has moved"
