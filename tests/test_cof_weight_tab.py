"""
The Placements by Weight tab on Cattle on Feed.

Added 2026-10-23 at Ross's request: the weight classes placed, the head in
each, and when those cattle come to market.

EVERY FIGURE ON IT ALREADY EXISTED. `cof_recap.build_recap` returns
`weight_classes` as (label, head, window) and `placed_total`, and until now
both went only into the PNG one-pager that gets emailed. The tab renders that
object. It must never recompute any of it: two surfaces deriving one figure
separately is the failure CLAUDE.md records five times over, and here the two
surfaces are a tab and the sheet a client is holding in their inbox.

The marketing window in particular is NOT USDA data — it is a fixed per-class
offset in `cof_recap.WEIGHT_CLASSES`, derived from one example sheet. A copy of
those offsets in the page would be a second source of truth for a number USDA
never published, which is the worst shape available.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "cattle_on_feed"))

import cof_recap  # noqa: E402

APP = ROOT / "apps/cattle_on_feed/app.py"
LABEL = "⚖️  Placements by Weight"


def _src() -> str:
    # BOM: this file starts with one, and ast.parse rejects it as an invalid
    # non-printable character, which reads as a syntax error in the page.
    return APP.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="module")
def tree():
    return ast.parse(_src())


def _tabs_call(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tabs"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "portal_view"
                and node.args and isinstance(node.args[0], ast.List)):
            labels = [e.value for e in node.args[0].elts if isinstance(e, ast.Constant)]
            if LABEL in labels:
                return node, labels
    raise AssertionError(f"no portal_view.tabs call carries {LABEL!r}")


def _body(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if (isinstance(item.context_expr, ast.Name)
                        and item.context_expr.id == "tab_weights"):
                    return node
    raise AssertionError("no `with tab_weights:` block")


# -- who sees it --------------------------------------------------------------

def test_both_views_get_it(tree):
    """
    Ross chose both. COF Recap directly above it is client-hidden -- the
    one-pager is his to author and send -- but which weights went on feed and
    when they market is a market reading, so it is NOT in the hide set. This
    pins that as a decision rather than something nobody revisited.
    """
    call, _ = _tabs_call(tree)
    hide = next((k.value for k in call.keywords if k.arg == "hide"), None)
    assert hide is not None, "the tab set should still hide the research tabs"
    hidden = {e.value for e in hide.elts if isinstance(e, ast.Constant)}
    assert LABEL not in hidden, "Placements by Weight is meant to reach clients"
    assert "📄  COF Recap" in hidden, "COF Recap is still staff-only"


# -- where it renders ---------------------------------------------------------

def test_it_renders_above_the_quickstats_guard(tree):
    """
    It reads USDA's released report text over plain HTTP and needs neither the
    QuickStats API nor a key. Below the `st.stop()` that guards that load it
    would vanish on exactly the days it still had something to say -- the same
    four-line reasoning COF Recap already depends on.
    """
    body = _body(tree)
    stops = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "stop" and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "st"]
    # the QuickStats guard is the last st.stop() on the page
    assert stops, "expected at least one st.stop()"
    assert body.end_lineno < max(stops), (
        f"the tab body ends at line {body.end_lineno}, below the st.stop() at "
        f"{max(stops)} -- a QuickStats outage would take it down"
    )


def test_the_body_is_behind_the_open_guard(tree):
    """A hidden Streamlit tab still executes. Without this the recap fetch runs
    on every Cattle on Feed load, including for readers who never open it."""
    body = _body(tree)
    guards = [n for n in body.body if isinstance(n, ast.If)]
    assert guards, "expected `if tab_weights.open:` as the body's first statement"
    test = guards[0].test
    assert (isinstance(test, ast.Attribute) and test.attr == "open"
            and isinstance(test.value, ast.Name)
            and test.value.id == "tab_weights")


# -- it must not recompute anything -------------------------------------------

def test_it_does_not_reimplement_the_marketing_window(tree):
    """
    The window is a fixed per-class offset USDA never published. A second copy
    of those offsets in the page is a second source of truth for a JSA
    convention -- and it would drift silently, because a wrong window renders
    as a perfectly plausible pair of month names.
    """
    body = _body(tree)
    src = ast.unparse(body)
    assert "WEIGHT_CLASSES" not in src, "the page must not hold its own class table"
    assert "marketing_window" not in src, (
        "the window arrives already built inside recap['weight_classes']; "
        "calling it again here is a second derivation"
    )
    # and no month-offset arithmetic smuggled in
    assert "% 12" not in src, "month wrap-around arithmetic belongs in cof_recap"


def test_it_reads_the_recap_rather_than_parsing_usda_itself(tree):
    body = _body(tree)
    src = ast.unparse(body)
    assert "_latest_recap()" in src, "it should use the page's one cached fetch"
    assert "weight_classes" in src
    for forbidden in ("fetch_report", "parse_weight_classes", "requests", "build_recap"):
        assert forbidden not in src, f"{forbidden} should not be called from the tab"


# -- the figures themselves ---------------------------------------------------

def test_the_classes_sum_to_the_published_total():
    """
    USDA publishes the six classes and the placement total independently, so
    they must agree -- the free audit the tab prints. Verified against the real
    October 2026 release: 1,777,000 both ways.

    This hits the network. Skipped rather than failed when USDA is unreachable:
    a red suite because nass.usda.gov is down teaches people to ignore it.
    """
    try:
        year, month, text = cof_recap.latest_report()
    except Exception as exc:                      # pragma: no cover - network
        pytest.skip(f"USDA unreachable: {exc}")
    if not text:                                  # pragma: no cover - network
        pytest.skip("USDA returned no report text")

    recap = cof_recap.build_recap(year, month, text)
    classes = recap["weight_classes"]
    assert len(classes) == 6, "USDA publishes six placement weight classes"

    total = sum(h for _l, h, _w in classes if h)
    assert total == recap["placed_total"], (
        f"the six classes sum to {total:,} against a published placement total "
        f"of {recap['placed_total']:,} -- one of them is being misread"
    )


def test_every_class_carries_a_window():
    """A class with head but no window would render a dash where the whole
    point of the tab is."""
    for label, pattern, lo, hi in cof_recap.WEIGHT_CLASSES:
        assert isinstance(lo, int) and isinstance(hi, int)
        assert 0 < lo <= hi <= 12, f"{label}: implausible offset {lo}/{hi}"
        win = cof_recap.marketing_window(9, lo, hi)
        assert "/" in win and len(win) > 3, f"{label}: bad window {win!r}"


def test_the_offsets_run_monotonically_heavier_markets_sooner():
    """
    A heavier calf is closer to finished, so it markets sooner. If an offset is
    ever edited the ordering is the cheapest thing that catches a typo -- the
    months themselves are a judgement nobody can check from here.
    """
    offsets = [lo for _label, _pat, lo, _hi in cof_recap.WEIGHT_CLASSES]
    assert offsets == sorted(offsets, reverse=True), (
        f"offsets should fall as weight rises, got {offsets}"
    )
