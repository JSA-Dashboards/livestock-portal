"""New World Screwworm — the APHIS case feeds behind the fourth tab.

What is pinned here is mostly one claim and its consequences: on the Mexican
feed a case is Active for exactly fifteen days and then Inactive, with no
exceptions across all 578 rows of the shipped fixture. Everything the panel
can do that the US dashboard cannot — week over week, a reconstructed history,
an as-of date derived rather than assumed — rests on that, so it is checked
against the real file rather than a hand-built one, and the detectors are run
against deliberately broken forms as well as correct ones.

    python -m pytest tests/test_screwworm.py -q
"""

import ast
import io
import os
import sys
from datetime import date, timedelta

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "mexican_feeder_imports")
sys.path.insert(0, _APP)

import screwworm as sw  # noqa: E402

MODULE = os.path.join(_APP, "screwworm.py")
PAGE = os.path.join(_APP, "app.py")
FIX_MX = os.path.join(_HERE, "fixtures", "nws_mexico_2026-11-10.csv")
FIX_US = os.path.join(_HERE, "fixtures", "nws_us_2026-11-11.csv")

# The fixture's own as-of, stated so a test that recomputes it has something
# independent to agree with.
AS_OF = date(2026, 11, 8)


def _text(path):
    return io.open(path, encoding="utf-8-sig").read()


@pytest.fixture(scope="module")
def rows():
    return sw.parse_mexico(_text(FIX_MX))


@pytest.fixture(scope="module")
def us():
    return sw.parse_us(_text(FIX_US))


# ── The rule the whole panel rests on ───────────────────────────────────────

def test_the_active_window_reproduces_the_feed(rows):
    """Active <=> confirmed within 15 days, on every row, no exceptions.

    This is the claim that licenses reconstructing the history, and so the
    week-over-week figures, from one snapshot. 578 of 578.
    """
    assert len(rows) == 578
    wrong = [r for r in rows
             if r["status"] != ("Active" if sw._is_active(r["date"], AS_OF)
                                else "Inactive")]
    assert wrong == [], wrong[:5]
    assert sw.rule_holds(rows, AS_OF)


@pytest.mark.parametrize("days", [14, 16])
def test_a_window_one_day_either_side_does_not_reproduce_it(rows, monkeypatch, days):
    """The boundary is measured, not chosen, so it must be falsifiable.

    A guard that cannot fail is the thing it guards against. Fourteen days
    closes cases APHIS still calls active; sixteen keeps ones it has closed.
    """
    monkeypatch.setattr(sw, "ACTIVE_DAYS", days)
    assert not sw.rule_holds(rows, AS_OF)


def test_the_as_of_date_is_derived_and_lands_on_one_day(rows):
    """Not max(date), not today's clock — read off the status boundary."""
    assert sw.as_of(rows) == AS_OF
    act = [r["date"] for r in rows if r["status"] == "Active"]
    ina = [r["date"] for r in rows if r["status"] == "Inactive"]
    lo = max(ina) + timedelta(days=sw.ACTIVE_DAYS)
    hi = min(act) + timedelta(days=sw.ACTIVE_DAYS - 1)
    assert lo == hi == AS_OF, (lo, hi)


def test_a_broken_rule_returns_no_as_of_rather_than_a_number(rows):
    """If APHIS changes the rule the page must say so, not compute anyway.

    One case restated active long after its window is enough to make the two
    bounds cross, which is exactly the signal wanted.
    """
    bad = [dict(r) for r in rows]
    bad[0] = dict(bad[0], status="Active")       # the oldest case, Sep 2025
    assert bad[0]["date"] == date(2025, 9, 20)
    assert sw.as_of(bad) is None


def test_no_date_carries_both_statuses(rows):
    """A mixed date would mean the flip is not mechanical after all."""
    seen = {}
    for r in rows:
        seen.setdefault(r["date"], set()).add(r["status"])
    assert [d for d, s in seen.items() if len(s) > 1] == []


def test_the_as_of_never_runs_ahead_of_the_newest_case(rows):
    """Nothing can be published before it was confirmed.

    The bound that stops a gap in case dates pushing the as-of into the
    future and silently ageing real cases out of the active window.
    """
    assert sw.as_of(rows) >= max(r["date"] for r in rows) or True
    assert sw.as_of(rows) == max(r["date"] for r in rows)


# ── Counts and week over week ───────────────────────────────────────────────

def test_the_snapshot_reproduces_the_published_split(rows):
    s = sw.snapshot(rows, AS_OF)
    assert (s["total"], s["active"], s["inactive"]) == (578, 63, 515)
    assert s["active"] + s["inactive"] == s["total"]
    assert s["newest"] == AS_OF
    assert s["oldest"] == date(2025, 9, 20)


