"""The nearby-delivery window must not be two literal months.

`_jsa_bids` filtered on a pair of anchored literal month patterns until
2026-10-07. Two defects in one predicate, and both failed silently:

  * The months were LITERALS, so from November it would have matched nothing and
    `delivered_corn` would have fallen through to the thinner AMS path while
    still labelling the figure "USDA AMS".
  * The match was ANCHORED, and DELIVERY_MONTH is free text as the elevator
    typed it. Measured over the ten days to 2026-10-07 the anchored filter
    returned 5,062 corn rows where the unanchored current-plus-next-month
    filter returns 7,337 across the same 25 states — a third of the nearby
    quotes dropped, and which third depended on how each elevator writes a
    date. The state count does not move, so nothing looked wrong.

    python -m pytest tests/test_corn_cost.py -q
"""

import ast
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "fed_cattle_crush")
sys.path.insert(0, _APP)

import corn_cost as cc  # noqa: E402

MODULE = os.path.join(_APP, "corn_cost.py")


def _code_of(fn_name: str) -> str:
    """The function's SOURCE WITH ITS DOCSTRING REMOVED.

    Searching the raw text is what the first version of this file did, and it
    failed immediately: `_jsa_bids`'s docstring QUOTES the old predicate in
    order to explain why it was wrong, so a search for the literal matched the
    explanation and reported the bug it had just fixed. The same mistake
    tests/test_rundown.py records making, and the reason tests/test_mx_prices.py
    uses AST for its own banned-import check.
    """
    tree = ast.parse(open(MODULE, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_the_window_is_this_month_and_next():
    assert cc._nearby_months(date(2026, 10, 7)) == ("oct", "nov")
    assert cc._nearby_months(date(2026, 9, 1)) == ("sep", "oct")


def test_it_rolls_over_the_year_end():
    """December must reach into January, not into month 13."""
    assert cc._nearby_months(date(2026, 12, 20)) == ("dec", "jan")
    assert cc._nearby_months(date(2027, 1, 5)) == ("jan", "feb")


def test_it_rolls_over_a_short_month():
    """Computed from the FIRST of the month, so the 31st does not skip one.
    today.replace(month=+1) would raise on 31 January."""
    assert cc._nearby_months(date(2026, 1, 31)) == ("jan", "feb")
    assert cc._nearby_months(date(2026, 3, 31)) == ("mar", "apr")
    assert cc._nearby_months(date(2026, 5, 31)) == ("may", "jun")


def test_every_month_of_the_year_resolves():
    """The literal pair was right for two months in twelve. Walk all twelve."""
    for m in range(1, 13):
        cur, nxt = cc._nearby_months(date(2026, m, 15))
        assert len(cur) == 3 and len(nxt) == 3
        assert cur.islower() and nxt.islower(), "ILIKE patterns are lowercased"
        assert cur != nxt


def test_sep_matches_every_spelling_the_feed_uses():
    """'sep' is a SUBSTRING of every September spelling observed in the live
    column — Sept, September, SEPT, F.H. SEPT 26 — which is the whole reason a
    three-letter lowercase fragment matched case-insensitively is enough."""
    frag = cc._nearby_months(date(2026, 9, 10))[0]
    for spelling in ("Sept 1-10", "SEP '26", "September 5-10, 2026",
                     "F.H. SEPT 26", "Thru Sept 18", "FH Sept"):
        assert frag in spelling.lower(), spelling


def test_oct_matches_the_spellings_the_anchored_filter_dropped():
    """These are real values read off the live column on 2026-10-07, every one
    of which the anchored pattern missed."""
    frag = cc._nearby_months(date(2026, 10, 7))[0]
    for spelling in ("By Oct 9th", "FH Oct 2026", "Delv by Oct 10th",
                     "LH October 2026", "DELIVERY BY OCT 9TH", "YC Oct '26"):
        assert frag in spelling.lower(), spelling


def test_the_months_are_not_hardcoded_in_the_query():
    """The literal pair is exactly what this fix removed. A future edit that
    reintroduces one would pass every test above."""
    body = _code_of("_jsa_bids")
    for literal in ("Sep%", "Oct%", "ILIKE 'Sep", "ILIKE 'Oct"):
        assert literal not in body, f"_jsa_bids hardcodes {literal} again"
    assert "_nearby_months()" in body, "_jsa_bids must derive its window"


def test_the_month_match_is_unanchored():
    """An anchored pattern silently drops 'By Oct 9th', 'FH Oct 2026' and
    'Delv by Oct 10th' — a third of the rows, with the right state count."""
    body = _code_of("_jsa_bids")
    # Quote-agnostic: ast.unparse normalises string quoting.
    assert "%{near[0]}%" in body and "%{near[1]}%" in body, \
        "both patterns must be wrapped in % on BOTH sides"


def test_the_patterns_are_bound_not_interpolated():
    """They come from strftime so they are three safe ASCII letters, but the
    binding costs nothing and stops the next person interpolating something
    that is not."""
    body = _code_of("_jsa_bids")
    assert "ILIKE %s OR r.DELIVERY_MONTH ILIKE %s" in body


def test_corn_cost_still_has_no_http_path():
    """This module is imported by two Streamlit pages and reads Snowflake only.
    It has never had an HTTP path and must not acquire one."""
    tree = ast.parse(open(MODULE, encoding="utf-8").read())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    for banned in ("requests", "urllib", "httpx"):
        assert banned not in imported, f"corn_cost imports {banned}"
