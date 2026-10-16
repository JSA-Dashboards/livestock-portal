"""
Death loss on the Backgrounding Crush -- a BREAKDOWN of cost of gain, not a
charge on top of it.

THE FIRST VERSION OF THIS FILE PINNED THE OPPOSITE and every test passed. It
shipped on 2026-10-16 with death loss added to total cost, and the arithmetic
was right in isolation -- the break-even solved correctly, the profit identity
held, the guards fired against a broken copy. It was still wrong, because the
$110 cost of gain default is Iowa State's ALL-IN figure and already carries
death loss, so the page charged it twice and moved every number on it. Pulled
the same day at Ross's call.

That is the thing worth recording: a test suite cannot tell you that a number
is being counted twice when both places that count it are individually
correct. It can only hold whichever answer you gave it. So what is pinned here
now is the NEGATIVE -- that `death` reaches no total -- because that is the
property the next person to touch this page is most likely to undo, and it is
the one nothing on screen would report.

  * DEATH LOSS REACHES NOTHING. Not total cost, not profit, not the
    value-of-gain comparison. Asserted structurally off the AST, so it holds
    whatever the lines are renamed to.

  * THE PROFIT IDENTITY SURVIVES. profit == (vog - cog) x gain/100, which is
    what lets the caption report a per-head figure that agrees with the Profit
    tile. Adding death loss to total cost alone breaks it; that is how the
    first version was found to need a matching change everywhere.

  * THE COST OF GAIN FIELD SAYS DEATH LOSS IS IN IT. That one is prose, so it
    is checked as prose -- but lifted off the AST rather than grepped, because
    the module's comments discuss the double count at length and a grep
    matches the explanation.

    python -m pytest tests/test_backgrounding_death.py -q
"""

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from streamlit_source import load_from_app  # noqa: E402

APP = os.path.join(_HERE, "..", "apps", "backgrounding_crush", "app.py")
SRC = open(APP, encoding="utf-8").read()
TREE = ast.parse(SRC)

# `load_from_app` hands back the function itself when exactly one name is
# asked for, so DEFAULTS comes off the tree this file already parsed.
death_cost_per_head = load_from_app(APP, "death_cost_per_head")
DEFAULTS = ast.literal_eval(
    next(n.value for n in ast.walk(TREE)
         if isinstance(n, ast.Assign) and len(n.targets) == 1
         and isinstance(n.targets[0], ast.Name)
         and n.targets[0].id == "DEFAULTS"))


def crush(start_wt, sell_wt, bid, cog, death, sale_price):
    """The page's build-up, in one place, so the identities can be asserted.

    Mirrors apps/backgrounding_crush/app.py rather than importing it -- the
    page is a script and importing it runs the dashboard. Note what is NOT
    here: `death` appears only in the breakdown block at the bottom and in no
    total above it. That shape is the thing under test, and the AST checks
    further down are what hold the real page to it.
    """
    gain = sell_wt - start_wt
    gain_cwt = gain / 100.0
    revenue = sell_wt / 100.0 * sale_price
    cog_cost = gain_cwt * cog
    calf_cost = start_wt / 100.0 * bid
    total_cost = calf_cost + cog_cost
    vog = (revenue - calf_cost) / gain_cwt

    death_cost = death_cost_per_head(calf_cost, death)
    death_c = death_cost / gain_cwt
    return {
        "revenue": revenue, "cog_cost": cog_cost, "calf_cost": calf_cost,
        "total_cost": total_cost, "profit": revenue - total_cost, "vog": vog,
        "gain_cwt": gain_cwt,
        "death_cost": death_cost, "death_c": death_c,
        "cog_other": cog - death_c,
        "death_share": death_c / cog * 100.0 if cog else 0.0,
    }


CASE = dict(start_wt=525.0, sell_wt=800.0, cog=110.0, death=1.0, sale_price=330.0)


# ── the breakdown is right ──────────────────────────────────────────────────

def test_death_loss_is_the_purchase_value_of_the_calves_that_die():
    """1% of a $2,165 calf is $21.65 -- no (1-d) grossing up, no sale value."""
    assert death_cost_per_head(2165.0, 1.0) == 21.65
    assert death_cost_per_head(2165.0, 0.0) == 0.0


def test_the_explainers_worked_example_is_what_the_code_does():
    """The page claims 1% -> 5% on a $2,165 calf is $31.50/cwt over 275 lb.
    That sentence has been on the page since it was built; it is quoted here
    so the prose and the arithmetic cannot drift apart."""
    swing = (death_cost_per_head(2165.0, 5.0)
             - death_cost_per_head(2165.0, 1.0)) / 2.75
    assert abs(swing - 31.50) < 0.02


def test_the_split_adds_back_up_to_the_cost_of_gain():
    """death loss + the remainder == the figure the user typed. If this ever
    fails the column is telling someone their feed bill is a number it is
    not."""
    for death in (0.0, 1.0, 2.5, 7.0):
        out = crush(bid=450.0, **{**CASE, "death": death})
        assert abs(out["death_c"] + out["cog_other"] - CASE["cog"]) < 1e-9
        assert abs(out["death_share"] / 100.0 * CASE["cog"]
                   - out["death_c"]) < 1e-9


