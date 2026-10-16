"""
Death loss on the Backgrounding Crush -- the slider, and the subtraction that
makes it safe.

FOUR VERSIONS SHIPPED ON 2026-10-16 AND THE SUITE WAS GREEN FOR EVERY ONE. A
test suite holds whichever answer it was given; it cannot tell you a figure is
counted twice when both places counting it are individually right. That is the
reason this file leans on the ONE invariant that survives every version:

    DEFAULTS["cog"] and whether death loss is charged are A PAIR.

ISU's $109-111/cwt is all-in and carries death loss inside it. Charge death
loss on top of $110 and it is counted twice -- which is version 1, and which
moved every figure on the page with nothing raising. The $101.35 default is
that figure less the death loss charge, so the page opens on $110 all-in.

The history, since each wrong version looked right:

  1. A cost line added to a $110 all-in cost of gain. Double counted.
  2. An input that only split the $110. Arithmetically harmless, and still
     wrong -- a control that changes no figure misleads about what it does.
  3. No input at all, a worked note at a fixed 1%. Correct, but it left the
     user adjusting the cost of gain by hand for a high-risk set.
  4. This one: a slider that charges, against a cost of gain that excludes.

What is pinned here:

  * The cost of gain default is the EX-DEATH-LOSS figure, and adding a
    representative death loss back lands inside ISU's published all-in range.
    This is the double-count guard and it is the only one that could have
    caught version 1.
  * The break-even solves for a bid that death loss scales with -- the (1 + d)
    factor. Dropping it returns a bid a point high that reads as a break-even.
  * profit == (vog - all-in cost) x gain/100, which is what lets the caption
    report a per-head figure that agrees with the Profit tile.

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


def _const(name):
    """A module-level constant's value, off the AST.

    Handles tuple assignment, because `DEATH_PCT_MIN, DEATH_PCT_MAX = 0, 10`
    is one Assign whose target is a Tuple -- a Name-only reader raises
    StopIteration on it, which reads as the constant having been deleted.
    """
    for n in ast.walk(TREE):
        if not isinstance(n, ast.Assign) or len(n.targets) != 1:
            continue
        tgt = n.targets[0]
        if isinstance(tgt, ast.Name) and tgt.id == name:
            return ast.literal_eval(n.value)
        if isinstance(tgt, ast.Tuple) and isinstance(n.value, ast.Tuple):
            for t, v in zip(tgt.elts, n.value.elts):
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(v)
    raise AssertionError(f"no module-level constant {name!r}")


_ns = load_from_app(APP, "death_cost_per_head", "calf_breakeven")
death_cost_per_head = _ns["death_cost_per_head"]
calf_breakeven = _ns["calf_breakeven"]
DEFAULTS = _const("DEFAULTS")
DEATH_PCT_MIN, DEATH_PCT_MAX = _const("DEATH_PCT_MIN"), _const("DEATH_PCT_MAX")

# Iowa State's Livestock Enterprise Budgets for Iowa-2026 (FM 1815 / B1-21),
# backgrounding, ALL-IN -- the range the module comment cites.
ISU_ALL_IN = (109.0, 111.0)

# What the page opens on, Ross's call 2026-10-16: the midpoint, which is the
# figure ISU's backgrounding budgets are usually quoted at.
ISU_ALL_IN_TARGET = 110.0


def crush(start_wt, sell_wt, bid, cog, death, sale_price):
    """The page's build-up, in one place, so the identities can be asserted.

    Mirrors apps/backgrounding_crush/app.py rather than importing it -- the
    page is a script and importing it runs the dashboard. The two helpers that
    carry the real arithmetic ARE imported, so what can drift is the page's.
    """
    gain = sell_wt - start_wt
    gain_cwt = gain / 100.0
    revenue = sell_wt / 100.0 * sale_price
    cog_cost = gain_cwt * cog
    calf_cost = start_wt / 100.0 * bid
    death_cost = death_cost_per_head(calf_cost, death)
    total_cost = calf_cost + cog_cost + death_cost
    death_c = death_cost / gain_cwt
    cost_c = cog + death_c
    return {
        "revenue": revenue, "cog_cost": cog_cost, "calf_cost": calf_cost,
        "death_cost": death_cost, "total_cost": total_cost,
        "profit": revenue - total_cost, "gain_cwt": gain_cwt,
        "vog": (revenue - calf_cost) / gain_cwt,
        "death_c": death_c, "cost_c": cost_c,
        "death_share": death_c / cost_c * 100.0 if cost_c else 0.0,
    }


CASE = dict(start_wt=525.0, sell_wt=800.0, cog=DEFAULTS["cog"],
            death=DEFAULTS["death"], sale_price=330.0)

# The calf the $101.35 was subtracted at -- today's cash seed.
TODAYS_BID = 453.28


# ── the pairing: the guard that could have caught version 1 ─────────────────

def test_the_page_opens_on_110_all_in():
    """THE DOUBLE-COUNT GUARD, and the only test here that version 1 fails.

    Ross's call, 2026-10-16: the page opens on ISU's $110/cwt ALL-IN. Since
    the slider charges death loss separately, the cost of gain box has to hold
    $110 LESS that charge -- $101.35 at a $453 calf. A box holding $110 passes
    every other test in this file and is the double count.

    Pinned at TODAYS_BID because the subtraction is calf-price dependent; see
    the drift test below for why that is correct rather than a defect.
    """
    out = crush(bid=TODAYS_BID, **CASE)
    assert abs(out["cost_c"] - ISU_ALL_IN_TARGET) < 0.01, (
        f"page opens on {out['cost_c']:.2f}/cwt all-in, not "
        f"{ISU_ALL_IN_TARGET:.2f}; DEFAULTS['cog'] and the death loss charge "
        f"have come apart")

    # ...and stated the other way round, so a reader sees why 101.35, not 110.
    assert DEFAULTS["cog"] < ISU_ALL_IN[0], "the default must EXCLUDE death loss"
    assert abs(DEFAULTS["cog"] + out["death_c"] - out["cost_c"]) < 1e-9


def test_the_all_in_default_drifts_up_with_the_calf_and_that_is_right():
    """Dearer calves genuinely cost more to lose, so the opening all-in figure
    rises with them. Pinning it at $110 forever would mean quietly shrinking
    the feed-and-yardage figure every time calves rallied, which is false.

    The band is ISU's own published range, so the drift is bounded by
    something real rather than by a number picked here.
    """
    dear = crush(bid=500.0, **CASE)["cost_c"]
    assert dear > ISU_ALL_IN_TARGET
    assert dear <= ISU_ALL_IN[1], "a $500 calf should still sit inside ISU's range"
    assert crush(bid=400.0, **CASE)["cost_c"] < ISU_ALL_IN_TARGET


def test_charging_on_an_all_in_cost_of_gain_overshoots_isu():
    """Version 1, stated as arithmetic so nobody has to take it on trust: the
    same slider against a $110 box lands above ISU's all-in range."""
    bad = crush(bid=TODAYS_BID, **{**CASE, "cog": 110.0})
    assert bad["cost_c"] > ISU_ALL_IN[1]
    assert bad["cost_c"] - crush(bid=TODAYS_BID, **CASE)["cost_c"] > 8.0