def test_week_over_week_satisfies_both_identities(rows):
    """Free audits: a total moves only by new cases, and active moves by
    what came in less what aged out. Either breaking means the window
    arithmetic has drifted from the counting."""
    w = sw.wow(rows, AS_OF)
    assert w["total_change"] == w["new_7"]
    assert w["active_change"] == w["new_7"] - w["aged_out"]
    assert w["inactive_change"] == w["total_change"] - w["active_change"]
    assert (w["total"], w["total_prev"]) == (578, 547)
    assert (w["active"], w["active_prev"]) == (63, 59)


def test_the_weeks_are_anchored_blocks_not_calendar_weeks(rows):
    """Every block is seven days, so there is never a partial one.

    A calendar week is partial on six days in seven, and differencing three
    days against seven prints a collapse that is only the calendar.
    """
    blocks = sw.weekly_new(rows, AS_OF, 10)
    assert blocks, "no blocks"
    for b in blocks:
        assert (b["end"] - b["start"]).days == sw.WEEK - 1
    assert blocks[-1]["end"] == AS_OF
    ends = [b["end"] for b in blocks]
    assert all((b - a).days == sw.WEEK for a, b in zip(ends, ends[1:]))


def test_only_the_newest_block_is_provisional(rows):
    """The chart has to show the settling week as settling.

    It ends on the newest published case while the file is written days
    later, so a full-height bar there reads as a turn in the outbreak.
    """
    blocks = sw.weekly_new(rows, AS_OF, 10)
    assert [b["provisional"] for b in blocks] == [False] * (len(blocks) - 1) + [True]


def test_the_blocks_sum_to_the_cases_they_span(rows):
    blocks = sw.weekly_new(rows, AS_OF, 60)
    spanned = sum(b["count"] for b in blocks)
    first = min(b["start"] for b in blocks)
    assert spanned == sum(1 for r in rows if first <= r["date"] <= AS_OF)


def test_a_date_before_the_file_reconstructs_what_it_then_said(rows):
    """The point of the whole exercise: last week is recomputable.

    Fifteen days back, every case confirmed in that window must be the active
    set — which is only true because status is a function of the two dates.
    """
    d = AS_OF - timedelta(days=15)
    assert sw.active_on(rows, d) == sum(
        1 for r in rows if 0 <= (d - r["date"]).days <= 14)
    assert sw.total_on(rows, d) < sw.total_on(rows, AS_OF)


def test_nothing_in_the_module_reads_the_clock():
    """Every count takes its as-of date as an argument.

    `date.today()` anywhere here would compute the active window against a
    day the file does not reach, drop cases APHIS still calls active off the
    back of it, and render a plausible number with nothing raising. The same
    reason `cof_recap._class_periods` reads the header and the FCI
    `published` rule takes `today` as an argument.
    """
    tree = ast.parse(_text(MODULE))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("today", "now", "utcnow"):
            raise AssertionError(f"reads the clock at line {node.lineno}")


# ── Scope and breakdowns ────────────────────────────────────────────────────

def test_the_feed_is_the_within_100_miles_list(rows):
    """The caption says this is not a national count, so that must stay true."""
    assert sw.in_scope(rows)
    miles = [r["miles"] for r in rows if r["miles"] is not None]
    assert max(miles) == sw.MAX_MILES


def test_the_unlocated_cases_are_kept_and_are_the_newest(rows):
    """Dropping State='NA' would silently delete the most recent week.

    On this file all 24 of them are the newest eight days — which is exactly
    the stretch a reader opens the tab to look at.
    """
    na = [r for r in rows if r["state"] == sw.NO_STATE]
    assert len(na) == 24
    assert min(r["date"] for r in na) >= AS_OF - timedelta(days=8)
    assert sw.NO_STATE in [s["state"] for s in sw.by_state(rows, AS_OF)]
    assert sw.by_state(rows, AS_OF)[-1]["state"] == sw.NO_STATE


def test_the_state_totals_sum_to_the_case_total(rows):
    agg = sw.by_state(rows, AS_OF)
    assert sum(s["total"] for s in agg) == 578
    assert sum(s["active"] for s in agg) == 63


def test_every_state_in_the_feed_has_a_coordinate(rows):
    """A state missing from the map reads as a state with no cases.

    Which is the worst way for this to fail: it looks like good news.
    """
    assert sw.unmapped_states(rows) == []


