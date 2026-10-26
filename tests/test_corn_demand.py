"""Corn demand that moves with Mexican feeder cattle — the staff-only tab.

The panel's whole reason to exist is that the intuitive answer is wrong. While
the border was shut, cattle that would have crossed were fed in Mexico on US
corn, so reopening reads as lost US export demand. It is — but the same animal
eats about 1.6x the corn finished in a US yard, so the demand MOVES to domestic
feed and grows. An export tile on its own would be arithmetically right and
would tell a reader the opposite of what happens.

    python -m pytest tests/test_corn_demand.py -q
"""

import ast
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "mexican_feeder_imports")
sys.path.insert(0, _APP)

import corn_demand as cdm  # noqa: E402

PAGE = os.path.join(_APP, "app.py")
MODULE = os.path.join(_APP, "corn_demand.py")


def _page():
    return open(PAGE, encoding="utf-8-sig").read()


def _code_of(fn):
    """Source with the docstring stripped — these guards must read code, not
    the prose explaining the rule."""
    node = ast.parse(inspect.getsource(fn).lstrip()).body[0]
    body = node.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return chr(10).join(ast.unparse(n) for n in body)


# ── the arithmetic is anchored to this repo's own convention ────────────────

def test_it_reproduces_corn_costs_own_worked_example():
    """corn_cost.py states "an 80% corn ration and 6.5:1 conversion ... about
    $52 a head over 650 lb of gain". If this formula reproduces that, the US
    side uses the portal's documented convention rather than something
    invented here — which is the only reason to prefer these constants."""
    # AS FED -- that rule of thumb is an as-fed one, which is itself the
    # reason `basis` has no default.
    mt = cdm.corn_per_head(0, 650, 6.5, 0.80, basis="as_fed")
    dollars = mt * cdm.BU_PER_MT * 0.86      # that module's measured spread
    assert abs(dollars - 52) < 1.0, dollars
    assert abs(mt * cdm.BU_PER_MT / 6.5 - 9.29) < 0.2


def test_corn_is_charged_from_the_BUNK_not_the_border():
    """THE LARGEST ERROR AVAILABLE HERE. The pounds between the border and the
    feedlot are put on at grass on both sides — in Mexico the first 100-150 kg
    carries no grain at all. A first version ran crossing-weight to finish
    through a conversion and inflated both sides by roughly 40%."""
    sig = inspect.signature(cdm.corn_per_head)
    first = list(sig.parameters)[0]
    assert "feedlot" in first or "in_lb" in first, first
    # Raising the on-feed weight must REDUCE corn, because it shortens the
    # grain-fed phase. A formula keyed on the border would not move at all.
    hi = cdm.corn_per_head(900, 1400, 6.8, 0.80, basis="as_fed")
    lo = cdm.corn_per_head(700, 1400, 6.8, 0.80, basis="as_fed")
    assert hi < lo


def test_the_two_sides_use_one_formula():
    """The Mexico/US comparison must be a difference in INPUTS, not in method.
    Two formulas is how the ratio becomes an artefact of the arithmetic."""
    src = _code_of(cdm.displaced)
    assert src.count("corn_per_head(") == 2, src


def test_the_us_animal_eats_more_and_the_net_is_positive():
    """The finding the panel exists to carry: reopening costs the export line
    and adds MORE to domestic feed."""
    r = cdm.displaced(1_000_000)
    assert r["per_head_us_bu"] > r["per_head_mx_bu"]
    assert r["net_bu"] > 0
    assert abs(r["net_bu"] - (r["domestic_bu"] - r["export_bu"])) < 1e-6


def test_the_per_head_figures_land_where_independent_research_puts_them():
    """Checked against two independent Mexican routes (a UNAM finishing
    programme and CONAFAB's feedlot compound-feed total) giving 0.6-1.0 MT a
    head under closure conditions, and K-State's August 2026 closeouts giving
    1.3-1.8 MT for the US animal. Pinning
    the BAND, not the point, because every input is an assumption — but a
    default that drifts outside it is a default nobody re-derived."""
    r = cdm.displaced(1_000_000)
    mx_mt = r["mx_mt"] / 1_000_000
    us_mt = r["us_mt"] / 1_000_000
    assert 0.70 <= mx_mt <= 1.05, mx_mt
    assert 1.25 <= us_mt <= 1.85, us_mt
    assert 1.3 <= us_mt / mx_mt <= 2.3, us_mt / mx_mt


# ── PSD's two traps ─────────────────────────────────────────────────────────

