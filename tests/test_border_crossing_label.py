"""The Border Prices tiles name the crossing from the data, never from source.

The headline tile read "Douglas" over `AVG(avg_price)` taken across whichever
crossings quoted that day. On 2026-10-20 that is $324.50 — the mean of Douglas
$324.00 and Santa Teresa $325.00 — so it was neither crossing's quote under one
crossing's name, and on the several 2026 days Santa Teresa quoted ALONE it was
simply the wrong port. The caption had it worse: "Mexican cattle at Douglas
averaged -42.27 in 2025" where Douglas alone averaged -45.74 and -42.27 is the
mean over four crossings.

Nothing raises on either. A plausible border price under a plausible port name
is plausible whichever port it came from — the same defect
`apps/canadian_feeder_cattle` was corrected for, and the reason
`mx_prices.compare()` returns its crossing rather than letting the page type
one.

    python -m pytest tests/test_border_crossing_label.py -q
"""

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "mexican_feeder_imports")
sys.path.insert(0, _APP)

import border as bd  # noqa: E402

PAGE = os.path.join(_APP, "app.py")


def _code_only(text):
    """The page with comment lines removed.

    Both of the assertions below first failed on this page's own comments
    EXPLAINING the rule they check — "it read Douglas over an average", "at
    Douglas averaged -42.27" — which is the trap tests/test_rundown.py records
    for its AST assertion. A guard that trips over the note describing the fix
    reads exactly like the defect being back.
    """
    return chr(10).join(l for l in text.splitlines()
                        if not l.lstrip().startswith("#"))


def _page():
    # utf-8-sig: two pages in this repo carry a BOM and ast.parse rejects it
    # as "invalid non-printable character U+FEFF", which reads as a syntax
    # error in the page rather than a codec choice in the reader.
    return open(PAGE, encoding="utf-8-sig").read()


# ── the label must come from the row ────────────────────────────────────────

def test_the_border_tile_does_not_hardcode_a_crossing():
    """A port name typed into the page is right only by luck and only on the
    days that port quoted alone."""
    src = _page()
    start = src.index("# ── Border prices")
    end = src.index("# ── Daily crossings")
    block = _code_only(src[start:end])
    for port in ('"Douglas', "'Douglas", '"Santa Teresa', "'Santa Teresa",
                 '"Nogales', '"Presidio'):
        assert port not in block, (
            f"the Border Prices block types {port!r}; the crossings must come "
            f"from index_spread's own row")


def test_index_spread_returns_the_crossings_it_averaged():
    """Five fields, and the fifth is what lets the page name them."""
    import inspect
    doc = inspect.getdoc(bd.index_spread) or ""
    assert "crossings" in doc
    src = inspect.getsource(bd.index_spread)
    assert "LISTAGG" in src, "the crossings are not carried off the query"
    assert "crossing=None" in src, "there is no way to fix the roster"


def test_spread_by_year_reports_its_roster():
    import inspect
    src = inspect.getsource(bd.spread_by_year)
    assert '"crossings"' in src, (
        "a year's mean with no record of which crossings made it cannot be "
        "compared with another year's")


# ── the roster check behind the "halved" claim ──────────────────────────────

def test_basis_move_separates_the_market_from_the_roster():
    """2025 carried four crossings on this rung and 2026 carries two, which is
    exactly the setup where a move is really a roster change. The claim is
    measured rather than asserted — and it survived: holding both years to the
    shared pair moves the narrowing by about a third of a point.
    """
    import inspect
    src = inspect.getsource(bd.basis_move)
    for key in ("reported", "same_crossing", "roster", "panel"):
        assert f'"{key}"' in src, f"basis_move does not return {key}"
    assert "set(a[\"crossings\"]) & set(b[\"crossings\"])" in src, (
        "the fixed panel is not the INTERSECTION of the two years' crossings, "
        "so a crossing present in only one of them can still move the answer")


