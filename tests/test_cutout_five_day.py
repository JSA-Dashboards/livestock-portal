"""
The cutout page's 5-Day Avg must be USDA's window, not the obvious one.

USDA publishes the figure itself — "Current 5 Day Simple Average" on the
morning report — so there is a right answer to check against rather than a
convention to argue about. It is the five sessions BEFORE the one being
reported. `tail(5)`, which includes the current session, is the natural thing
to write and is wrong by about three quarters of a dollar.

This is not a fresh concern. CLAUDE.md records the same window being fixed in
letter/sources.py on 2026-10-06, where the letter had been printing the
including-five and the client slide the excluding-five, and neither raised.
It also records two separate mornings lost to the letter and a dashboard
quoting one figure and disagreeing, each defensible. A third consumer of the
same number is exactly where that happens again, so the agreement between
this page and the letter is asserted here directly.

The fixture is the real feed: six consecutive LM_XB403 sessions ending
2026-10-06, and USDA's own published average for that report.
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = ROOT / "apps" / "beef_cutout" / "app.py"
LETTER_SOURCES = ROOT / "letter" / "sources.py"

# report_date, choice, select — straight from LM_XB403.
FEED = [
    ("2026-09-29", 382.66, 364.48),
    ("2026-09-30", 382.79, 360.59),
    ("2026-10-01", 376.79, 352.89),
    ("2026-10-02", 374.19, 354.49),
    ("2026-10-05", 378.26, 358.57),
    ("2026-10-06", 378.93, 356.34),
]

# What USDA printed on the 2026-10-06 morning report, verified against
# ams_2452.pdf: "Current 5 Day Simple Average: 378.94 / 358.20".
USDA_CHOICE_AVG5 = 378.94
USDA_SELECT_AVG5 = 358.20


def _five_day():
    """Lift five_day() out of the Streamlit script without importing it."""
    src = APP.read_text(encoding="utf-8")
    m = re.search(r"^def five_day\(df: pd\.DataFrame, col: str\):.*?(?=\n\S)",
                  src, re.S | re.M)
    assert m, "five_day() not found in app.py"
    ns = {"pd": pd}
    exec(m.group(0), ns)
    return ns["five_day"]


def _hist(n=None):
    rows = FEED if n is None else FEED[:n]
    return pd.DataFrame({
        "report_date": pd.to_datetime([r[0] for r in rows]),
        "choice": [r[1] for r in rows],
        "select": [r[2] for r in rows],
    })


def test_it_reproduces_the_average_usda_published():
    five_day = _five_day()
    assert round(five_day(_hist(), "choice"), 2) == USDA_CHOICE_AVG5
    assert round(five_day(_hist(), "select"), 2) == USDA_SELECT_AVG5


def test_the_including_window_does_not_reproduce_it():
    """
    The failure this exists to prevent, stated as arithmetic so nobody has to
    take it on trust: tail(5) is off by 0.75 on Choice and 1.62 on Select,
    and both are plausible numbers that render perfectly.
    """
    h = _hist()
    tail5_choice = round(float(h["choice"].tail(5).mean()), 2)
    tail5_select = round(float(h["select"].tail(5).mean()), 2)
    assert tail5_choice == 378.19 and tail5_choice != USDA_CHOICE_AVG5
    assert tail5_select == 356.58 and tail5_select != USDA_SELECT_AVG5


def test_the_page_and_the_letter_use_the_same_window():
    """
    Three things now print this number — this page, the daily letter and the
    client slide. CLAUDE.md: when the letter and a dashboard quote the same
    figure, a disagreement is a bug even when both numbers are defensible,
    and neither will raise.
    """
    # BY AST, WITH THE DOCSTRING DROPPED. A substring search over the source
    # matches the docstring that EXPLAINS the rule — five_day's own prose
    # names tail(5) as the thing not to do, so the first version of this test
    # failed on the sentence warning against it. Fourth time in this repo;
    # see tests/test_am_cutout.py and tests/test_rundown.py.
    import ast
    fn = next(n for n in ast.walk(ast.parse(APP.read_text(encoding="utf-8")))
              if isinstance(n, ast.FunctionDef) and n.name == "five_day")
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(n) for n in body)
    assert "iloc[-6:-1]" in code, code
    assert "tail(5)" not in code, code
    assert "iloc[-6:-1]" in LETTER_SOURCES.read_text(encoding="utf-8")


def test_too_short_a_history_returns_none_rather_than_a_partial_average():
    """
    Five rows cannot produce a five-session average that EXCLUDES the current
    one. Averaging whatever is there would render a number that is quietly
    not what the label says.
    """
    five_day = _five_day()
    assert five_day(_hist(5), "choice") is None
    assert five_day(_hist(6), "choice") is not None


def test_gaps_in_one_grade_do_not_shift_the_other():
    """Each grade drops its own NaNs, so a missing Select print cannot pull
    Choice's window back a session."""
    five_day = _five_day()
    h = _hist()
    h.loc[h["report_date"] == "2026-10-01", "select"] = None
    assert round(five_day(h, "choice"), 2) == USDA_CHOICE_AVG5
    assert five_day(h, "select") is None   # only five Select prints left