def test_the_latest_year_is_never_a_forward_forecast():
    """PSD carries marketing years ahead of the calendar. Taking max() headlined
    MY2027's 625,000-head RECOVERY FORECAST as if it were the year running,
    reporting a 545,000 head shortfall where the real one is about a million.
    The figure looked entirely plausible, which is the whole problem."""
    from datetime import date
    cattle = {2023: {"Exports": 1295.0}, 2024: {"Exports": 1250.0},
              2025: {"Exports": 229.0}, 2026: {"Exports": 150.0},
              2027: {"Exports": 625.0}}        # <- forecast
    sf, base, ly, lh = cdm.crossing_shortfall(
        cattle, normal_years=(2023, 2024), today=date(2026, 10, 26))
    assert ly == 2026, ly
    assert lh == 150_000
    assert abs(sf - (1_272_500 - 150_000)) < 1


def test_the_baseline_is_several_normal_years_not_one():
    """Mexican exports are lumpy — 1,037 / 965 / 1,295 / 1,250 thousand head
    over 2021-24 — so one year as the counterfactual moves the headline by a
    third depending which is picked."""
    src = inspect.signature(cdm.crossing_shortfall)
    years = src.parameters["normal_years"].default
    assert len(years) >= 3, years


def test_a_zero_filled_us_share_falls_back_and_says_so():
    """**PSD CARRIES A LITERAL ZERO** for `TY Imp. from U.S.` in trade years
    that have not closed. MY2025 and MY2026 both read 0.0 while imports are
    26,200 and 27,200. Read naively that says Mexico stopped buying US corn
    altogether — the most wrong a number on this page could be."""
    corn = {2021: {"Imports": 17584.0, "TY Imp. from U.S.": 16803.0},
            2022: {"Imports": 19325.0, "TY Imp. from U.S.": 16454.0},
            2023: {"Imports": 24222.0, "TY Imp. from U.S.": 23945.0},
            2024: {"Imports": 25930.0, "TY Imp. from U.S.": 25809.0},
            2025: {"Imports": 26200.0, "TY Imp. from U.S.": 0.0}}
    share, reported = cdm.us_share(corn, 2025)
    assert reported is False
    assert 0.80 < share < 1.01, share
    share24, rep24 = cdm.us_share(corn, 2024)
    assert rep24 is True and abs(share24 - 25809 / 25930) < 1e-9


def test_the_substitution_check_exists_and_counts_every_grain():
    """Corn feed use rose +1,700 thousand MT in MY2025, which reads as a cattle
    story. TOTAL feed grain rose +320: sorghum fell 900 and feed wheat 450 as
    Mexico's own crops failed. Quoting the corn line alone attributes the lot
    to cattle and is wrong by roughly a factor of five in that year."""
    grains = {
        "Corn":    {2024: {"Feed Dom. Consumption": 27500.0},
                    2025: {"Feed Dom. Consumption": 29200.0}},
        "Sorghum": {2024: {"Feed Dom. Consumption": 4700.0},
                    2025: {"Feed Dom. Consumption": 3800.0}},
        "Wheat":   {2024: {"Feed Dom. Consumption": 650.0},
                    2025: {"Feed Dom. Consumption": 200.0}},
    }
    rows = cdm.feed_grain_total(grains)
    by = {y: t for y, _p, t in rows}
    assert by[2024] == 32850.0
    assert by[2025] == 33200.0
    corn_rise = 29200 - 27500
    total_rise = by[2025] - by[2024]
    assert total_rise < corn_rise / 4, (total_rise, corn_rise)


# ── the panel ───────────────────────────────────────────────────────────────

def test_the_tab_is_staff_only_and_its_body_is_guarded():
    """HIDING A TAB'S LABEL DOES NOT STOP ITS BODY. portal_view.Hidden is a
    no-op context manager, so an unguarded `with tab_corn:` would run the PSD
    fetch on a client load and render the panel UNFRAMED into their page."""
    page = _page()
    assert 'hide=["Corn Demand"]' in page
    # COMMENTS STRIPPED FIRST. This failed on the page's own comment warning
    # that an unguarded `with tab_corn:` would leak the panel to clients --
    # the trap tests/test_rundown.py and test_border_crossing_label.py both
    # record. A guard that trips over the note describing the rule reads
    # exactly like the rule being broken.
    code = chr(10).join(l for l in page.splitlines()
                        if not l.lstrip().startswith("#"))
    i = code.index("if portal_view.shown(tab_corn):")
    j = code.index("with tab_corn:")
    assert i < j, "the body is not behind portal_view.shown()"


def test_the_net_tile_is_on_the_panel():
    """The export tile alone is arithmetically right and tells a reader the
    opposite of what happens to US corn demand. The net is never omitted."""
    page = _page()
    assert "NET US corn demand" in page
    assert "EXPORT demand lost" in page
    assert "DOMESTIC demand gained" in page