def test_the_shared_panel_is_averaged_per_crossing_not_by_day_count():
    """Averaging the shared crossings' DAYS would weight a crossing by how
    often it quoted — Douglas 29 days against Santa Teresa 12 in 2026 — which
    is the roster effect wearing the fixed-panel label."""
    import inspect
    src = inspect.getsource(bd.basis_move)
    assert "for cx in panel" in src, (
        "the panel mean is not computed one crossing at a time")


# ── the caption must not attribute the average to one port ──────────────────

def test_the_caption_no_longer_credits_douglas_with_the_average():
    src = _page()
    start = src.index("# ── Border prices")
    end = src.index("# ── Daily crossings")
    block = _code_only(src[start:end])
    assert "at Douglas averaged" not in block
    assert "Averaged over" in block, (
        "the caption does not say the figure is an average across crossings")


def test_every_dollar_in_that_caption_is_escaped():
    """Streamlit renders a PAIR of unescaped dollar signs as inline LaTeX: the
    signs vanish and any bold between them is stranded as literal asterisks.
    This caption quotes two prices, so both need the escape — the trap this
    repo has shipped three times."""
    src = _page()
    start = src.index("The border discount has roughly halved")
    block = src[start:start + 900]
    bs = chr(92)
    # Every `${` that interpolates a price must carry the backslash escape.
    for frag in ("{prev_yr_s['mean']:,.2f}", "{cur_yr_s['mean']:,.2f}"):
        i = block.index(frag)
        assert block[i - 3:i] == bs + bs + "$", (
            f"{frag} is not preceded by an escaped dollar sign")


# ── a shape change must not silently break an unpacking ─────────────────────

SPREAD_FIELDS = 5          # date, border, index, spread, crossings


def _spread_unpackings(src):
    """[(lineno, n_names)] for every comprehension that iterates `spread`.

    Walks the AST rather than grepping, so a reformat does not hide one.
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.ListComp, ast.GeneratorExp,
                                 ast.SetComp, ast.DictComp)):
            continue
        for gen in node.generators:
            if not (isinstance(gen.iter, ast.Name) and gen.iter.id == "spread"):
                continue
            tgt = gen.target
            n = len(tgt.elts) if isinstance(tgt, ast.Tuple) else 1
            out.append((node.lineno, n))
    return out


def test_every_spread_unpacking_matches_the_row_width():
    """ADDING THE CROSSINGS FIELD BROKE THE 'vs CME index' CHART AND NOTHING
    CAUGHT IT. index_spread went from 4-tuples to 5, four comprehensions in
    the page still unpacked four, and the page died with
    `ValueError: too many values to unpack (expected 4)` — below the fold,
    so everything above it rendered perfectly.

    py_compile passed it. 1,494 tests passed it. Only loading the page found
    it, which is the lesson this repo keeps paying for.
    """
    found = _spread_unpackings(_page())
    assert found, "no comprehension iterates `spread` — has the page changed?"
    wrong = [(ln, n) for ln, n in found if n != SPREAD_FIELDS]
    assert not wrong, (
        f"index_spread yields {SPREAD_FIELDS}-tuples; these unpack a different "
        f"number: {wrong}. Bump SPREAD_FIELDS here when the row genuinely "
        f"changes, and fix every line it names.")


def test_index_spread_really_yields_that_many_fields():
    """The constant above is checked against the function, not trusted — a
    guard keyed on a number nobody re-derives drifts out of date silently."""
    import inspect
    src = inspect.getsource(bd.index_spread)
    ret = [n for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.ListComp)]
    assert ret, "index_spread no longer builds its rows in a comprehension"
    elts = ret[0].elt
    assert isinstance(elts, ast.Tuple), "a row is no longer a tuple"
    assert len(elts.elts) == SPREAD_FIELDS, (
        f"index_spread now yields {len(elts.elts)} fields, not "
        f"{SPREAD_FIELDS} — update SPREAD_FIELDS and every page unpacking")
