"""
The cutout page's Day Change must equal USDA's own "Change From Prior Day".

LM_XB403 publishes the change itself, so there is a right answer to check
against rather than a convention to argue about. The page computed its own
and got a different number every day there had been a report yesterday:

    prior(timedelta(days=2)) takes the last row on or before today MINUS TWO
    DAYS. On 2026-10-01 that is <= 09/29, so 09/30 was skipped and a
    two-session move was labelled a day change.

        dashboard   Choice 376.79 - 382.66 (09/29) =  -5.87
                    Select 352.89 - 364.48 (09/29) = -11.59
        USDA        Choice 376.79 - 382.79 (09/30) =  -6.00
                    Select 352.89 - 360.59 (09/30) =  -7.70

Reported by Ross against ams_2453.pdf on 2026-10-01: the levels matched and
only the changes did not, which is the signature of this bug — the price
comes straight from the feed, and only the subtraction reached too far back.

The fixture is the real feed. Dates, levels and USDA's published changes are
all copied from LM_XB403, and they include a MONDAY (09/28, published +1.65
against Friday 09/25) so the weekend case is covered by data rather than by
an assumption about calendars.
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

# report_date, choice current, select current, USDA choice chg, USDA select chg
FEED = [
    ("2026-09-22", 378.89, 357.85, None,  None),   # no prior row in fixture
    ("2026-09-23", 377.31, 352.34, -1.58, -5.51),
    ("2026-09-24", 376.12, 352.10, -1.19, -0.24),
    ("2026-09-25", 378.83, 355.76, +2.71, +3.66),
    ("2026-09-28", 380.48, 358.23, +1.65, +2.47),  # Monday, prior is Friday
    ("2026-09-29", 382.66, 364.48, +2.18, +6.25),
    ("2026-09-30", 382.79, 360.59, +0.13, -3.89),
    ("2026-10-01", 376.79, 352.89, -6.00, -7.70),
]


def _changes():
    """Lift changes() out of the Streamlit script without importing it."""
    src = APP.read_text(encoding="utf-8")
    m = re.search(r"^def changes\(df: pd\.DataFrame, col: str\):.*?(?=\n\S)",
                  src, re.S | re.M)
    assert m, "changes() not found in app.py"
    ns = {"pd": pd, "timedelta": timedelta}
    exec(m.group(0), ns)
    return ns["changes"]


def _hist(upto):
    rows = FEED[: upto + 1]
    return pd.DataFrame({
        "report_date": pd.to_datetime([r[0] for r in rows]),
        "choice": [r[1] for r in rows],
        "select": [r[2] for r in rows],
    })


@pytest.mark.parametrize("i", range(1, len(FEED)))
@pytest.mark.parametrize("col,idx", [("choice", 3), ("select", 4)])
def test_day_change_matches_usdas_published_change(i, col, idx):
    expected = FEED[i][idx]
    _, day, _, _ = _changes()(_hist(i), col)
    assert day is not None
    assert round(day, 2) == pytest.approx(expected, abs=0.005), (
        f"{FEED[i][0]} {col}: got {day:+.2f}, USDA published {expected:+.2f}"
    )


def test_the_monday_change_reaches_back_to_friday():
    """
    The weekend case, called out because a calendar offset gets it wrong in
    the opposite direction from the weekday case and would look like a fix.
    """
    i = [r[0] for r in FEED].index("2026-09-28")
    _, day, _, _ = _changes()(_hist(i), "choice")
    assert round(day, 2) == 1.65        # 380.48 - 378.83, Friday 09/25


def test_a_single_report_has_no_day_change():
    _, day, _, _ = _changes()(_hist(0), "choice")
    assert day is None


def test_the_two_day_offset_is_gone():
    """
    Pins the REGRESSION. `prior(timedelta(days=2))` is the shape that was
    wrong, and it reads as deliberate — someone will reintroduce it reasoning
    about weekends unless the reason it fails is recorded next to it.
    """
    src = APP.read_text(encoding="utf-8")
    src = re.sub(r'"""(.*?)"""', "", src, flags=re.S)   # strip docstrings
    src = re.sub(r"#.*", "", src)                        # and comments
    assert "timedelta(days=2)" not in src