def test_the_panel_says_usda_is_not_forecasting_a_fall():
    """USDA's own post-reopening vintage has Mexican corn imports UP on the
    year, on poultry growth. Three tiles sizing a displacement, with nothing
    saying that, would read as a forecast that Mexican demand falls."""
    page = _page()
    assert "USDA is not forecasting Mexico to buy less corn" in page


def test_the_loader_passes_the_schema_at_the_call_site():
    """st.cache_data hashes the arguments it is CALLED with: a parameter at its
    default contributes nothing to the key, and an underscore-prefixed one is
    excluded outright."""
    page = _page()
    assert isinstance(cdm.SCHEMA, int)
    tree = ast.parse(page)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "load_corn")
    args = [a.arg for a in fn.args.args]
    assert args and not any(a.startswith("_") for a in args), args
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "load_corn"]
    assert calls and all(c.args or c.keywords for c in calls)


# ── the HTTP departure is deliberate and bounded ────────────────────────────

def test_this_module_reaches_psd_and_nothing_else():
    """border.py and mx_prices.py import no `requests` and must not start.
    What that rule protects is CREDENTIALS — every key this page's data needs
    belongs to an ingest elsewhere. PSD is a public keyless bulk file, so
    nothing of the sort enters the process; but the departure is bounded to
    one host and pinned here."""
    src = open(MODULE, encoding="utf-8").read()
    tree = ast.parse(src)
    urls = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("http")]
    assert urls, "no URL constants found"
    for u in urls:
        assert u.startswith("https://apps.fas.usda.gov/psdonline/"), u
    assert "api.census.gov" not in src, (
        "Census needs a key this deployment deliberately does not carry")


def test_the_two_existing_modules_still_cannot_fetch():
    """Adding this module must not have loosened the rule for the others."""
    for name in ("border.py", "mx_prices.py"):
        tree = ast.parse(open(os.path.join(_APP, name), encoding="utf-8").read())
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                imported.add(n.module.split(".")[0])
        for banned in ("requests", "urllib", "httpx"):
            assert banned not in imported, f"{name} imports {banned}"


# ── the basis, which is where the conversions went wrong ────────────────────

def test_basis_has_no_default_and_is_validated():
    """K-State publishes feed:gain on DRY MATTER, UNAM's Mexican programme AS
    FED, and corn_cost.py's "80% and 6.5:1" is an as-fed rule of thumb.
    Multiplying a DM conversion straight through to market-weight bushels
    understates corn by about 18%, and nothing about the result looks wrong.
    So a caller must say which it has."""
    import pytest
    sig = inspect.signature(cdm.corn_per_head)
    p = sig.parameters["basis"]
    assert p.default is inspect.Parameter.empty, "basis acquired a default"
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(ValueError):
        cdm.corn_per_head(700, 1400, 6.5, 0.7, basis="wet")


def test_dry_matter_carries_the_moisture_step_and_as_fed_does_not():
    """Corn is marketed at about 15.5% moisture. The DM route must come out
    HIGHER in market weight for identical feed inputs — if the two agree, the
    step is missing."""
    dm = cdm.corn_per_head(825, 1500, 6.47, 0.65, basis="dm")
    af = cdm.corn_per_head(825, 1500, 6.47, 0.65, basis="as_fed")
    assert dm > af
    assert abs(dm * cdm.CORN_DM - af) < 1e-9
    assert 0.80 < cdm.CORN_DM < 0.90


def test_each_side_declares_its_own_basis():
    """The two are not on the same footing and `displaced` must not assume
    they are."""
    assert cdm.US_BASIS == "dm"
    assert cdm.MX_BASIS == "as_fed"
    src = _code_of(cdm.displaced)
    assert "basis=mx_basis" in src and "basis=us_basis" in src


def test_the_defaults_are_the_published_figures():
    """THE DEFECT THIS PINS: the conversions were picked in a sensitivity run
    before the research existed, the weights and shares were updated to match
    it afterwards, and the conversions were not — leaving a comment citing
    6.47 directly above a constant reading 6.8. The output was close because
    the inflated conversion was absorbing the missing dry-matter step."""
    assert cdm.US_CONVERSION == 6.47, "K-State Aug 2026 closeouts"
    assert cdm.US_FEEDLOT_IN_LB == 825.0 and cdm.US_FINISH_LB == 1500.0
    assert 6.0 <= cdm.MX_CONVERSION <= 6.5, "UNAM gives 6.0-6.5 as fed"
    assert 0.38 <= cdm.MX_CORN_SHARE <= 0.54, "corn is 38-54% of the ration"
    assert 0.50 <= cdm.US_CORN_SHARE <= 0.90, "Samuelson survey range"


def test_the_page_says_which_basis_each_box_wants():
    """A box reading 'feed conversion' that silently wants dry matter on one
    side and as-fed on the other is the same defect one level up, on controls
    a reader can move."""
    page = _page()
    assert "AS FED" in page and "DRY MATTER" in page
    assert "different bases" in page


