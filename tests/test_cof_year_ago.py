"""The Data tab's "% of year ago" column, and the two ways it would go wrong
quietly.

USDA's Cattle on Feed report prints a percent-of-previous-year column beside
On Feed, Placed and Marketed, and the Data tab now reproduces it per month.
Both failures below render a perfectly plausible table:

  * **A second copy of the arithmetic.** The COF Recap tab on this same page
    already prints these three percentages, off USDA's released report text
    rather than QuickStats. Two tabs computing one number two ways is the
    letter-versus-dashboard failure CLAUDE.md records four times -- both
    defensible, neither raising. The reference figures here are USDA's own
    September 2026 release, so this pins the published number and not a
    fixture that could be edited into agreement.

  * **A 12-row shift instead of a (year - 1, month) match.** They agree on
    every row of every state today, so a "simplification" to `shift(12)` costs
    nothing visible -- until a month goes missing, when it prices a row
    against whatever happens to sit twelve places back. These state series do
    stop without warning: Minnesota's placements run to November 2024 and end.

A third thing pinned is the LABEL. 97.0 under "% of year ago" is three
percent below last year; the same figure under a signed header reads as a
near-doubling, and the Summary tiles on this page genuinely do show a percent
CHANGE. The two conventions live on one page, so the one that is not signed
has to say so.

    python -m pytest tests/test_cof_year_ago.py -q
"""

import ast
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

_HERE = Path(__file__).resolve().parent
_APP = _HERE.parent / "apps" / "cattle_on_feed" / "app.py"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_APP.parent))

import cof_recap  # noqa: E402
from streamlit_source import load_from_app  # noqa: E402

with_year_ago_pct = load_from_app(
    _APP, "with_year_ago_pct", globals_={"pd": pd, "cof_recap": cof_recap},
)

# The September 2026 release, US, 1,000+ head feedlots. On Feed is Sep 1;
# Placed and Marketed are the August flow the same report carries.
USDA_SEP_2026 = {
    "on_feed":  (11_163_000, 11_080_000, 100.7),
    "placed":   ( 1_617_000,  1_781_000,  90.8),
    "marketed": ( 1_519_000,  1_571_000,  96.7),
}


def _frame(rows):
    """[(year, month, value), ...] -> the frame series_for() returns."""
    return pd.DataFrame([
        {"year": y, "month": m,
         "date": pd.Timestamp(year=y, month=m, day=1), "Value": float(v)}
        for y, m, v in rows
    ])


def _tab_data_block():
    """The source of the module-level `with tab_data:` block, as an AST node."""
    tree = ast.parse(_APP.read_text(encoding="utf-8-sig"))
    blocks = [
        n for n in tree.body
        if isinstance(n, ast.With)
        and any(isinstance(i.context_expr, ast.Name) and i.context_expr.id == "tab_data"
                for i in n.items)
    ]
    assert len(blocks) == 1, f"expected one module-level `with tab_data:`, found {len(blocks)}"
    return blocks[0]


def _rendered_through_cols(block):
    """{frame name} for each st.dataframe(<name>[_cols]...) in the block.

    The first argument is `inv_y[_cols].sort_values(...)`, so the subscript is
    nested inside a call -- matching only a bare Subscript finds nothing and
    every assertion below it passes on an empty set.
    """
    names = set()
    for n in ast.walk(block):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "dataframe" and n.args):
            continue
        for sub in ast.walk(n.args[0]):
            if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Name) \
                    and sub.slice.id == "_cols" and isinstance(sub.value, ast.Name):
                names.add(sub.value.id)
    return names


# ── the figure itself ────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(USDA_SEP_2026))
def test_it_reproduces_usdas_own_percent_of_previous_year(key):
    curr, prior, published = USDA_SEP_2026[key]
    out = with_year_ago_pct(_frame([(2025, 9, prior), (2026, 9, curr)]))
    assert out["pct_year_ago"].iloc[-1] == published


@pytest.mark.parametrize("key", sorted(USDA_SEP_2026))
def test_the_data_tab_and_the_cof_recap_tab_cannot_drift(key):
    """Same input, same figure, because it is the same function."""
    curr, prior, _ = USDA_SEP_2026[key]
    out = with_year_ago_pct(_frame([(2025, 9, prior), (2026, 9, curr)]))
    assert out["pct_year_ago"].iloc[-1] == cof_recap.pct(curr, prior)


