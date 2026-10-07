"""
The morning cutout parser -- apps/beef_cutout/am_cutout.py.

Every assertion here is about a failure that RENDERS PERFECTLY. A sign read
the wrong way, a column that has shifted one place, the afternoon report
parsed as the morning one: none of them raise, none of them look wrong on a
tile, and the figure they produce is the one a reader would act on.

The fixture is the real 2026-10-06 report. USDA figures are public, so unlike
tests/test_sterling.py there is no reason to synthesise them -- and a fixture
with the real numbers in it is the only kind that can check the spread
identity against arithmetic a human can do in their head.
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "_test_am_cutout", REPO / "apps" / "beef_cutout" / "am_cutout.py")
am = importlib.util.module_from_spec(spec)
sys.modules["_test_am_cutout"] = am
spec.loader.exec_module(am)


# The real LM_XB402 of 2026-10-06, as pypdf extracts it.
AM_TEXT = """Agricultural Marketing Service
October 06, 2026
Livestock, Poultry, and Grain Market News
LM_XB402
National Daily Boxed Beef Cutout And Boxed Beef Cuts - Negotiated Sales -
Morning
Based on negotiated prices and volume of boxed beef cuts delivered within 0-21 days.
Choice
600-900
Select
600-900
Current Cutout Values:
382.46
360.62
Change from prior day:
4.20
2.05
Choice/Select spread:
21.84
Total Load Count (Cuts, Trimmings, Grinds):
49
Composite Primal Values
Primal Rib
679.31
562.84
Load Count And Cutout Value Summary For Prior 5 Days
Current 5 Day Simple Average:
378.94
358.20
USDA Estimated Boxed Beef Cut-out Values - as of 9:30am
"""

# The real LM_XB403 of the same day, which must never be accepted as a
# morning reading. Note Select fell, and USDA prints that as (2.23).
PM_TEXT = AM_TEXT.replace("LM_XB402", "LM_XB403").replace("Morning", "Afternoon")


def test_parses_the_real_morning_report():
    r = am.parse_am(AM_TEXT)
    assert "error" not in r, r
    assert r["report_date"] == date(2026, 10, 6)
    assert r["choice"] == 382.46
    assert r["select"] == 360.62
    assert r["change_choice"] == 4.20
    assert r["change_select"] == 2.05
    assert r["spread"] == 21.84
    assert r["loads"] == 49
    assert r["avg5_choice"] == 378.94
    assert r["avg5_select"] == 358.20


def test_the_spread_identity_holds_on_the_real_report():
    """Choice minus Select IS the printed spread -- the free audit."""
    r = am.parse_am(AM_TEXT)
    assert abs((r["choice"] - r["select"]) - r["spread"]) <= am.SPREAD_TOLERANCE


# -- Parentheses are a minus sign ---------------------------------------------

@pytest.mark.parametrize("tok,want", [
    ("(2.23)", -2.23),
    ("2.23", 2.23),
    ("(335.15)", -335.15),
    ("1,234.56", 1234.56),
    ("49", 49.0),
    ("-", None),
    ("", None),
])
def test_parentheses_are_negative(tok, want):
    assert am._num(tok) == want


def test_a_down_day_is_read_as_a_loss():
    """
    The whole point. USDA prints a fall as (2.23); read naively that is a
    two-dollar RALLY, and the tile is green on a day the cutout broke.
    """
    text = AM_TEXT.replace("4.20\n2.05", "(1.15)\n(2.23)")
    r = am.parse_am(text)
    assert r["change_choice"] == -1.15
    assert r["change_select"] == -2.23


# -- It must know which report it is reading ----------------------------------

def test_the_afternoon_report_is_refused():
    """
    The two PDFs sit one slug apart in the same directory with the same
    layout. Banking the close as a morning reading would turn every fade into
    a zero, and nothing would raise.
    """
    r = am.parse_am(PM_TEXT)
    assert "error" in r
    assert am.AM_REPORT in r["error"]


def test_the_right_slug_without_the_word_morning_is_refused():
    r = am.parse_am(AM_TEXT.replace("Morning", "Afternoon"))
    assert "error" in r
    assert "Morning" in r["error"]


# -- A shifted parse must not render ------------------------------------------

def test_a_shifted_parse_is_refused_by_the_spread_audit():
    """Choice reading one column early: plausible, wrong, and caught."""
    text = AM_TEXT.replace("Current Cutout Values:\n382.46\n360.62",
                           "Current Cutout Values:\n360.62\n382.46")
    r = am.parse_am(text)
    assert "error" in r
    assert "reconcile" in r["error"]


def test_a_cent_of_rounding_is_tolerated():
    """USDA rounds the three figures independently; a cent is not a shift."""
    text = AM_TEXT.replace("Choice/Select spread:\n21.84",
                           "Choice/Select spread:\n21.85")
    assert "error" not in am.parse_am(text)


# -- Missing values return None, never a padded list --------------------------

def test_a_short_row_returns_none_rather_than_padding():
    assert am._after("Label: 1.00", "Label:", 2) is None
    assert am._after("Label: 1.00 2.00", "Label:", 2) == [1.0, 2.0]


def test_the_scan_is_bounded_so_a_gap_cannot_borrow_the_next_section():
    """
    An unbounded scan past a missing figure silently takes the next section's
    number. Padding renders; borrowing renders too, and is worse.
    """
    text = "Change from prior day:" + (" " * (am._SCAN_CHARS + 20)) + "999.99 888.88"
    assert am._after(text, "Change from prior day:", 2) is None


def test_a_missing_optional_field_leaves_the_row_usable():
    """Load count is not worth refusing the whole morning read over."""
    text = AM_TEXT.replace("Total Load Count (Cuts, Trimmings, Grinds):\n49\n", "")
    r = am.parse_am(text)
    assert "error" not in r
    assert r["loads"] is None
    assert r["choice"] == 382.46


def test_no_cutout_values_is_an_error_not_a_blank_row():
    text = AM_TEXT.replace("Current Cutout Values:\n382.46\n360.62\n", "")
    assert "error" in am.parse_am(text)


# -- Which session the page opens on ------------------------------------------

TODAY = date(2026, 10, 6)
YESTERDAY = date(2026, 10, 5)


@pytest.mark.parametrize("am_date,pm_date,want", [
    # Before the morning release: the PDF still holds yesterday's report.
    (YESTERDAY, YESTERDAY, "PM"),
    # Morning is out, close is not: the AM is the newest thing published.
    (TODAY, YESTERDAY, "AM"),
    # Close is out. "The default in the afternoon should be the PM cutout."
    (TODAY, TODAY, "PM"),
    # The morning report could not be read at all.
    (None, TODAY, "PM"),
    (None, YESTERDAY, "PM"),
])
def test_default_session(am_date, pm_date, want):
    assert am.default_session(am_date, pm_date, TODAY) == want


def test_default_is_pm_when_usda_runs_late_on_the_morning_report():
    """
    DRIVEN BY WHAT IS PUBLISHED, NOT THE CLOCK. At 2pm with no morning report
    out, a clock rule would open on an AM that does not exist.
    """
    assert am.default_session(YESTERDAY, YESTERDAY, TODAY) == "PM"


# -- The fade -----------------------------------------------------------------

def test_fade_is_the_close_minus_the_morning():
    pd = pytest.importorskip("pandas")
    am_df = pd.DataFrame({
        "report_date": pd.to_datetime(["2026-10-05", "2026-10-06"]),
        "choice": [377.00, 382.46],
        "select": [357.00, 360.62],
    })
    pm_hist = pd.DataFrame({
        "report_date": pd.to_datetime(["2026-10-05", "2026-10-06"]),
        "choice": [378.26, 378.93],
        "select": [358.57, 356.34],
    })
    out = am.fade(am_df, pm_hist)
    assert len(out) == 2
    # The day the morning read faded by three and a half dollars.
    row = out[out["report_date"] == pd.Timestamp("2026-10-06")].iloc[0]
    assert round(row["choice_fade"], 2) == -3.53
    assert round(row["select_fade"], 2) == -4.28


def test_fade_drops_a_morning_with_no_close_yet():
    """An inner join: today's AM before the PM lands is not a fade."""
    pd = pytest.importorskip("pandas")
    am_df = pd.DataFrame({
        "report_date": pd.to_datetime(["2026-10-06"]),
        "choice": [382.46], "select": [360.62],
    })
    pm_hist = pd.DataFrame({
        "report_date": pd.to_datetime(["2026-10-05"]),
        "choice": [378.26], "select": [358.57],
    })
    assert am.fade(am_df, pm_hist).empty