# ── provenance ──────────────────────────────────────────────────────────────

def test_every_feeding_input_carries_a_source_and_an_honest_grade():
    """Ross asked twice where a figure came from and the answer lived only in
    a docstring and a slider tooltip. The citations sit beside the constants
    now and the page renders them, so a default that moves without its
    citation is visible rather than silent."""
    grades = {"measured", "judgement", "derived", "ours"}
    assert len(cdm.SOURCES) >= 8
    for r in cdm.SOURCES:
        assert r["side"] in {"US", "Mexico", "both"}, r
        assert r["strength"] in grades, r
        assert r["cite"].strip(), r
        assert r["sourced"].strip(), r


def test_the_inference_is_graded_as_ours_not_as_measured():
    """THE WEAKEST INPUT MUST SAY SO. The Mexican feedlot entry weight has no
    published counterpart -- it is taken from the closure gain less a pasture
    share. Grading it 'measured' alongside K-State's closeouts would put a
    guess and a survey on the same footing in the same table."""
    assert cdm.strength_of("Mexico", "Feedlot entry weight") == "ours"
    assert cdm.strength_of("US", "Feed conversion") == "measured"
    ours = [r for r in cdm.SOURCES if r["strength"] == "ours"]
    assert len(ours) == 1, [r["input"] for r in ours]


def test_the_mexican_cross_check_is_flagged_as_the_wrong_programme():
    """CONAFAB and the UNAM bottom-up converge beautifully -- on the NORMAL
    programme. The closure figure is that roughly doubled on FAS's
    description of longer feeding, so it is scaled rather than measured.
    Presenting it as an agreeing cross-check would be the most flattering
    available misreading."""
    mx = [c for c in cdm.CROSS_CHECKS if c["side"] == "Mexico"]
    assert mx, "no Mexican cross-check recorded"
    for c in mx:
        assert c["agrees"] is False
        assert "NORMAL PROGRAMME" in c.get("caveat", "").upper()
    us = [c for c in cdm.CROSS_CHECKS if c["side"] == "US"]
    assert len(us) >= 2 and all(c["agrees"] for c in us)


def test_the_page_renders_the_table_rather_than_retyping_it():
    """A provenance table typed into the page goes stale the first time a
    constant moves, which is the failure it exists to prevent."""
    page = _page()
    assert "Where these figures come from" in page
    assert "cdm.SOURCES" in page and "cdm.CROSS_CHECKS" in page
    # Scoped to the EXPANDER. A citation in a slider tooltip is correct and
    # useful -- the first version of this guard failed on exactly that, which
    # is the "trips over the thing it is checking" trap this file records.
    # What must not happen is the TABLE carrying typed copies, because those
    # go stale the first time a constant moves.
    i = page.index('"Where these figures come from"')
    block = page[i:i + 3000]
    for cite in ("Focus on Feedlots", "Livas", "CONAFAB", "Samuelson",
                 "MX2026-0040", "Iowa Beef"):
        assert cite not in block, (
            f"{cite!r} is typed into the expander instead of read from "
            f"cdm.SOURCES")


def test_the_head_box_is_capped_on_the_record_not_a_recent_mean():
    """IT WAS CAPPED AT THE 2022-24 MEAN AND REFUSED AN ORDINARY SCENARIO.
    1,170,000 is not a ceiling -- that window spans two weak years (965,000
    in 2022, 1,037,000 in 2021) while Mexico has shipped 1,485,000 in 2020,
    1,539,000 in 2012 and 1,658,000 in 1995. Typing 1.3 million turned the
    box red with nothing saying why, which is a control refusing something
    the border has actually done three times."""
    cattle = {1995: {"Exports": 1658.0}, 2020: {"Exports": 1485.0},
              2021: {"Exports": 1037.0}, 2022: {"Exports": 965.0},
              2023: {"Exports": 1295.0}, 2024: {"Exports": 1250.0},
              2026: {"Exports": 150.0}}
    peak, year = cdm.peak_exports(cattle)
    assert (peak, year) == (1_658_000, 1995)
    _sf, base, _ly, _lh = cdm.crossing_shortfall(
        cattle, normal_years=(2022, 2023, 2024))
    assert peak > base, "the cap must exceed the baseline it replaced"
    assert 1_300_000 <= peak, "1.3m must be accepted"


def test_the_page_caps_on_the_peak_and_says_so():
    page = _page()
    assert "cdm.peak_exports" in page
    assert "int(max(_peak, _base))" in page, (
        "the head box is not capped on the record")
    assert "most Mexico has" in page, "the cap is not explained to the reader"


def test_peak_exports_survives_an_empty_series():
    assert cdm.peak_exports({}) == (0.0, None)