def test_every_mapped_port_is_a_border_port():
    """The crossings on the map and border.KNOWN_PORTS are one roster.

    Two spellings of one crossing is the trap border.PORT_ALIASES already
    exists to undo, and it split 2024's Santa Teresa 136/56 across two names.
    """
    import border as bd
    for port in sw.PORT_COORDS:
        assert port in bd.KNOWN_PORTS, port


def test_cattle_are_the_majority_and_the_species_shares_sum(rows):
    sp = sw.by_species(rows, AS_OF)
    assert abs(sum(s["share"] for s in sp) - 1.0) < 1e-9
    assert sum(s["count"] for s in sp) == 578
    assert sp[0]["species"] == "Bovine"
    assert 0.55 < sw.cattle_share(rows, AS_OF) < 0.58


def test_the_distance_bands_cover_the_whole_range_without_overlap(rows):
    bands = sw.by_distance(rows, AS_OF)
    assert bands[0]["low"] == 0 and bands[-1]["high"] == sw.MAX_MILES
    for a, b in zip(bands, bands[1:]):
        assert b["low"] == a["high"] + 1
    priced = sum(1 for r in rows if r["miles"] is not None)
    assert sum(b["count"] for b in bands) == priced


def test_the_nearest_active_case_is_reported_with_its_date(rows):
    n = sw.nearest(rows, AS_OF)
    assert n["miles"] == 2.0 and n["state"] == "Sonora"
    assert sw._is_active(n["date"], AS_OF)
    # and the all-cases figure reaches closer than the active one
    assert sw.nearest(rows, AS_OF, active_only=False)["miles"] == 0.0


# ── Parsing ─────────────────────────────────────────────────────────────────

def test_the_bom_is_handled(rows):
    """utf-8 rather than utf-8-sig puts \\ufeff on the first column name, so
    every date lookup returns None and the parse yields 578 empty rows rather
    than an error."""
    raw = io.open(FIX_MX, "rb").read()
    assert raw[:3] == b"\xef\xbb\xbf"
    naive = sw.parse_mexico(raw.decode("utf-8"))
    assert naive == [], "a BOM-blind parse must be visibly empty, not subtly wrong"
    assert len(rows) == 578


def test_a_row_with_no_usable_date_is_dropped_not_carried():
    """Every figure is a function of the date; a null one cannot be counted."""
    text = ('"Date (mm/dd/yy)","State","Species","Age","Active/Inactive*",'
            '"USDA Sterile Insect Dispersal","Approximate Miles From US"\n'
            '"11/08/26","Sonora","Bovine","4 months","Active","**",11\n'
            '"","Sonora","Bovine","4 months","Active","**",11\n'
            '"not a date","Sonora","Bovine","4 months","Active","**",11\n')
    assert len(sw.parse_mexico(text)) == 1


def test_accented_state_names_survive(rows):
    assert any(r["state"] == "Nuevo León" for r in rows)
    assert "Nuevo León" in sw.MX_STATE_COORDS


# ── The US half ─────────────────────────────────────────────────────────────

def test_the_us_active_count_is_exact_even_though_the_window_is_not(us):
    """An active US case is a recent one, so four months holds every one.

    65 reconciles against the dashboard's own 126 domestic less 61 inactive.
    """
    assert us["active"] == 65
    assert us["window_domestic"] == 82 and us["window_total"] == 90


def test_the_us_months_parse_in_order(us):
    assert [m["month"] for m in us["months"]] == [
        "2026-08", "2026-09", "2026-10", "2026-11"]
    oct_ = [m for m in us["months"] if m["month"] == "2026-10"][0]
    assert (oct_["domestic"], oct_["total"]) == (33, 38)
    assert (oct_["active"], oct_["inactive"]) == (24, 9)
    for m in us["months"]:
        assert m["active"] + m["inactive"] == m["domestic"]


def test_the_us_active_flag_is_not_a_fifteen_day_clock(us):
    """The two countries' 'active' mean different things, and the page says so.

    If the US used Mexico's mechanical window, October's cases — 11 to 41
    days old at this reading — would all be closed. 24 of 33 are not.
    """
    oct_ = [m for m in us["months"] if m["month"] == "2026-10"][0]
    assert oct_["active"] >= 20


def test_the_us_half_carries_no_all_time_total(us):
    """It cannot have one: the worksheet draws four months and the outbreak
    began in June. An all-time figure here would be the four-month window
    wearing a label it has not earned, so the page links out instead."""
    assert "all_time" not in us
    assert "total" not in us


# ── Where this module may reach ─────────────────────────────────────────────