def test_the_helper_delegates_rather_than_re_deriving():
    """It must CALL cof_recap.pct, not carry its own round(x / y * 100, 1).

    A local copy is right the day it is written and drifts the day either
    side changes its rounding.
    """
    fn = next(n for n in ast.parse(_APP.read_text(encoding="utf-8-sig")).body
              if isinstance(n, ast.FunctionDef) and n.name == "with_year_ago_pct")
    calls = [n.func for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert any(isinstance(f, ast.Attribute) and f.attr == "pct"
               and isinstance(f.value, ast.Name) and f.value.id == "cof_recap"
               for f in calls), "with_year_ago_pct no longer calls cof_recap.pct"
    assert not any(isinstance(f, ast.Name) and f.id == "round" for f in calls), \
        "with_year_ago_pct is rounding on its own -- that is the second copy"


# ── the year-ago match ───────────────────────────────────────────────────────

def test_a_missing_month_is_not_bridged():
    """The row twelve places back is not the row a year back once a hole opens.

    2025 is missing May. Every 2026 month from February to May then sits one
    place too early for a shift, so the shift reaches a month too far back --
    and from June it silently comes right again, which is what makes the
    positional form so hard to spot: it is wrong for four rows out of twelve.
    """
    rows = [(2025, m, 100 + m) for m in range(1, 13) if m != 5]
    rows += [(2026, m, 200 + m) for m in range(1, 13)]
    out = with_year_ago_pct(_frame(rows)).set_index(["year", "month"])

    assert out.loc[(2026, 2), "pct_year_ago"] == cof_recap.pct(202, 102)   # vs Feb 2025
    assert pd.isna(out.loc[(2026, 5), "pct_year_ago"])                     # no May 2025
    assert out.loc[(2026, 6), "pct_year_ago"] == cof_recap.pct(206, 106)   # vs Jun 2025

    # ...and the positional answer really is different, so this is not a test
    # that would pass against the implementation it is meant to reject.
    shifted = _frame(rows).sort_values(["year", "month"]).reset_index(drop=True)
    shifted["shift12"] = shifted["Value"].shift(12)
    shifted = shifted.set_index(["year", "month"])
    assert shifted.loc[(2026, 2), "shift12"] == 101.0, "the shift reaches January"
    assert shifted.loc[(2026, 5), "shift12"] == 104.0, "the shift invents an April base"
    assert shifted.loc[(2026, 6), "shift12"] == 106.0, "and here it is right again"


def test_a_series_that_stops_leaves_blanks_rather_than_reaching_further_back():
    """Minnesota's shape: a full history, then nothing."""
    rows = [(y, m, 10 + m) for y in (2022, 2023) for m in range(1, 13)]
    rows += [(2024, m, 20 + m) for m in range(1, 12)]          # ends November
    out = with_year_ago_pct(_frame(rows)).set_index(["year", "month"])

    assert out.loc[(2024, 11), "pct_year_ago"] == cof_recap.pct(31, 21)
    assert pd.isna(out.loc[(2022, 1), "pct_year_ago"])         # earliest year: nothing to reach


def test_an_unmatched_column_is_still_numeric():
    """All-blank must stay float64 -- an object column cannot format as %.1f%%."""
    out = with_year_ago_pct(_frame([(2026, m, 100 + m) for m in range(1, 4)]))
    assert out["pct_year_ago"].dtype == "float64"
    assert out["pct_year_ago"].isna().all()


def test_the_oldest_displayed_year_reaches_into_the_longer_history():
    """st.column_config.NumberColumn prints a greyed "None" for a missing
    number -- there is no blank -- so a window whose first year cannot reach
    back renders twelve rows that read as a fault. The page holds the full
    record since 1996 for the seasonality charts; the tables borrow it.
    """
    window = _frame([(2025, m, 100 + m) for m in range(1, 13)])
    history = _frame([(y, m, 100 + m) for y in (2024, 2025) for m in range(1, 13)])

    assert with_year_ago_pct(window)["pct_year_ago"].isna().all()
    assert not with_year_ago_pct(window, history)["pct_year_ago"].isna().any()


def test_the_reach_back_adds_no_rows_to_what_is_shown():
    """It supplies the base, never the display window."""
    window = _frame([(2025, m, 100 + m) for m in range(1, 4)])
    history = _frame([(y, m, 100 + m) for y in (2024, 2025) for m in range(1, 13)])
    out = with_year_ago_pct(window, history)
    assert len(out) == len(window)
    assert list(out["date"]) == list(window["date"])


def test_the_tab_hands_each_table_its_own_full_history():
    """A table reaching into the WRONG series computes a plausible percentage
    off another quantity entirely -- placements over on-feed inventory is
    about 15%, and nothing would raise."""
    block = _tab_data_block()
    pairs = {}
    for n in ast.walk(block):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "with_year_ago_pct" and len(n.args) == 2):
            continue
        window = n.args[0].id
        inner = n.args[1]
        assert isinstance(inner, ast.Call) and inner.func.id == "series_for", \
            "the history argument should be this state's slice of the full frame"
        pairs[window] = inner.args[0].id

    assert pairs == {"inv_s": "inv_full", "place_s": "place_full",
                     "sales_s": "sales_full"}, pairs


