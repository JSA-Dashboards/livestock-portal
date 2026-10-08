"""
The spread's month/year tiles show a LEVEL, and it must agree with the delta.

Those two tiles used to pass the change as both the value and the delta —
the same number printed twice, with the prior spread nowhere on the page. To
read "what was it a month ago" you subtracted 1.11 from 21.41 yourself.

They now print the prior level with the change as the delta, which means two
functions choose a row: changes() for the move and prior_level() for the
level. THE WHOLE RISK IS THAT THEY DRIFT. If they ever select different
reports the page prints a prior price and a change that do not subtract to
the current one — and nothing raises, because both numbers are individually
fine. So the identity is asserted here rather than left to the two
implementations staying in step.

The fixture is the real feed, and deliberately includes a gap: USDA does not
publish every day, so "a month ago" has to land on the nearest session at or
before the date rather than on the date.
"""
import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = ROOT / "apps" / "beef_cutout" / "app.py"


def _lift(name):
    """Pull one function out of the Streamlit script without importing it."""
    src = APP.read_text(encoding="utf-8")
    m = re.search(rf"^def {name}\(.*?(?=\n\S)", src, re.S | re.M)
    assert m, f"{name}() not found in app.py"
    ns = {"pd": pd, "timedelta": timedelta}
    exec(m.group(0), ns)
    return ns[name]


def _hist(days=400):
    """A daily spread series with weekends dropped, so dates are not uniform."""
    idx = pd.bdate_range(end="2026-10-07", periods=days)
    return pd.DataFrame({
        "report_date": idx,
        # something that actually moves, so a wrong row gives a wrong number
        "spread": [10 + (i % 37) * 0.5 for i in range(len(idx))],
    })


def test_prior_plus_delta_equals_current():
    """The identity the two tiles sit on, for both windows."""
    changes = _lift("changes")
    prior_level = _lift("prior_level")
    h = _hist()
    cur, _d1, d30, d365 = changes(h, "spread")
    p30, _ = prior_level(h, "spread", 30)
    p365, _ = prior_level(h, "spread", 365)
    assert round(p30 + d30, 6) == round(cur, 6)
    assert round(p365 + d365, 6) == round(cur, 6)


def test_it_lands_on_the_last_report_at_or_before_the_date():
    """
    Not on the date. The series here has no weekend rows, so a 30-day step
    from a Wednesday lands on a weekend about three times in ten.
    """
    prior_level = _lift("prior_level")
    h = _hist()
    cdt = h["report_date"].iloc[-1]
    val, dt = prior_level(h, "spread", 30)
    assert dt <= cdt - timedelta(days=30)
    # and it is the LAST such row, not merely one of them
    later = h[(h["report_date"] > dt) & (h["report_date"] <= cdt - timedelta(days=30))]
    assert later.empty
    assert val == h.loc[h["report_date"] == dt, "spread"].iloc[0]


def test_too_short_a_history_returns_none_rather_than_the_oldest_row():
    """
    With no report a year back, the honest answer is nothing. Falling back to
    the oldest row available would label a two-month-old spread "a year ago".
    """
    prior_level = _lift("prior_level")
    short = _hist(40)
    assert prior_level(short, "spread", 365) == (None, None)
    assert prior_level(short, "spread", 30)[0] is not None


def test_empty_input_is_handled():
    prior_level = _lift("prior_level")
    empty = pd.DataFrame({"report_date": pd.to_datetime([]), "spread": []})
    assert prior_level(empty, "spread", 30) == (None, None)


def test_nulls_are_skipped_so_a_blank_report_cannot_be_the_prior_level():
    """A report USDA published with no cutout is not a price."""
    prior_level = _lift("prior_level")
    h = _hist()
    cdt = h["report_date"].iloc[-1]
    target = prior_level(h, "spread", 30)[1]
    h.loc[h["report_date"] == target, "spread"] = None
    val, dt = prior_level(h, "spread", 30)
    assert dt < target and val is not None


def test_the_tiles_no_longer_print_the_change_as_their_own_value():
    """
    The defect Ross reported: tile(... fmt(spd30), delta_html(spd30) ...)
    used the whole tile to say one number twice and never showed a level.
    """
    src = APP.read_text(encoding="utf-8")
    assert "fmt(spd30), delta_html(spd30)" not in src
    assert "fmt(spd365), delta_html(spd365)" not in src
    assert "fmt(sp_p30), delta_html(spd30)" in src
    assert "fmt(sp_p365), delta_html(spd365)" in src
