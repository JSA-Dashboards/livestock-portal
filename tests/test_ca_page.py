"""The Canadian Feeder Cattle page reads keys that actually exist.

A page reading `row.get("ytd_year_ago")` when the module produces `ytd_prior`
does not raise. `.get()` returns None, the conditional falls through, and the
tile renders a percentage with no levels under it — which is the standing rule
in CLAUDE.md broken silently, in Ross's words: "you have to do the math in
your head". That is exactly what shipped on the first build of this page and
it was found by loading it in a browser, not by 1,233 passing tests.

    python -m pytest tests/test_ca_page.py -q
"""

import ast
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "canadian_feeder_cattle")
sys.path.insert(0, _APP)

import ca_prices as cap  # noqa: E402

PAGE = os.path.join(_APP, "app.py")


def _slaughter_row(**kw):
    """One AMS 3213 slaughter result.

    Field names copied from tests/test_ca_prices.py rather than invented --
    the first version of this guessed them, parse_slaughter rejected the row,
    and the test failed on its own fixture instead of on the page.
    """
    row = {
        "report_date": "09/21/2026",
        "report_begin_date": "09/20/2026",
        "report_end_date": "09/26/2026",
        "published_date": "10/06/2026 07:06:18",
        "commodity": "Livestock Slaughter",
        "cat": "Federally Inspected Slaughter",
        "country_of_origin": "Canada",
        "class": "Cattle",
        "volume_unit": "Head",
        "current_volume": 63175,
        "week_ago_volume": 62405,
        "year_ago_volume": 53949,
        "current_YTD_volume": 2067700,
        "prior_YTD_volume": 2113947,
        "percent_change": -2.2,
    }
    row.update(kw)
    return row


def _page_src():
    return open(PAGE, encoding="utf-8").read()


# ── the key names the page reads must be real ───────────────────────────────

def test_every_slaughter_key_the_page_reads_is_one_the_module_produces():
    """The guard for the defect above. A `.get()` on a key that does not exist
    is silent, so the page is checked against the module's real output rather
    than against anyone's memory of it."""
    rows = cap.parse_slaughter([_slaughter_row()])
    produced = set(cap.slaughter_summary(rows, "Cattle"))
    assert produced, "the fixture must yield a summary for this to test anything"

    tree = ast.parse(_page_src())
    read = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ("_cattle", "_calves")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            read.add(node.args[0].value)

    assert read, "no slaughter keys found in the page — has it been rewritten?"
    unknown = read - produced
    assert not unknown, (
        f"the page reads {sorted(unknown)}, which slaughter_summary never "
        f"returns. It produces {sorted(produced)}."
    )


def test_the_ytd_tiles_quote_both_levels_not_just_the_percentage():
    """A percentage with no levels is the rule this repo has corrected on four
    other pages. Asserted on the SOURCE rather than the render, so it holds
    whether or not Snowflake is reachable."""
    src = _page_src()
    assert "ytd_prior" in src, "the year-ago level is not on the page at all"
    # Both tiles: cattle and calves.
    assert src.count("ytd_prior") >= 2, \
        "only one of the two YTD tiles shows the level it is measured against"


# ── the cache key, both halves ──────────────────────────────────────────────

def test_the_loader_keys_on_schema_and_the_caller_passes_it():
    """CLAUDE.md records this being inert in nineteen loaders: a leading
    underscore is excluded from the key, and a default the caller never
    overrides is not in the key either. Both halves or it does nothing."""
    src = _page_src()
    tree = ast.parse(src)

    cached = [n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and any("cache_data" in ast.dump(d) for d in n.decorator_list)]
    assert cached, "no cached loader on the page"

    for fn in cached:
        names = [a.arg for a in fn.args.args]
        schema_args = [a for a in names if "schema" in a.lower()]
        assert schema_args, f"{fn.name} takes no schema argument"
        for a in schema_args:
            assert not a.startswith("_"), (
                f"{fn.name}({a}=...) — a leading underscore excludes it from "
                f"the cache key, which is the whole point of passing it")

    # And the call site must actually supply it.
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in {f.name for f in cached}]
    assert calls, "the cached loader is never called"
    assert any(c.args or c.keywords for c in calls), (
        "the loader is called with no arguments, so its schema default is not "
        "part of the cache key and the guard is inert")


# ── things the page must keep saying ────────────────────────────────────────

def test_the_page_states_the_prices_are_already_us_dollars():
    """AMS converts 3213 before publishing. A reader who assumes Canadian
    dollars is out by roughly a third and nothing on the page looks wrong."""
    src = _page_src()
    assert "US dollars per" in src or "US$/cwt" in src
    # "no exchange rate" is split across two source lines by implicit
    # concatenation, so a contiguous match would never hit it.
    assert "exchange rate" in src.lower()


def test_the_page_never_applies_an_exchange_rate():
    """The Mexican page converts pesos; this one must not convert anything.
    Asserted by AST so the module's own prose explaining the rule cannot
    satisfy it — the trap tests/test_rundown.py records."""
    tree = ast.parse(_page_src())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    for banned in ("fx", "usd_per_cwt", "mxn_per_usd", "fx_on", "exchange_rate"):
        assert banned not in names, f"the page references {banned}"


def test_the_page_cannot_fetch():
    """It reads Snowflake only. marsapi rejects Community Cloud's IPs, so a
    page-side fetch would fail in production whatever we wanted — the rule
    border.py follows on the Mexican side."""
    tree = ast.parse(_page_src())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    for banned in ("requests", "urllib", "httpx"):
        assert banned not in imported, f"the page imports {banned}"


def test_staleness_is_measured_against_the_feeds_lag_not_its_cadence():
    """MAX_AGE_DAYS comes from the measured 9-17 day publication lag. A rule
    written from "it is weekly" marks this feed stale every week on current
    data — the defect CLAUDE.md records for the board's leverage tension."""
    assert cap.MAX_AGE_DAYS > 17, (
        f"MAX_AGE_DAYS is {cap.MAX_AGE_DAYS}; AMS 3213 publishes 9-17 days "
        f"after the week it covers, so anything at or below 17 fires on "
        f"perfectly current data")