def test_the_share_moves_with_the_calf_and_not_with_the_ration():
    """The reason the box exists. Same 1%, same ration, dearer calf -> bigger
    share of the cost of gain. Cheap calves at $180/cwt against today's $450."""
    cheap = crush(bid=180.0, **CASE)
    dear = crush(bid=450.0, **CASE)
    assert cheap["death_c"] < dear["death_c"]
    assert round(cheap["death_c"], 2) == 3.44      # the docstring's "about $3.50"
    assert round(dear["death_c"], 2) == 8.59       # "nearer $8.65" at $453
    assert dear["death_share"] > 2 * cheap["death_share"]


def test_a_cost_of_gain_too_low_to_contain_the_death_loss_is_detectable():
    """15% on a dear calf exceeds the whole $110. The page prints a warning
    there rather than a negative remainder under 'feed, yardage, health'."""
    out = crush(bid=450.0, **{**CASE, "death": 15.0})
    assert out["death_c"] > CASE["cog"]
    assert out["cog_other"] < 0


def test_both_places_that_quote_the_split_branch_on_the_same_test():
    """The column row and the caption must agree about whether the death loss
    fits inside the cost of gain. The caption shipped without the branch and
    printed 'death loss is inside that $110.00 -- $129.80/cwt of it ... 118%
    of your cost of gain', contradicting itself in one sentence. Found at 15%
    in a browser, not here: both halves were true statements about numbers
    that were individually right.

    Counting the comparisons is what pins it -- one in the column, one in the
    caption -- rather than matching either one's wording."""
    compares = [n for n in ast.walk(TREE)
                if isinstance(n, ast.Compare)
                and isinstance(n.left, ast.Name) and n.left.id == "death_c"
                and any(isinstance(c, ast.Name) and c.id == "cog"
                        for c in n.comparators)]
    assert len(compares) >= 2, (
        "every place that quotes the split needs the over-run branch; "
        f"found {len(compares)}")


# ── and it reaches nothing ──────────────────────────────────────────────────

def test_death_loss_changes_no_dollar_figure_on_the_page():
    """THE ONE THAT MATTERS. Profit, total cost and value of gain are
    identical at 0% and at 15%, because death loss is already inside the cost
    of gain and must not be charged again."""
    base = crush(bid=450.0, **{**CASE, "death": 0.0})
    for death in (1.0, 5.0, 15.0):
        out = crush(bid=450.0, **{**CASE, "death": death})
        for k in ("profit", "total_cost", "vog", "cog_cost", "calf_cost"):
            assert out[k] == base[k], k


def test_profit_reconciles_with_the_margin_on_gain():
    """profit == (vog - cog) x gain/100, which is what lets the caption report
    a per-head figure that agrees with the Profit tile six inches above it."""
    for death in (0.0, 1.0, 7.0):
        for bid in (300.0, 420.0, 515.0):
            out = crush(bid=bid, **{**CASE, "death": death})
            implied = (out["vog"] - CASE["cog"]) * out["gain_cwt"]
            assert abs(implied - out["profit"]) < 1e-9


def _assigned_names() -> dict:
    """{target: {names its value reads}} for every top-level-ish assignment."""
    seen: dict[str, set] = {}
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            seen.setdefault(node.targets[0].id, set()).update(
                n.id for n in ast.walk(node.value) if isinstance(n, ast.Name))
    return seen


def test_no_total_on_the_page_reads_the_death_loss():
    """Structural, so it survives any renaming of the display lines. These are
    every figure a reader takes as a cost or a result."""
    seen = _assigned_names()
    for target in ("total_cost", "profit", "breakeven", "calf_be", "vog",
                   "cog_cost", "calf_cost"):
        reads = seen[target]
        assert not ({"death", "death_c", "death_cost", "cog_other"} & reads), \
            f"{target} reads death loss: {reads}"


def test_the_breakdown_is_derived_from_the_cost_of_gain_the_user_typed():
    seen = _assigned_names()
    assert "death" in seen["death_cost"] or "death" in seen["death_c"]
    assert {"cog", "death_c"} <= seen["cog_other"]
    assert {"cog", "death_c"} <= seen["death_share"]


def test_there_is_no_death_loss_tile():
    """A ninth tile reading 'Death Loss $23.80' beside 'Cost of Gain' and
    'Total Cost' gets added on by a reader, whatever the label says -- it is
    already inside the cost of gain. The breakdown belongs in the input
    column, next to the two fields it comes from."""
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "tile" and node.args \
                and isinstance(node.args[0], ast.Constant):
            assert "death" not in str(node.args[0].value).lower()


def test_the_field_ships_at_one_percent():
    assert DEFAULTS["death"] == 1.00


# ── the note says so ────────────────────────────────────────────────────────

def _help_of(var: str) -> str:
    """The `help=` string on the number_input bound to `var`, off the AST.

    Grepping the file finds the module comments explaining the double count,
    which is the mistake tests/test_corn_cost.py records making against a
    docstring that quoted the predicate it had fixed.
    """
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "number_input"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == var):
            continue
        for kw in node.keywords:
            if kw.arg == "help":
                return ast.literal_eval(kw.value)
    raise AssertionError(f"no number_input({var!r}) with a help= string")


def test_cost_of_gain_says_death_loss_is_inside_it():
    """THE NOTE Ross asked for. Someone entering a feed-and-yardage-only
    figure here is light by the death loss and nothing on the page would say
    so, because the split would still compute and still look reasonable."""
    h = _help_of("cog").lower()
    assert "all-in" in h
    assert "death loss" in h
    assert "does not add" in h


def test_the_death_loss_field_says_it_adds_nothing():
    h = _help_of("death").lower()
    assert "does not add" in h
    assert "what you paid" in h