# ── the charge is right ─────────────────────────────────────────────────────

def test_death_loss_is_the_purchase_value_of_the_calves_that_die():
    """1% of a $2,165 calf is $21.65 -- no (1-d) grossing up, no sale value."""
    assert death_cost_per_head(2165.0, 1) == 21.65
    assert death_cost_per_head(2165.0, 0) == 0.0


def test_the_explainers_worked_example_is_what_the_code_does():
    """The page claims 1% -> 5% on a $2,165 calf is $31.50/cwt over 275 lb.
    Quoted here so the prose and the arithmetic cannot drift apart."""
    swing = (death_cost_per_head(2165.0, 5)
             - death_cost_per_head(2165.0, 1)) / 2.75
    assert abs(swing - 31.50) < 0.02


def test_the_slider_moves_the_answer():
    """The whole point of the change: raising death loss raises the all-in
    cost and lowers profit, with no hand-editing of the cost of gain."""
    last_profit, last_cost = None, None
    for death in range(DEATH_PCT_MIN, DEATH_PCT_MAX + 1):
        out = crush(bid=TODAYS_BID, **{**CASE, "death": death})
        if last_profit is not None:
            assert out["profit"] < last_profit
            assert out["cost_c"] > last_cost
        last_profit, last_cost = out["profit"], out["cost_c"]

    off = crush(bid=TODAYS_BID, **{**CASE, "death": 0})
    assert off["death_cost"] == 0.0
    assert off["cost_c"] == CASE["cog"]


def test_the_share_moves_with_the_calf_and_not_with_the_ration():
    """Why it is a slider and not a line in the cost of gain: same 1%, same
    ration, dearer calf -> a bigger charge."""
    cheap = crush(bid=180.0, **CASE)
    dear = crush(bid=TODAYS_BID, **CASE)
    assert round(cheap["death_c"], 2) == 3.44   # the docstring's "$3.44"
    assert round(dear["death_c"], 2) == 8.65    # and its "$8.65"
    assert dear["death_share"] > 2 * cheap["death_share"]


# ── the break-even, which death loss scales with ────────────────────────────

def test_break_even_bid_actually_breaks_even():
    """THE ONE THAT CATCHES A DROPPED (1 + d). Feed the answer back in."""
    gain_cwt = (CASE["sell_wt"] - CASE["start_wt"]) / 100.0
    revenue = CASE["sell_wt"] / 100.0 * CASE["sale_price"]
    be = calf_breakeven(revenue, gain_cwt * CASE["cog"],
                        CASE["start_wt"], CASE["death"])
    assert abs(crush(bid=be, **CASE)["profit"]) < 1e-9

    # The naive version -- subtract cost of gain, forget that death loss rises
    # with the bid -- loses exactly the death loss line at its own answer.
    naive = (revenue - gain_cwt * CASE["cog"]) / (CASE["start_wt"] / 100.0)
    assert naive > be
    bad = crush(bid=naive, **CASE)
    assert abs(bad["profit"] + bad["death_cost"]) < 1e-9


