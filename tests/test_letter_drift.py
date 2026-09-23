"""
Guard the constants letter/sources.py had to copy out of the dashboards.

The dashboards are Streamlit scripts and cannot be imported without executing a
page, so the USDA report IDs and endpoints are duplicated in letter/sources.py.
Duplication is the accepted cost; SILENT duplication is not. These tests read the
app files as text and assert every copied value still matches, so a dashboard
changing a report ID fails here instead of quietly sending last month's numbers
to clients.

CLAUDE.md records the same hazard for snowflake_db.py, and the same answer:
compare every copy, not just one pair.

    python -m pytest tests/test_letter_drift.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APPS = REPO / "apps"

from letter import sources  # noqa: E402


def _const(path: Path, name: str) -> str:
    """Read `NAME = value` out of a source file without importing it."""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^{name}\s*=\s*(.+?)\s*(?:#.*)?$", text, re.MULTILINE)
    assert m, f"{name} not found in {path.name}"
    return m.group(1).strip().strip('"').strip("'")


@pytest.mark.parametrize("app, name, mirrored", [
    ("cash_trade", "CT150_ID", sources.CT150_ID),
    ("cash_trade", "CT154_ID", sources.CT154_ID),
    ("beef_cutout", "REPORT_ID", sources.XB403_ID),
    ("beef_cutout", "GRADING_ID", sources.GRADING_ID),
])
def test_report_ids_match(app, name, mirrored):
    actual = _const(APPS / app / "app.py", name)
    assert int(actual) == int(mirrored), (
        f"apps/{app}/app.py {name}={actual} but letter/sources.py mirrors {mirrored}. "
        "The dashboard moved; update letter/sources.py to match.")


@pytest.mark.parametrize("app, name, mirrored", [
    ("cash_trade", "LMR_BASE", sources.LMR_BASE),
    ("beef_cutout", "LMR_BASE", sources.LMR_BASE),
    ("beef_weight", "AMS_URL", sources.AMS_SJ_LS712),
    ("beef_weight", "MARS_BASE", sources.MARS_BASE),
    ("beef_weight", "FIS_SECTION", sources.FIS_SECTION),
])
def test_endpoints_match(app, name, mirrored):
    assert _const(APPS / app / "app.py", name) == mirrored


def test_fis_report_id_matches():
    actual = _const(APPS / "beef_weight" / "app.py", "FIS_REPORT_ID")
    assert int(actual) == int(sources.FIS_REPORT_ID)


# -- AMS report 3208 ----------------------------------------------------------
# Not mirrored from any dashboard -- no dashboard reads it. What needs guarding
# is the COLUMN ORDER, which is positional and carries no labels once the PDF is
# flattened to text. The fixture is a real 9/22/26 print.

FIXTURE = Path(__file__).parent / "fixtures" / "ams_3208_2026-09-22.txt"


def test_3208_columns_parse_in_the_expected_order():
    parsed = sources.parse_3208(FIXTURE.read_text(encoding="utf-8"))
    assert parsed["current_day"] == 105_000
    assert parsed["day_week_ago"] == 108_000
    assert parsed["day_year_ago"] == 119_912
    assert parsed["wtd"] == 210_000
    assert parsed["wtd_week_ago"] == 211_000
    assert parsed["wtd_year_ago"] == 229_195
    assert parsed["ytd"] == 19_731_641
    assert parsed["ytd_prev_year"] == 21_332_241
    assert parsed["ytd_pct_change"] == -7.5
    assert parsed["report_date"] == "2026-09-22"
    assert parsed["status"] == "Final"


def test_3208_matches_what_the_letter_printed():
    """
    The 9/15/26 letter printed "Daily slaughter- 108,000" and "WTD slaughter-
    211,000". A week later those are exactly the week-ago columns, which is the
    check that the column mapping is right rather than merely self-consistent.
    """
    parsed = sources.parse_3208(FIXTURE.read_text(encoding="utf-8"))
    assert parsed["day_week_ago"] == 108_000
    assert parsed["wtd_week_ago"] == 211_000


def test_3208_revision_marker_does_not_shift_columns():
    """
    A revised figure is flagged with a bare "R" line between values. Counting it
    as a column would shift every later value one place -- and still produce nine
    plausible numbers, so nothing would look wrong.
    """
    text = FIXTURE.read_text(encoding="utf-8")
    assert "\nR\n" in text, "fixture no longer exercises the revision marker"
    parsed = sources.parse_3208(text)
    assert parsed["ytd_pct_change"] == -7.5


def test_ls712_section_headers_still_match_the_dashboard():
    """
    The SJ_LS712 parser keys off USDA's section headings. Both parsers must look
    for the same ones -- if AMS renames a section, both should break together.
    """
    app_text = (APPS / "beef_weight" / "app.py").read_text(encoding="utf-8")
    src_text = (REPO / "letter" / "sources.py").read_text(encoding="utf-8")
    for heading in (r"Livestock Slaughter \(head\)", r"Average Weights \(lbs\)"):
        assert heading in app_text, f"dashboard no longer looks for {heading!r}"
        assert heading in src_text, f"letter no longer looks for {heading!r}"


def test_snowflake_module_is_loaded_under_a_private_name():
    """
    CLAUDE.md: snowflake_db.py exists five times and Python caches by module
    NAME, so a plain `import snowflake_db` here could hand a Streamlit page this
    copy, or hand this generator a page's copy. The private name is the fix and
    must stay.
    """
    text = (REPO / "letter" / "sources.py").read_text(encoding="utf-8")
    assert "_letter_fci_db" in text
    assert not re.search(r"^\s*import snowflake_db", text, re.MULTILINE)