def test_fade_tolerates_empty_input():
    pd = pytest.importorskip("pandas")
    assert am.fade(pd.DataFrame(), pd.DataFrame()).empty
    assert am.fade(None, None).empty


# -- Banking ------------------------------------------------------------------

def test_bank_does_nothing_with_an_error_row(monkeypatch):
    monkeypatch.setenv("USE_SNOWFLAKE", "1")
    assert am.bank({"error": "nope"}) == ""


def test_bank_does_nothing_without_a_report_date(monkeypatch):
    monkeypatch.setenv("USE_SNOWFLAKE", "1")
    assert am.bank({"choice": 1.0, "report_date": None}) == ""


def test_bank_is_quiet_when_snowflake_is_off(monkeypatch):
    monkeypatch.delenv("USE_SNOWFLAKE", raising=False)
    msg = am.bank({"report_date": date(2026, 10, 6), "choice": 382.46})
    assert "USE_SNOWFLAKE" in msg


def test_history_is_empty_rather_than_raising_when_snowflake_is_off(monkeypatch):
    monkeypatch.delenv("USE_SNOWFLAKE", raising=False)
    assert am.history().empty


def test_the_insert_has_one_placeholder_per_column():
    """
    Eleven columns, eleven placeholders. Off by one and the driver raises --
    but only on a machine with Snowflake reachable, which is not CI.
    """
    assert len(am._COLS) == len(am.FIELDS) == 8


