"""The Cattle on Feed sidebar's "Check for new data" button, and the line beside it.

These tabs and the COF Recap run on different clocks. The Recap reads USDA's
released report text the moment it posts; everything else reads the shared NASS
cache a scheduled job fills, so on release day the two disagree for a day or
more. On 2026-10-23 that looked exactly like a dashboard that had not noticed
the report, and nothing on the page said otherwise.

Two things here would be wrong silently:

  * **Clearing one cache and not the other.** `load_all` is cached and its body
    calls `fetch_series`, which is cached too. Clear only the outer one and it
    re-runs straight back into the inner cache and hands back the same frames —
    a button that spins, reruns, and changes nothing.
  * **Filling the slot before the data exists.** The freshness line needs `inv`,
    fetched ~190 lines below the sidebar. Script order, not layout order: the
    slot is booked by the button and filled after the load, and getting that
    backwards is a NameError on the live page that no source-text test sees.

    python -m pytest tests/test_cof_freshness.py -q
"""

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "apps" / "cattle_on_feed" / "app.py"
_SRC = _APP.read_text(encoding="utf-8-sig")   # this page carries a UTF-8 BOM
_TREE = ast.parse(_SRC)


def _button_block():
    """The `if <button>: ...` statement that clears the caches."""
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.If):
            continue
        # attr names, not source text: an ast.dump renders st.rerun() as
        # Attribute(value=Name(id='st'), attr='rerun'), so matching "st.rerun"
        # finds nothing and the helper reports the button as missing.
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "'clear'" in body and "'rerun'" in body:
            return node
    raise AssertionError("no cache-clearing button block found in the sidebar")


def test_the_button_clears_both_caches():
    """One without the other is a button that does nothing.

    load_all is cached AND calls fetch_series, which is cached. Clearing the
    outer alone re-runs it into the inner cache and returns identical frames.
    """
    cleared = {
        n.func.value.id
        for n in ast.walk(_button_block())
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "clear" and isinstance(n.func.value, ast.Name)
    }
    assert cleared == {"fetch_series", "load_all"}, (
        f"clears {sorted(cleared)}; both are cached and both must go")


def test_the_button_reruns():
    """Clearing without a rerun leaves the stale frames on screen until the
    next interaction, which reads as the button having failed."""
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "rerun"
        for n in ast.walk(_button_block()))


@pytest.mark.parametrize("name", ["fetch_series", "load_all"])
def test_both_names_are_actually_cached_functions(name):
    """.clear() exists only on an st.cache_data-wrapped function, so this test
    is what stops the one above passing against a plain function."""
    fn = next(n for n in _TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    assert any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and d.func.attr == "cache_data"
        for d in fn.decorator_list), f"{name} is not @st.cache_data"


def test_the_slot_is_booked_before_the_load_and_filled_after():
    """Script order, not layout order. Booked in the sidebar, filled once the
    frames exist — reversed, the live page raises and the source still reads
    perfectly well."""
    book = _SRC.index("_freshness_slot = st.sidebar.empty()")
    load = _SRC.index("= load_all(LOAD_YEARS, Q_YEARS)")
    fill = _SRC.index("_freshness_slot.markdown")
    assert book < load < fill


def test_the_line_names_on_feed_and_flows_separately():
    """They are a month apart by USDA's own design: the report carrying the
    Oct 1 inventory carries SEPTEMBER placements and marketings. One combined
    date would be wrong for one of them every single month."""
    start = _SRC.index("_freshness_slot.markdown")
    block = _SRC[_SRC.index("_inv_latest ="):start + 400]
    assert "on-feed to" in block
    assert "flows to" in block
    assert "place[" in block and "inv[" in block, (
        "both series must be read; one date cannot describe both")


def test_the_line_is_withheld_when_there_is_no_data():
    """An empty frame must print nothing rather than a formatted NaT."""
    block = _SRC[_SRC.index("_inv_latest ="):_SRC.index("_freshness_slot.markdown")]
    assert "if not inv.empty" in block
    assert "pd.notna(_inv_latest)" in block


def test_the_button_is_staff_only():
    """A client has no use for a cache control, and the trend slider beside it
    already draws that line."""
    block = ast.dump(_button_block())
    assert "portal_view" in block and "pick" in block
