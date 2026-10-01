"""
The individual-cuts feed sets two traps, and both are silent.

LM_XB403's cut sections are strings: prices arrive as "1,361.58" and pounds
as "239,801", so a bare pd.to_numeric returns NaN for every one of them and
empties the table rather than raising.

And **0.00 means "did not trade"**, not "cost nothing". Over 259 reports that
is 978 zeros across 18 Choice cuts and 3,612 across 38 of the 42 Select cuts
— the normal state of the thinner cuts, not an edge case. Left as zeros they
are wrong three ways, none of which raise: a cut shown trading at $0.00, a
Choice−Select spread that is really the whole Choice price, and a chart axis
dragged to zero. The last is how it was found — a ribeye running $826–$1,417
was plotted from −85 to 1502, so a $130 move read as a flat line.
"""
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).parent))
from streamlit_source import load_from_app  # noqa: E402

APP = ROOT / "apps" / "beef_cutout" / "app.py"


def _cut_numbers():
    """
    Lift the helper out without importing the page.

    apps/beef_cutout/app.py is a Streamlit script: importing it runs the whole
    dashboard and hits the USDA API. Exec'ing the one function keeps this a
    unit test of the thing that actually goes wrong.
    """
    # ast, NOT a regex. A regex for `NAME = (...)` broke the moment a comment
    # inside the tuple contained a bracket -- eleven tests failing on the
    # extraction rather than on the thing under test. Parsing the module is
    # exact and cannot be fooled by prose, which this repo keeps proving.
    return load_from_app(APP, "_cut_numbers",
                         consts=("CUT_NUM_COLS", "CUT_PRICE_COLS"),
                         globals_={"pd": pd})


def _frame(**cols):
    return pd.DataFrame(cols)


def test_thousands_separators_survive():
    out = _cut_numbers()(_frame(weighted_average=["1,361.58", "855.15"],
                                total_pounds=["239,801", "8,783"]))
    assert out["weighted_average"].tolist() == [1361.58, 855.15]
    assert out["total_pounds"].tolist() == [239801.0, 8783.0]


def test_a_zero_price_becomes_missing_not_zero():
    """0.00 is USDA for "did not trade in this grade on this report"."""
    out = _cut_numbers()(_frame(weighted_average=["1,361.58", "0.00", "826.54"]))
    v = out["weighted_average"]
    assert v[0] == 1361.58
    assert pd.isna(v[1]), "a no-trade print is still being read as a price of zero"
    assert v[2] == 826.54


@pytest.mark.parametrize("col", ["weighted_average", "price_range_low",
                                 "price_range_high", "choice_600_900",
                                 "select_600_900"])
def test_every_price_column_is_cleaned(col):
    """
    Composite Primal Values does NOT share the cut sections' schema — it
    carries choice_600_900/select_600_900. Missing that pair left them as
    strings and the panel died on "str - str" the first time it rendered.
    """
    out = _cut_numbers()(_frame(**{col: ["0.00", "123.45"]}))
    assert pd.isna(out[col][0])
    assert out[col][1] == 123.45


@pytest.mark.parametrize("col", ["total_pounds", "number_trades"])
def test_counts_keep_their_zeros(col):
    """
    A zero COUNT is a fact — no pounds moved, no trades happened — and
    blanking it would hide exactly the thin-volume prints the table exists to
    flag. Only prices get the no-trade treatment.
    """
    out = _cut_numbers()(_frame(**{col: ["0", "4,635"]}))
    assert out[col][0] == 0
    assert out[col][1] == 4635.0


def test_a_missing_column_is_not_an_error():
    """The three sections have different schemas; each is passed through this."""
    out = _cut_numbers()(_frame(item_description=["Rib, ribeye, lip-on"]))
    assert list(out["item_description"]) == ["Rib, ribeye, lip-on"]


def test_unparseable_text_becomes_missing_rather_than_raising():
    out = _cut_numbers()(_frame(weighted_average=["", "n/a", "1,000.00"]))
    v = out["weighted_average"]
    assert pd.isna(v[0]) and pd.isna(v[1])
    assert v[2] == 1000.0
