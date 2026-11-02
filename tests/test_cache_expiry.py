"""
A cache that says it expires in an hour, and never expires at all.

THE BUG, IN ONE LINE: Streamlit ignores `ttl` when `persist` is set. Its own
`local_disk_cache_storage.py` warns "The cached function '%s' has a TTL that
will be ignored. Persistent cached functions currently don't support TTL."

So `@st.cache_data(ttl=3600, persist="disk")` is not an hourly cache. It is a
cache with NO time expiry, invalidated only by its key changing, by
`st.cache_data.clear()` behind a Refresh button, or by a restart. The page
renders perfectly throughout, with old numbers, which is why this has been
found four separate times in this repo and never by looking at the screen:

  * `fetch_leverage` froze the whole Packer Leverage tab until 2026-10-07.
  * `fetch_price_history` made the sidebar's "Cache: 1 hr" untrue; a weekly
    LM_CT150 release was picked up only by Refresh now or a restart.
  * `tests/test_market_board.py::test_no_loader_persists_to_disk` bans it for
    that one module's loaders -- this test is that idea, repo-wide.
  * 2026-11-02: eleven more, across six pages. Beef Cutout's whole page load
    was one of them, so an app up since morning served the previous day's
    cutout to anyone opening it after the 2:55 CT close -- on the STAFF
    deployment as much as the client one, which is where the daily letter is
    written.

WHAT THIS DOES NOT BAN. `persist="disk"` on its own is correct and wanted: it
survives sleep/wake so nobody pays a cold fetch, and it is safe exactly when
the cache key carries the freshness instead. That is the pattern cash_trade
and beef_cutout use -- key on USDA's published_date via publication_stamps(),
no ttl at all. Only the COMBINATION is a lie, so only the combination fails.

THE TWO WAYS OUT, when this test fails on something new:
  * The data has a cheap publication stamp -> key on it, drop the ttl, keep
    persist. Preferred when the probe is much cheaper than the fetch it
    guards (cash_trade: one 67KB probe for eight Detail calls).
  * It does not, or the probe is not cheaper -> drop persist so the ttl works.
    Preferred for monthly files (WASDE, ERS) where a stamp probe would cost
    as much as the fetch.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Every page, every shared module at the root, and the letter package.
SOURCES = sorted(
    set(ROOT.glob("apps/*/*.py")) | set(ROOT.glob("*.py")) | set(ROOT.glob("letter/*.py"))
)


def _is_cache_data(dec):
    """True for a `@st.cache_data(...)` decorator with arguments."""
    return (isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in {"cache_data", "cache_resource"})


def _offenders(tree):
    """(function, lineno) for every decorator setting ttl AND persist."""
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not _is_cache_data(dec):
                continue
            kw = {k.arg for k in dec.keywords if k.arg}
            if "ttl" in kw and "persist" in kw:
                bad.append((node.name, dec.lineno))
    return bad


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_cache_sets_both_ttl_and_persist(path):
    """
    Pinned on the DECORATOR, not on a grep for the two words: a comment
    explaining this trap contains both (beef_cutout's publication_stamps
    docstring quotes the old decorator verbatim), and a guard that fails on
    its own documentation is one somebody deletes.
    """
    bad = _offenders(ast.parse(path.read_text(encoding="utf-8-sig")))
    assert not bad, (
        f"{path.relative_to(ROOT)}: "
        + ", ".join(f"{name} at line {line}" for name, line in bad)
        + " sets ttl and persist together, so the ttl is ignored and the cache "
          "never expires. Read this file's docstring for the two ways out."
    )


def test_the_detector_catches_the_real_shape_and_spares_the_legitimate_ones():
    """
    The guard fed a known violation, and the three forms it must NOT reject.
    Every one of these is live in the repo today, so a detector that failed
    any of them would have to be deleted within the week.
    """
    bad = ast.parse(
        "@st.cache_data(ttl=7200, persist='disk', show_spinner=False)\n"
        "def fetch_thin_sections():\n    pass\n")
    assert _offenders(bad) == [("fetch_thin_sections", 1)], _offenders(bad)

    # persist alone -- correct, and what beef_cutout and cash_trade now use.
    ok_persist = ast.parse(
        "@st.cache_data(persist='disk', max_entries=8, show_spinner=False)\n"
        "def fetch_thin_sections(stamps):\n    pass\n")
    assert not _offenders(ok_persist), "rejects the stamp-keyed pattern"

    # ttl alone -- correct, and what the WASDE loaders now use.
    ok_ttl = ast.parse(
        "@st.cache_data(ttl=21600, show_spinner=False)\n"
        "def load_trade(schema):\n    pass\n")
    assert not _offenders(ok_ttl), "rejects a plain ttl"

    # a bare decorator with no call parens at all
    ok_bare = ast.parse("@st.cache_data\ndef f():\n    pass\n")
    assert not _offenders(ok_bare), "rejects an undecorated-call form"

    # the words in a COMMENT or docstring must not count
    ok_prose = ast.parse(
        "def publication_stamps():\n"
        "    '''This used to read ttl=7200, persist=\"disk\", which never expired.'''\n"
        "    return ''\n")
    assert not _offenders(ok_prose), "a guard that fails its own documentation"


def test_the_sweep_actually_covers_the_pages():
    """
    A parametrised test over an empty list passes silently. This is the half
    that would have hidden it.
    """
    assert len(SOURCES) > 30, f"only {len(SOURCES)} source files found"
    names = {p.name for p in SOURCES}
    assert "app.py" in names
    cached = [p for p in SOURCES
              if "@st.cache_data" in p.read_text(encoding="utf-8-sig")]
    assert len(cached) >= 10, f"only {len(cached)} files use st.cache_data"