def test_it_reaches_exactly_the_two_documented_hosts():
    """border.py and mx_prices.py may not fetch at all; this one may, because
    both feeds are keyless and no credential can enter the process. The
    precedent is corn_demand.py and the guard is the same."""
    src = _text(MODULE)
    tree = ast.parse(src)
    urls = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("http")]
    hosts = {u.split("/")[2] for u in urls}
    assert hosts == {"www.aphis.usda.gov", "publicdashboards.dl.usda.gov"}, hosts


def test_it_asks_for_no_credential():
    src = _text(MODULE)
    for bad in ("API_KEY", "api_key", "SNOWFLAKE", "getenv", "environ",
                "password", "token"):
        assert bad not in src, bad


def test_the_us_half_fails_on_its_own(monkeypatch):
    """publicdashboards.dl.usda.gov is a host nothing else in this repo reads,
    and marsapi is the standing proof a USDA host can be unreachable from
    Community Cloud. The Mexican half must survive it."""
    monkeypatch.setattr(sw, "fetch_mexico", lambda *a, **k: {"rows": [], "x": 1})
    monkeypatch.setattr(sw, "fetch_us",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked")))
    out = sw.load_all()
    assert out["mx"] is not None and out["mx_error"] is None
    assert out["us"] is None and "blocked" in out["us_error"]


def test_the_schema_argument_carries_no_underscore():
    """Streamlit drops an underscore-prefixed argument from the cache key,
    which is the half of that trap that looks fixed and is not."""
    import inspect
    params = inspect.signature(sw.load_all).parameters
    assert "schema" in params and "_schema" not in params


def test_the_page_passes_the_schema_at_the_call_site():
    """A default is never hashed, so a loader called bare keys on nothing."""
    src = io.open(PAGE, encoding="utf-8-sig").read()
    assert "sw.SCHEMA" in src, "the page must pass screwworm.SCHEMA into the cache key"


# ── The page's own decisions ────────────────────────────────────────────────

def _page():
    return io.open(PAGE, encoding="utf-8-sig").read()


def test_the_tab_is_in_both_views():
    """A market reading, not a workbench, and that is a decision to pin.

    Screwworm is why these crossings closed, every figure is APHIS's own
    published count, and a client watching the crossings panel has more
    reason to want it than we do. Corn Demand beside it is hidden; this is
    not. Pinned in BOTH directions so it stays a decision rather than
    something that rotted.
    """
    src = _page()
    call = src[src.index("= portal_view.tabs("):]
    call = call[:call.index(")") + 1]
    assert '"New World Screwworm"' in call
    assert "hide=" in call
    hide = call[call.index("hide="):]
    assert "New World Screwworm" not in hide, \
        "the screwworm tab must not be hidden from the client deployment"
    assert "Corn Demand" in hide, "Corn Demand is the staff-only one"


def test_the_part_month_bar_says_it_is_part_finished():
    """Eleven days of November stood taller than all of October.

    Drawn bare that is a true number telling a false story -- the part-period
    failure `annual_span()` guards on the retention chart and `YTD_CUT` on
    the heifer-share one. The Mexican chart uses a hollow bar; a stacked bar
    cannot be hollowed legibly, so this one carries it in the axis label,
    which also survives a screenshot.
    """
    src = _page()
    assert '(so far)' in src
    assert 'date.today().strftime("%Y-%m")' in src, \
        "the partial month must be identified, not assumed to be the last one"


def test_the_map_caption_names_the_country_it_plots():
    """The map draws both countries' ground and one country's cases.

    A reader who takes the empty north at face value concludes the US has
    none, when it has more than a hundred. The caption has to say so before
    anything else, and it has to point at where the US figures are.
    """
    src = _page()
    i = src.index("Mexican cases only")
    cap = src[i:i + 500]
    assert "US cases are counted further down" in cap


def test_the_headline_tiles_are_one_grid_not_columns():
    """st.columns gives a ragged row when the feet wrap differently.

    The defect CLAUDE.md records for the daily cash tiles, which py_compile,
    the suite and get_page_text all pass. Grid items stretch to their row by
    default. st.html also skips the markdown parser, where a pair of dollar
    signs becomes inline LaTeX.
    """
    src = _page()
    i = src.index('with tab_nws:')
    tab = src[i:]
    assert 'nws-grid' in tab
    assert 'st.html(' in tab


def test_staleness_is_judged_on_the_write_date_not_the_case_date():
    """A healthy edition always reaches only two or three days back.

    The publication lag means a rule on the newest case date would cry stale
    every single day, which teaches a reader to ignore the one time it
    matters.
    """
    src = _page()
    i = src.index("_stale = ")
    assert "_written_age" in src[i:i + 80], src[i:i + 80]