def test_round_matches_the_column_precision():
    """A float that round-trips through NUMBER(9,2) must not read as a
    correction and insert a duplicate row every page load."""
    assert am._round(382.46000000001) == 382.46
    assert am._round(None) is None


# -- The things the docstring promises ----------------------------------------

def test_it_reads_the_ams_pdf_host_the_letter_already_uses():
    """
    Not marsapi, which rejects Streamlit Community Cloud's IPs. If this ever
    moves to a host the deployed app cannot reach, the page goes quiet.
    """
    assert am.AM_PDF.startswith("https://www.ams.usda.gov/mnreports/")
    src = (REPO / "letter" / "sources.py").read_text(encoding="utf-8")
    assert "www.ams.usda.gov/mnreports/" in src


def test_the_table_is_named_in_full_so_snowflake_schema_is_irrelevant():
    """
    CLAUDE.md: five bundled modules each default SNOWFLAKE_SCHEMA to the
    schema they own, so a module that relies on the session schema joins that
    collision. Every statement here names the table three-part.
    """
    src = (REPO / "apps" / "beef_cutout" / "am_cutout.py").read_text(encoding="utf-8")
    assert "SNOWFLAKE_SCHEMA" not in src
    assert am.TABLE.count(".") == 2


def test_it_never_imports_snowflake_db_by_bare_name():
    """
    snowflake_db.py exists five times and Python caches by NAME. draft_store
    loads it under a private name for this reason; so does this.

    BY AST, NOT BY GREP, and the first version of this test is why: it
    searched the source text and failed on the module's own docstring
    explaining the rule. tests/test_rundown.py records the identical mistake.
    """
    import ast
    src = (REPO / "apps" / "beef_cutout" / "am_cutout.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            assert all(a.name != "snowflake_db" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "snowflake_db"
    assert "_am_cutout_db" in src
