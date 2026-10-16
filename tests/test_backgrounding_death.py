"""
Death loss on the Backgrounding Crush -- the arithmetic, not the wording.

Added 2026-10-16 with the death loss field itself. Three things here can go
wrong without anything raising, because every intermediate value stays a
plausible dollar figure:

  * THE BREAK-EVEN CAN IGNORE THAT DEATH LOSS SCALES WITH THE BID. Cost of gain
    subtracts; death loss does not, because raising the bid raises the death
    line with it. A break-even that forgets the (1 + d) factor comes back about
    a point high, prints as a break-even, and loses the whole death loss line
    at that bid. Pinned by feeding the answer back through the crush.

  * THE MARGIN ON GAIN CAN STOP RECONCILING WITH THE PROFIT TILE. Before this
    change profit was identically (vog - cog) x gain/100, which is why the
    caption could report "$X a head" off the margin and agree with the Profit
    tile six inches above it. Put death loss into total cost alone and the two
    drift one death loss line apart, both honestly computed, neither raising --
    the letter-versus-dashboard failure this repo has paid for three times.

  * THE COST OF GAIN FIELD CAN GO ON TELLING PEOPLE TO INCLUDE DEATH LOSS,
    which charges it twice. That one is prose, so it is checked as prose -- but
    by lifting the help string out of the AST rather than grepping the file,
    because the module's own comments discuss the double count at length and a
    grep matches the explanation.

    python -m pytest tests/test_backgrounding_death.py -q
"""

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from streamlit_source import load_from_app  # noqa: E402

APP = os.path.join(_HERE, "..", "apps", "backgrounding_crush", "app.py")

_ns = load_from_app(APP, "death_cost_per_head", "calf_breakeven",
                    consts=("DEFAULTS",))
death_cost_per_head = _ns["death_cost_per_head"]
calf_breakeven = _ns["calf_breakeven"]
DEFAULTS = _ns["DEFAULTS"]


def crush(start_wt, sell_wt, bid, cog, death, sale_price):
    """The page's own build-up, in one place, so the identities can be asserted.

    This mirrors apps/backgrounding_crush/app.py rather than importing it --
    the page is a script and importing it runs the dashboard. The two helpers
    it actually turns on ARE imported, so the parts that can drift are the
    page's own code.
    """
    gain = sell_wt - start_wt
    gain_cwt = gain / 100.0
    revenue = sell_wt / 100.0 * sale_price
    cog_cost = gain_cwt * cog
    calf_cost = start_wt / 100.0 * bid
    death_cost = death_cost_per_head(calf_cost, death)
    total_cost = calf_cost + cog_cost + death_cost
    vog = (revenue - calf_cost) / gain_cwt
    death_c = death_cost / gain_cwt
    return {
        "revenue": revenue, "cog_cost": cog_cost, "calf_cost": calf_cost,
        "death_cost": death_cost, "total_cost": total_cost,
        "profit": revenue - total_cost, "vog": vog, "death_c": death_c,
        "cost_c": cog + death_c, "gain_cwt": gain_cwt,
    }


# A pen at the page's own defaults, priced off a feeder board near where it has
# been trading. Nothing here depends on the live curve.
CASE = dict(start_wt=525.0, sell_wt=800.0, cog=110.0, death=1.0, sale_price=330.0)


def test_death_loss_is_the_purchase_value_of_the_calves_that_die():
    """1% of a $2,165 calf is $21.65 -- no (1-d) grossing up, no sale value."""
    assert death_cost_per_head(2165.0, 1.0) == 21.65
    assert death_cost_per_head(2165.0, 0.0) == 0.0


def test_the_explainers_worked_example_is_what_the_code_does():
    """The page claims 1% -> 5% on a $2,165 calf swings cost $31.50/cwt over
    275 lb of gain. That sentence has been on the page since it was built; it
    is quoted here so the prose and the arithmetic cannot drift apart."""
    swing = (death_cost_per_head(2165.0, 5.0)
             - death_cost_per_head(2165.0, 1.0)) / 2.75
    assert round(swing, 2) == 31.49  # the page rounds it to "$31.50"
    assert abs(swing - 31.50) < 0.02


