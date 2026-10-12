"""
Which contract month the technical read is about.

The letter used to run technicals on the front contract always. It is not
always the nearby — on a roll week it routinely is not, and the saved draft
for 2026-10-12 read "Dec live cattle holding support at 100-day MA at
225.675" under a heading that said **Oct**. Ross asked for a per-product
dropdown that day.

WHAT CAN GO WRONG HERE IS A PAIRING, not a value. `render.technicals_block`
prints the heading off `tech["month"]` and `build.hints()` quotes the 9-day,
20-day, swing high/low and prior range off the same dict. Resolve those in
two places and the letter eventually says Dec over October's averages, with
nothing raising — the failure this repo records three times between the
letter and a dashboard. So every caller goes through `select_technicals`,
and these tests are mostly about that.

    python -m pytest tests/test_technicals_month.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from letter import build as letter_build  # noqa: E402
from letter import render  # noqa: E402

PAGE = REPO / "apps" / "weekly_reports" / "app.py"


def ctx():
    """Real shape: three live cattle months, three feeder, as gather() leaves it."""
    return {
        "live_cattle": [{"month": "Oct", "ticker": "LEV6"},
                        {"month": "Dec", "ticker": "LEZ6"},
                        {"month": "Feb", "ticker": "LEG7"}],
        "feeder_cattle": [{"month": "Oct", "ticker": "GFV6"},
                          {"month": "Nov", "ticker": "GFX6"},
                          {"month": "Jan", "ticker": "GFF7"}],
        "tech_lc_all": {"Oct": {"month": "Oct", "ma": {"9": 220.94}},
                        "Dec": {"month": "Dec", "ma": {"9": 223.60}},
                        "Feb": {"month": "Feb", "ma": {"9": 226.04}}},
        "tech_fc_all": {"Oct": {"month": "Oct", "ma": {"9": 338.64}},
                        "Nov": {"month": "Nov", "ma": {"9": 335.99}},
                        "Jan": {"month": "Jan", "ma": {"9": 329.70}}},
    }


def test_it_still_defaults_to_the_front_contract():
    """The change must not move anyone's letter until they pick a month."""
    c = ctx()
    letter_build.select_technicals(c)
    assert c["tech_lc_month"] == "Oct" and c["tech_fc_month"] == "Oct"
    assert c["tech_lc"]["ma"]["9"] == 220.94


def test_a_chosen_month_wins():
    c = ctx()
    c["tech_lc_month"] = "Dec"
    letter_build.select_technicals(c)
    assert c["tech_lc"]["month"] == "Dec"
    assert c["tech_lc"]["ma"]["9"] == 223.60


def test_the_two_products_are_independent():
    """Dec live cattle against Jan feeders is an ordinary pair of reads, not
    an edge case — the whole point of two dropdowns."""
    c = ctx()
    c["tech_lc_month"], c["tech_fc_month"] = "Dec", "Jan"
    letter_build.select_technicals(c)
    assert c["tech_lc"]["month"] == "Dec"
    assert c["tech_fc"]["month"] == "Jan"


def test_a_month_that_has_rolled_off_falls_back_to_the_front():
    """
    The choice is stored per issue date and the contracts roll under it —
    feeders went Sep to Oct/Nov/Jan mid-week on 2026-09-25. Falling back to
    nothing would cost the section its figures and its heading; falling back
    to the front contract is what it did before the dropdown existed.
    """
    c = ctx()
    c["tech_lc_month"] = "Aug"
    letter_build.select_technicals(c)
    assert c["tech_lc_month"] == "Oct"
    assert c["tech_lc"]["month"] == "Oct"


def test_no_technicals_at_all_does_not_raise_or_invent():
    c = {"live_cattle": [], "feeder_cattle": []}
    letter_build.select_technicals(c)
    assert "tech_lc" not in c and c.get("tech_lc_month") is None


def test_a_month_whose_fetch_failed_is_still_offered():
    """
    Dropping it would make a broken feed look like a contract that does not
    exist, and the Massive cattle series has gone dark for a fortnight before
    now. It stays in the list and says why.
    """
    c = ctx()
    c["tech_lc_all"]["Dec"] = {"month": "Dec", "ticker": "LEZ6",
                               "error": "no bars returned"}
    assert "Dec" in letter_build.technical_months(c, "tech_lc")
    c["tech_lc_month"] = "Dec"
    letter_build.select_technicals(c)
    assert c["tech_lc"]["error"] == "no bars returned"


def test_the_months_are_offered_in_contract_order():
    """Front first — a dropdown sorted alphabetically would open on Dec."""
    assert letter_build.technical_months(ctx(), "tech_lc") == ["Oct", "Dec", "Feb"]
    assert letter_build.technical_months(ctx(), "tech_fc") == ["Oct", "Nov", "Jan"]


def test_the_heading_and_the_reference_figures_cannot_disagree():
    """
    The pairing this whole feature has to get right: the <h3> the client
    reads and the averages Ross writes against come from one dict.
    """
    c = ctx()
    c["tech_lc_month"] = "Feb"
    letter_build.select_technicals(c)
    html = render.technicals_block(c["tech_lc"], ["a read"], "Live Cattle")
    assert "Feb Live Cattle" in html
    assert c["tech_lc"]["ma"]["9"] == 226.04


# -- the wiring, which is where this can rot -------------------------------

def test_gather_builds_every_contract_not_just_the_front():
    src = (REPO / "letter" / "build.py").read_text(encoding="utf-8")
    assert "ctx[key + \"_all\"] = built" in src
    assert "ctx[\"live_cattle\"][0][\"ticker\"]" not in src, (
        "gather is back to building only the front contract")


def test_the_no_fetch_render_applies_the_stored_choice():
    """
    Without this the preview and the emailed PDF come out on different
    months — `main --no-fetch` is the run that makes the PDF.
    """
    src = (REPO / "letter" / "build.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "select_technicals"]
    assert calls, "main() never resolves the chosen month"


def test_the_page_applies_the_choice_before_it_reads_the_figures():
    """
    ORDERING, and it is the one subtle thing here. `hints()` reads
    ctx["tech_lc"], so applying the dropdown after it has run shows the new
    month's heading over the old month's numbers for a rerun. Script order
    again — the same shape as the NameError recorded for the WASDE panel.
    """
    src = PAGE.read_text(encoding="utf-8")
    apply_at = src.index("letter_build.select_technicals(ctx)")
    hints_at = src.index("hints = letter_build.hints(ctx, kind)")
    assert apply_at < hints_at, "the page reads the figures before applying the month"


def test_the_recap_format_offers_both_products():
    """Tue/Wed/Thu has ONE written technicals section covering both, and
    hints() still quotes both — so both pickers belong on it."""
    src = PAGE.read_text(encoding="utf-8")
    block = src[src.index("_TECH_PICKERS"):src.index("_TECH_PICKERS") + 600]
    assert '"technicals_lc"' in block and '"technicals_fc"' in block
    assert block.count("tech_lc") >= 2, "the recap key is missing a product"