def test_break_even_at_zero_death_loss_is_the_plain_formula():
    revenue = 800.0 / 100.0 * 330.0
    cog_cost = 2.75 * DEFAULTS["cog"]
    assert abs(calf_breakeven(revenue, cog_cost, 525.0, 0)
               - (revenue - cog_cost) / 5.25) < 1e-9


def test_break_even_falls_as_death_loss_rises():
    """What a user watches when they drag the slider."""
    revenue, cog_cost = 8.0 * 330.0, 2.75 * DEFAULTS["cog"]
    bes = [calf_breakeven(revenue, cog_cost, 525.0, d)
           for d in range(DEATH_PCT_MIN, DEATH_PCT_MAX + 1)]
    assert bes == sorted(bes, reverse=True)
    assert bes[0] - bes[-1] > 30.0     # 0% to 10% is worth real money


# ── and everything still reconciles ─────────────────────────────────────────

def test_profit_reconciles_with_the_margin_on_gain():
    """profit == (vog - cost_c) x gain/100 -- what lets the caption report a
    per-head figure that agrees with the Profit tile six inches above it."""
    for death in range(DEATH_PCT_MIN, DEATH_PCT_MAX + 1):
        for bid in (300.0, 420.0, 515.0):
            out = crush(bid=bid, **{**CASE, "death": death})
            implied = (out["vog"] - out["cost_c"]) * out["gain_cwt"]
            assert abs(implied - out["profit"]) < 1e-9


def test_the_three_cost_tiles_sum_to_total_cost():
    """Calf Cost + Cost of Gain + Death Loss is exactly Total Cost, which is
    what makes a Death Loss tile correct here when it was not before."""
    out = crush(bid=TODAYS_BID, **CASE)
    assert abs(out["calf_cost"] + out["cog_cost"] + out["death_cost"]
               - out["total_cost"]) < 1e-9


def _assigned_names() -> dict:
    seen: dict[str, set] = {}
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            seen.setdefault(node.targets[0].id, set()).update(
                n.id for n in ast.walk(node.value) if isinstance(n, ast.Name))
    return seen


def test_the_page_charges_death_loss_everywhere_it_has_to():
    """Structural, so it survives renaming the display lines. These are the
    places the charge has to reach; the value-of-gain comparison is the one
    that silently breaks the caption/tile agreement if it is missed."""
    seen = _assigned_names()
    assert "death_cost" in seen["total_cost"]
    assert {"cog", "death_c"} <= seen["cost_c"]
    assert "death" in seen["calf_be"]
    assert "death_cost" in seen["death_c"]


def test_the_slider_exists_and_is_whole_points():
    """Ross asked for 1%, 2%, 3% -- a slider, not a box."""
    sliders = [n for n in ast.walk(TREE)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "slider" and n.args
               and isinstance(n.args[0], ast.Constant)
               and n.args[0].value == "death"]
    assert len(sliders) == 1, "exactly one death loss slider"
    step = sliders[0].args[4]
    assert isinstance(step, ast.Constant) and step.value == 1
    assert DEATH_PCT_MIN == 0 and DEATH_PCT_MAX >= 5
    assert DEFAULTS["death"] == 1


def test_the_result_renders_next_to_the_slider():
    """Ross asked for the figure beside the control. It cannot be written in
    place -- it needs the bid, a widget in the other column -- so the page
    books the position with st.empty() and fills it later. If that slot goes
    away the figure silently relocates four rows down, under the cash calf
    price, which is where it was before and is not what was asked for."""
    assert "death_slot = st.empty()" in SRC
    assert "death_slot.markdown(" in SRC
    assert SRC.index("death_slot = st.empty()") < SRC.index("death_slot.markdown(")


def _text_of(node) -> str:
    """The literal text of a string node, f-strings included.

    The help strings interpolate constants, so they parse as JoinedStr and
    `ast.literal_eval` refuses them outright -- which reads as the help having
    gone missing rather than as the reader not handling an f-string.
    """
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ast.literal_eval(node)


def _help_of(var: str) -> str:
    """The `help=` string on the widget bound to `var`, off the AST.

    Grepping the file finds the module comments explaining the double count,
    which is the mistake tests/test_corn_cost.py records making against a
    docstring that quoted the predicate it had fixed.
    """
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute)
                and fn.attr in ("number_input", "slider")):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == var):
            continue
        for kw in node.keywords:
            if kw.arg == "help":
                return _text_of(kw.value)
    raise AssertionError(f"no widget {var!r} with a help= string")


def test_cost_of_gain_says_it_excludes_death_loss():
    """The sentence that stops someone typing an all-in figure into a box the
    slider then charges death loss on top of. That mistake double counts and
    nothing else on the page would report it."""
    h = _help_of("cog").lower()
    assert "not death loss" in h
    assert "all-in" in h          # names ISU's figure as the thing it is not


def test_the_slider_says_it_charges():
    h = _help_of("death").lower()
    assert "what you paid" in h
    assert "raising it" in h and "all-in" in h