def test_a_zero_year_ago_is_blank_not_infinite():
    out = with_year_ago_pct(_frame([(2025, 4, 0), (2026, 4, 900)]))
    assert pd.isna(out["pct_year_ago"].iloc[-1])


def test_the_input_frame_is_not_mutated():
    """The page passes the same series to the charts."""
    src = _frame([(2025, 4, 100), (2026, 4, 110)])
    with_year_ago_pct(src)
    assert "pct_year_ago" not in src.columns


# ── what the tab does with it ────────────────────────────────────────────────

def test_all_three_monthly_tables_carry_the_column():
    block = _tab_data_block()
    cols = [n for n in ast.walk(block)
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "_cols"]
    assert len(cols) == 1, "the shared column list moved or was duplicated"
    names = [e.value for e in cols[0].value.elts]
    assert "pct_year_ago" in names, f"_cols is {names}"

    shown = _rendered_through_cols(block)
    assert len(shown) == 3, (
        "expected the three monthly tables -- on-feed, placements, marketings -- "
        f"to render through _cols; found {sorted(shown)}")


def test_the_excel_download_shows_what_the_page_shows():
    """A workbook that disagrees with the page it came off is the same defect
    one step removed, and nobody opens it beside the tab."""
    block = _tab_data_block()
    rendered = _rendered_through_cols(block)
    assert rendered, "found no tables at all -- the rest of this would pass on an empty set"
    excel = next(n for n in ast.walk(block)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_to_excel")
    banked = {v.id for v in excel.args[0].values if isinstance(v, ast.Name)}
    assert rendered <= banked, (
        f"on the page but not in the workbook: {sorted(rendered - banked)}")

    augmented = {t.id for n in ast.walk(block)
                 if isinstance(n, ast.Assign)
                 for t in (n.targets[0].elts if isinstance(n.targets[0], ast.Tuple)
                           else [n.targets[0]])
                 if isinstance(t, ast.Name)
                 and "with_year_ago_pct" in ast.dump(n.value)}
    assert rendered <= augmented, (
        f"rendered without the year-ago column: {sorted(rendered - augmented)}")


def test_the_column_header_is_unsigned_and_says_what_it_means():
    """100.7 is "of", not "change". The Summary tiles on this page show a
    percent change, so the header is the only thing telling them apart."""
    block = _tab_data_block()
    ya = next(n for n in ast.walk(block)
              if isinstance(n, ast.Assign) and len(n.targets) == 1
              and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "_ya_col")
    call = ya.value
    label = call.args[0].value
    assert label == "% of year ago", f"header is {label!r}"
    fmt = next(k.value.value for k in call.keywords if k.arg == "format")
    assert "+" not in fmt, f"a signed format turns 100.7 into +100.7%: {fmt!r}"
    helptext = next(k.value for k in call.keywords if k.arg == "help")
    assert "100" in ast.literal_eval(helptext), "the help must say what 100 means"