def test_break_even_bid_actually_breaks_even_with_death_loss_in_it():
    """THE ONE THAT CATCHES A DROPPED (1 + d). Feed the break-even back in."""
    gain_cwt = (CASE["sell_wt"] - CASE["start_wt"]) / 100.0
    revenue = CASE["sell_wt"] / 100.0 * CASE["sale_price"]
    be = calf_breakeven(revenue, gain_cwt * CASE["cog"],
                        CASE["start_wt"], CASE["death"])
    out = crush(bid=be, **CASE)
    assert abs(out["profit"]) < 1e-9

    # ...and the naive version, which subtracts cost of gain and forgets that
    # death loss rises with the bid, loses exactly the death loss line.
    naive = (revenue - gain_cwt * CASE["cog"]) / (CASE["start_wt"] / 100.0)
    assert naive > be
    bad = crush(bid=naive, **CASE)
    assert bad["profit"] < 0
    assert abs(bad["profit"] + bad["death_cost"]) < 1e-9


def test_break_even_at_zero_death_loss_is_the_old_formula():
    """Turning the field off must leave every answer where it was."""
    revenue = 800.0 / 100.0 * 330.0
    cog_cost = 2.75 * 110.0
    assert abs(calf_breakeven(revenue, cog_cost, 525.0, 0.0)
               - (revenue - cog_cost) / 5.25) < 1e-9


def test_profit_reconciles_with_the_margin_on_gain():
    """profit == (vog - cost_c) x gain/100, which is what lets the caption
    report a per-head figure that agrees with the Profit tile."""
    for death in (0.0, 1.0, 2.5, 7.0):
        for bid in (300.0, 420.0, 515.0):
            out = crush(bid=bid, **{**CASE, "death": death})
            implied = (out["vog"] - out["cost_c"]) * out["gain_cwt"]
            assert abs(implied - out["profit"]) < 1e-9

    # And the comparison has to be against cost_c, not bare cost of gain: on
    # this pen the two straddle the value of gain, so comparing to the wrong
    # one colours the tile green on a trade that loses money.
    edge = crush(bid=443.0, **CASE)
    assert edge["vog"] < edge["cost_c"]
    assert edge["vog"] > CASE["cog"]
    assert edge["profit"] < 0


def test_death_loss_only_ever_adds_cost():
    """Monotone in the percentage, and zero at zero -- a sign slip here reads
    as an unusually good pen rather than as an error."""
    base = crush(bid=450.0, **{**CASE, "death": 0.0})
    assert base["death_cost"] == 0.0
    last = base["profit"]
    for death in (0.5, 1.0, 3.0, 10.0):
        out = crush(bid=450.0, **{**CASE, "death": death})
        assert out["profit"] < last
        assert out["cost_c"] > out["cost_c"] - out["death_c"]
        last = out["profit"]


def test_the_field_ships_at_one_percent():
    assert DEFAULTS["death"] == 1.00


def _help_of(var: str) -> str:
    """The `help=` string on the number_input bound to `var`, off the AST.

    Grepping the file finds the module comments explaining the double count,
    which is the mistake tests/test_corn_cost.py records making against a
    docstring that quoted the predicate it had fixed.
    """
    tree = ast.parse(open(APP, encoding="utf-8").read())
    for node in ast.walk(tree):
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


def test_cost_of_gain_no_longer_tells_you_to_include_death_loss():
    """THE DOUBLE-COUNT GUARD. It said 'all-in: feed, yardage, health, death
    loss and interest' for as long as death loss had no line of its own. Left
    there, the page instructs the reader to charge it twice."""
    h = _help_of("cog").lower()
    assert "death loss" in h, "it has to mention death loss to exclude it"
    assert "leave death loss out" in h
    assert "all-in: feed" not in h


def test_death_loss_names_its_own_basis():
    h = _help_of("death").lower()
    assert "%" in h
    assert "what you paid" in h


def test_the_page_charges_death_loss_into_total_cost_and_into_the_comparison():
    """Structural, not prose: whichever way the lines are worded, `total_cost`
    has to name `death_cost` and `cost_c` has to name both halves. Those are
    the two places the figure reaches the reader."""
    tree = ast.parse(open(APP, encoding="utf-8").read())
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            seen.setdefault(node.targets[0].id, set()).update(
                n.id for n in ast.walk(node.value) if isinstance(n, ast.Name))
    assert "death_cost" in seen["total_cost"]
    assert {"cog", "death_c"} <= seen["cost_c"]
