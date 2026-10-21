"""
Guards for the Cattle Cycles page.

THREE OF THESE COVER TRAPS THE REPO-WIDE TESTS DO NOT. The literal-tag-inside-
a-style-block check lives in `tests/test_six_state.py` scoped to
`apps/cme_feeder_cattle/app.py`, and the two-dollar-signs-is-LaTeX check lives
in `tests/test_cutout_prior_level.py` scoped to `apps/beef_cutout/app.py`.
Neither reaches a new page, and CLAUDE.md records both as found in a browser
rather than by a test. A new page ships them green unless it brings its own.

THE FIRST TEST IS THE ONE THAT MATTERS MOST. NASS carries both
`CATTLE, GE 500 LBS - PRICE RECEIVED...` and `CATTLE, STEERS & HEIFERS, GE 500
LBS - PRICE RECEIVED...`. They share the TAIL
`GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT`, which is in both, and
matching on that tail with `in` merges two different price definitions into
one plausible-looking series -- which is how the first cut of this analysis
was built. It moved the headline median from 7.4 years to 10.1 and rendered
perfectly throughout.

AN EARLIER VERSION OF THIS NOTE SAID THE SECOND STRING CONTAINS THE FIRST
WHOLE. It does not: they diverge at character 8, `CATTLE, GE` against
`CATTLE, STEERS`, so `broad in narrow` is False. The trap is entirely real
and the loose phrasing undersold it in the worst way -- a reader who tests
the claim as written gets False and concludes the guard is unnecessary.
`test_the_substring_trap_is_live_not_theoretical` asserts against the shared
tail, which is the thing that actually collides.
"""
import ast
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "cattle_cycles"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(ROOT))

import cycles  # noqa: E402


@pytest.fixture(scope="module")
def seed():
    s = cycles.load()
    assert s, "the committed seed must load"
    return s


@pytest.fixture(scope="module")
def page_src():
    return (APP_DIR / "app.py").read_text(encoding="utf-8-sig")


@pytest.fixture(scope="module")
def summary(seed):
    return cycles.summary(seed)


# -- the series identity ------------------------------------------------------

def test_series_are_named_by_exact_short_desc(seed):
    """Every series records the literal NASS short_desc it was built from."""
    for key in cycles.SERIES:
        desc = seed["series"][key]["short_desc"]
        assert desc.startswith("CATTLE, ") and "PRICE RECEIVED" in desc
        assert desc.endswith("MEASURED IN $ / CWT")


def test_the_substring_trap_is_live_not_theoretical(seed):
    """The two series share a TAIL, which is what a loose match collides on.

    Neither string contains the other whole -- asserted below, because that is
    the misreading this test exists to prevent. What collides is the tail, and
    matching on it with `in` is what spliced two price definitions together.
    """
    broad = seed["series"]["cattle_ge500"]["short_desc"]
    narrow = "CATTLE, STEERS & HEIFERS, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT"
    needle = "GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT"
    assert broad not in narrow and narrow not in broad, (
        "neither contains the other whole -- they part at 'CATTLE, GE' vs "
        "'CATTLE, STEERS'. If that changes, rewrite the docstring above too"
    )
    assert needle in broad and needle in narrow and broad != narrow, (
        "if these ever stop sharing the tail the trap is gone, but so is the "
        "reason this test exists -- check before deleting it"
    )


def test_the_seed_stores_nominal_prices_and_cpi_separately(seed):
    """Storing real values would freeze a base year into a committed file."""
    assert "cpi_u" in seed and seed["cpi_u"]["rows"]
    for key in cycles.SERIES:
        assert seed["series"][key]["unit"] == "$/cwt"
    # 1913 CPI is ~9.8 and 1913 cattle is single digits -- both unmistakably nominal.
    assert seed["cpi_u"]["rows"]["1913-01"] < 15


# -- the dating ---------------------------------------------------------------

def test_turns_alternate_peak_trough(summary):
    kinds = [k for _d, k in summary["turns"]]
    assert len(kinds) > 10
    assert all(a != b for a, b in zip(kinds, kinds[1:])), kinds


def test_no_dated_phase_is_shorter_than_the_minimum(summary):
    assert summary["phases"]
    short = [p for p in summary["phases"] if p["months"] < summary["min_phase"]]
    assert not short, short


def test_a_provisional_turn_is_never_dated(seed):
    """A turn inside the end buffer is returned separately and never becomes a phase."""
    s, _u = cycles.price(seed)
    tp, prov = cycles.turning_points(s)
    cutoff = s.index[-1] - __import__("pandas").DateOffset(months=cycles.END_BUFFER_MONTHS)
    assert all(d <= cutoff for d, _k in tp)
    assert all(d > cutoff for d, _k in prov)
    ends = {p["end"] for p in cycles.phases(s, tp)}
    assert not ends & {d for d, _k in prov}


def test_provisional_turns_do_not_reach_the_peer_statistics(summary):
    """The peer counts and ranks are built only from completed phases."""
    ctx = summary["context"]
    assert ctx["n_peers"] == len([p for p in summary["phases"] if p["phase"] == ctx["kind"]])
    assert ctx["age_months"] == (
        (summary["last"].year - ctx["start"].year) * 12
        + summary["last"].month - ctx["start"].month
    )


def test_minimum_phase_changes_the_cycle_count(seed):
    """The knob is real, which is why the page exposes it rather than hiding it."""
    counts = {}
    for mp in cycles.MIN_PHASE_CHOICES:
        d = cycles.summary(seed, min_phase=mp)
        counts[mp] = len(d["trough_to_trough"])
    assert len(set(counts.values())) > 1, counts
    assert counts[9] >= counts[18], counts


# -- the overlay --------------------------------------------------------------

def test_every_overlay_run_starts_at_100(summary):
    runs = summary["overlay"]
    assert len(runs) > 5
    for r in runs:
        assert r["x"][0] == 0
        assert abs(r["y"][0] - 100.0) < 1e-9, r["label"]


def test_exactly_one_overlay_run_is_the_running_one(summary):
    assert sum(1 for r in summary["overlay"] if r["running"]) == 1


# -- real vs nominal ----------------------------------------------------------

def test_deflating_changes_the_answer(seed):
    """If real and nominal agreed, the toggle would be decoration."""
    real, _ = cycles.price(seed, real=True)
    nom, _ = cycles.price(seed, real=False)
    assert real.idxmax().year != nom.idxmax().year, (
        "the real high is in the 1950s and the nominal high is recent -- that "
        "contrast is the point of the page"
    )
    assert real.idxmax().year < 1980 < nom.idxmax().year


def test_the_deflator_base_is_not_frozen_into_the_file(seed):
    """The units string names the month whose dollars are being quoted."""
    _s, units = cycles.price(seed, real=True)
    assert "dollars" in units and any(ch.isdigit() for ch in units)
    assert cycles.cpi_series(seed).last_valid_index() is not None


# -- module hygiene -----------------------------------------------------------

def test_cycles_module_reaches_no_network_and_no_database():
    """The arithmetic reads a file and nothing else, so the page cannot acquire
    an HTTP or Snowflake path through it."""
    tree = ast.parse((APP_DIR / "cycles.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    banned = {"requests", "urllib", "urllib3", "http", "snowflake", "snowflake_db",
              "psycopg2", "socket"}
    assert not (names & banned), names & banned
    assert names <= {"__future__", "json", "pathlib", "numpy", "pandas"}, names


@pytest.mark.parametrize("name", ["app.py", "cycles.py"])
def test_no_utf8_bom(name):
    """A BOM makes tests/test_cot_positions.py's repo walk skip the file on a
    SyntaxError, which EXEMPTS it from the cached-loader guard rather than
    failing. Two pages in this repo already carry one."""
    assert not (APP_DIR / name).read_bytes().startswith(b"\xef\xbb\xbf")


# -- the three page traps the repo-wide tests do not cover --------------------

def test_no_literal_tag_inside_the_style_block(page_src):
    """A literal tag inside a style element ENDS the element. A CSS comment
    reading "one class per <tr>" dropped an entire stylesheet on the index page
    and the data still read back perfectly through get_page_text."""
    low = page_src.lower()
    i = low.find("<style>")
    while i != -1:
        end = low.find("</style>", i)
        assert end != -1, "unterminated style block"
        body = page_src[i + len("<style>"):end]
        assert "<" not in body, f"literal tag inside a style block: {body[body.find('<'):][:60]!r}"
        i = low.find("<style>", end)


def test_raw_html_never_goes_through_the_markdown_parser(page_src):
    """st.markdown(unsafe_allow_html=True) STILL runs the markdown parser, so a
    block carrying two dollar amounts renders them as inline LaTeX and swallows
    everything between. st.html does not run the parser at all."""
    assert "unsafe_allow_html" not in page_src, (
        "emit raw HTML with st.html; the tile rows quote two prices in one block"
    )


def test_overlay_labels_cannot_land_on_each_other(summary):
    """The end-of-line year labels must not overlap, at any setting.

    Four runs finish within a few months and a few index points of one
    another, so without decluttering 1923-1929 sits on 1945-1951 and
    1967-1973 sits on the current run -- the one label nobody can afford to
    lose. This recomputes where every label lands and asserts the separation,
    rather than trusting the offsets to be right by inspection: two earlier
    attempts looked correct in the source and still overlapped on screen, one
    of them because plotly's `ay` runs the opposite way to the guess.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    from streamlit_source import load_from_app

    # Two names, so load_from_app returns the whole namespace -- with one it
    # returns the function alone and the constants are unreachable.
    ns = load_from_app(APP_DIR / "app.py", "label_offsets", "span_label",
                       consts=("CHART_PX", "PLOT_PX", "LABEL_PX"))
    label_offsets, PLOT_PX, LABEL_PX = (ns["label_offsets"], ns["PLOT_PX"],
                                        ns["LABEL_PX"])
    runs = summary["overlay"]
    ys = [v for r in runs for v in r["y"]]
    xs = [v for r in runs for v in r["x"]]
    y_span, x_span = max(ys) - min(ys), max(xs) - min(xs)
    offsets = label_offsets(runs, y_span, x_span)
    assert len(offsets) == len(runs)

    px_per_unit = PLOT_PX / (y_span * 1.1)
    x_tol = x_span * 0.09
    placed = [(r["x"][-1], -r["y"][-1] * px_per_unit + offsets[id(r)], r["label"])
              for r in runs]
    for i, (xa, ya, la) in enumerate(placed):
        for xb, yb, lb in placed[i + 1:]:
            if abs(xa - xb) <= x_tol:
                assert abs(ya - yb) >= LABEL_PX - 1, (
                    f"{la} and {lb} land {abs(ya - yb):.0f}px apart, "
                    f"closer than the {LABEL_PX}px a label needs")


def test_label_decluttering_leaves_isolated_runs_alone(summary):
    """A run with nothing near it keeps its label on its own endpoint. An
    offset applied to everything would scatter twelve labels to fix two."""
    sys.path.insert(0, str(ROOT / "tests"))
    from streamlit_source import load_from_app

    label_offsets = load_from_app(
        APP_DIR / "app.py", "label_offsets", "span_label",
        consts=("CHART_PX", "PLOT_PX", "LABEL_PX"))["label_offsets"]
    runs = summary["overlay"]
    ys = [v for r in runs for v in r["y"]]
    xs = [v for r in runs for v in r["x"]]
    offsets = label_offsets(runs, max(ys) - min(ys), max(xs) - min(xs))
    assert sum(1 for v in offsets.values() if v == 0) > len(runs) // 2


def test_the_basis_word_is_never_typed_into_a_rendered_string(page_src):
    """"Real" and "nominal" must be DERIVED from the toggle, never written out.

    Every one of these shipped in the first cut and was found by clicking
    Nominal: a heading reading "Real cattle price", a caption reading "the real
    high is $254", and two tiles reading "median move +92% real" — each a label
    contradicting the figure directly beneath it, which is the one thing the
    standing headline rule forbids. The toggle is the only place those words
    may come from.
    """
    tree = ast.parse(page_src)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        rendering = (isinstance(f, ast.Name) and f.id == "tile") or (
            isinstance(f, ast.Attribute) and f.attr in ("caption", "subheader", "html"))
        if not rendering:
            continue
        text = " ".join(
            c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        ).lower()
        derived = any(
            isinstance(n, ast.Name) and n.id == "basis_word" for n in ast.walk(node))
        for word in ("real", "nominal"):
            if f" {word}" in f" {text}" and not derived:
                bad.append((node.lineno, word, text[:70]))
    assert not bad, bad


def test_no_price_level_is_written_into_prose(page_src):
    """A caption that states where the series sits goes stale against the chart
    above it. CLAUDE.md records exactly this for the southeast retention panel:
    read the figure off the data at render time."""
    tree = ast.parse(page_src)
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("caption", "subheader")):
            continue
        for c in ast.walk(node):
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                for i, ch in enumerate(c.value):
                    if ch == "$" and c.value[i + 1:i + 2].isdigit():
                        bad.append((node.lineno, c.value[i:i + 20]))
    assert not bad, bad


def test_captions_quoting_two_prices_are_escaped(page_src):
    """A pair of unescaped dollar signs opens an inline LaTeX span."""
    tree = ast.parse(page_src)
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "caption"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        wrapped = (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                   and arg.func.id == "money_md")
        literal = "".join(
            v.value for v in ast.walk(arg)
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
        if literal.count("$") >= 2 and not wrapped:
            bad.append((node.lineno, literal[:70]))
    assert not bad, bad


# -- the cached loader --------------------------------------------------------

def test_the_cached_loader_keys_on_schema_and_is_handed_it(page_src):
    """Both halves. A leading underscore asks Streamlit to drop the argument from
    the key; a default alone is never hashed, because st.cache_data hashes what
    the function is CALLED with."""
    tree = ast.parse(page_src)
    guarded = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        cached = any(
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
             and d.func.attr in ("cache_data", "cache_resource"))
            or (isinstance(d, ast.Attribute) and d.attr in ("cache_data", "cache_resource"))
            for d in node.decorator_list
        )
        if not cached:
            continue
        params = [a.arg for a in node.args.posonlyargs + node.args.args]
        assert not any(p.startswith("_") and "schema" in p for p in params), node.name
        assert "schema" in params, f"{node.name} must take the cache key as `schema`"
        guarded[node.name] = params.index("schema")

    assert guarded, "the page defines no cached loader -- did it move?"
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in guarded):
            pos = guarded[node.func.id]
            passed = len(node.args) > pos or any(k.arg == "schema" for k in node.keywords)
            assert passed, f"{node.func.id} called without schema at line {node.lineno}"


# -- registration -------------------------------------------------------------

def test_the_page_is_staff_only_and_unlisted():
    """TOOLS, not DASHBOARDS: a client should not learn the page exists."""
    home = (ROOT / "Home.py").read_text(encoding="utf-8-sig")
    tools = home[home.index("TOOLS = ["):home.index("_TILE_CSS")]
    assert "apps/cattle_cycles/app.py" in tools
    dash = home[home.index("DASHBOARDS = ["):home.index("TOOLS_PARAM")]
    assert "cattle_cycles" not in dash


def test_nothing_renders_above_the_gate(page_src):
    """`sys.path.insert` legitimately precedes the gate -- portal_auth cannot be
    imported without it. What must NOT precede it is anything that draws: a
    st.* call above require_admin renders to an unauthenticated visitor, and a
    CSS block above it paints the page chrome behind the login box."""
    tree = ast.parse(page_src)
    gate_line = next(
        (n.lineno for n in ast.walk(tree)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "require_admin"),
        None,
    )
    assert gate_line, "no require_admin call found"
    early = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "st"
        and n.lineno < gate_line
    ]
    assert not early, f"streamlit calls above the gate at lines {early}"


def test_the_page_sets_no_page_config(page_src):
    """Home.py makes the single call allowed for the whole multi-page run."""
    assert "set_page_config" not in page_src


# -- a known answer, so a refactor cannot move the numbers silently -----------

def test_the_shipped_numbers(summary):
    """Pinned against the committed seed. If the seed is regenerated these move,
    and they SHOULD -- update them deliberately rather than loosening the test."""
    ctx = summary["context"]
    assert summary["first"].strftime("%Y-%m") == "1913-01"
    assert len(summary["trough_to_trough"]) == 13
    assert ctx["kind"] == "bull"
    assert ctx["start"].strftime("%Y-%m") == "2020-07"
    assert ctx["rank_duration"] == 2
    assert len(ctx["still_running_at_age"]) == 1
    assert ctx["provisional"] and ctx["provisional"][0]["date"].strftime("%Y-%m") == "2026-06"
    import numpy as np
    assert 7.0 < float(np.median(summary["trough_to_trough"])) / 12 < 7.8


# -- the herd cycle -----------------------------------------------------------
#
# A SECOND CLOCK. These guard the inventory view, which dates peak-to-trough
# liquidations in January 1 head. It must never be confused with the price
# dating above it: the two run roughly inverse and on different periods, and
# a figure from one set beside a figure from the other would be the
# letter-versus-dashboard failure this repo records five times.


@pytest.fixture(scope="module")
def herd(seed):
    return cycles.herd_summary(seed)


def test_the_seed_carries_both_inventory_series(seed):
    assert set(seed["inventory"]) == set(cycles.INVENTORY)
    for key, block in seed["inventory"].items():
        assert block["period"] == "FIRST OF JAN"
        assert block["unit"] == "head"
        assert block["short_desc"].startswith("CATTLE,")
        assert block["short_desc"].endswith("- INVENTORY")


def test_beef_cows_leads_not_all_cattle():
    """The productive base, not the headline count. All cattle and calves
    carries feeders that exist because of breeding decisions already made, so
    a liquidation there is the echo rather than the cycle."""
    assert cycles.DEFAULT_INVENTORY == "beef_cows"


def test_inventory_is_indexed_by_year_not_by_date(herd):
    """A Jan 1 count given a timestamp invites someone to line it up against
    the monthly price series and difference the two. The index type is the
    guard, so it is asserted rather than assumed."""
    idx = herd["series"].index
    assert all(isinstance(y, (int, np.integer)) for y in idx), idx.dtype
    assert 1920 <= int(idx[0]) and int(idx[-1]) >= 2025


def test_herd_turns_alternate(herd):
    kinds = [k for _y, k in herd["turns"]]
    assert len(kinds) > 6
    assert all(a != b for a, b in zip(kinds, kinds[1:])), kinds


def test_every_liquidation_is_actually_a_fall(herd):
    """peak -> trough only. An expansion appearing here would be a sign
    detection has picked the turns up in the wrong order."""
    assert herd["liquidations"]
    for q in herd["liquidations"]:
        assert q["drop"] < 0, q
        assert q["trough"] > q["peak"], q
        assert q["to"] < q["from"], q


def test_the_run_in_progress_is_excluded_from_its_own_peer_set(herd):
    """THE ONE THAT MATTERS MOST. January 2026 is the lowest year so far on
    both series, not a dated trough. Leaving that run in the peer set would
    have the current liquidation compared against itself, which flatters
    every median and rank on the panel."""
    ctx = herd["context"]
    assert ctx["provisional"] is True
    assert ctx["n_peers"] == len(herd["liquidations"]) - 1
    assert ctx["deeper"] <= ctx["n_peers"]
    assert ctx["longer"] <= ctx["n_peers"]


def test_a_trough_is_provisional_only_when_it_sits_near_the_end():
    """On a SYNTHETIC series, so the shape is controlled rather than inferred.

    Rise to a peak at year 10, fall to a trough at year 20, then rise again.
    With years to spare after it, that trough is dated. Cut the record two
    years past it and the same trough becomes provisional, because the window
    that found it no longer has years on both sides.

    An earlier version of this test truncated the REAL series instead and
    asserted the result was not provisional. That failed, and the test was
    wrong rather than the code: truncating a real series can create a fresh
    turn near its new end, so it was not measuring what it claimed to.
    """
    import pandas as pd
    shape = ([100 + i for i in range(11)]          # 1900..1910 up to a peak
             + [110 - i for i in range(1, 11)]     # 1911..1920 down to a trough
             + [100 + i for i in range(1, 11)]     # 1921..1930 up to a peak
             + [110 - i for i in range(1, 11)])    # 1931..1940 easing off again
    full = pd.Series({1900 + i: float(v) for i, v in enumerate(shape)})

    turns, prov = cycles.herd_turns(full)
    # 1900 is dropped: it is the max of a window with nothing on its left,
    # which is where the record begins rather than a peak. 1940 is KEPT --
    # it may be confirmed by the next reading.
    assert [y for y, _k in turns] == [1910, 1920, 1930, 1940], turns
    assert prov is True, "this record ends falling, so its low may be a bottom"

    # The same record cut where it is CLIMBING. A turn still lands on the last
    # year, but it is a peak, so there is no bottom to qualify.
    rising = full[full.index <= 1930]
    turns_r, prov_r = cycles.herd_turns(rising)
    assert turns_r[-1][1] == "P", turns_r
    assert prov_r is False, "a peak at the end is not an unconfirmed bottom"

    cut = full[full.index <= 1922]
    turns2, prov2 = cycles.herd_turns(cut)
    assert (1920, "T") in turns2, turns2


def test_overlay_runs_start_at_100_at_the_peak(herd):
    """Indexed at the PEAK, not the trough -- the quantity compared is the
    depth of a fall, so every line starts level and goes down. The price
    overlay indexes at the trough for the mirror reason."""
    runs = herd["overlay"]
    assert len(runs) > 4
    for r in runs:
        assert r["x"][0] == 0
        assert abs(r["y"][0] - 100.0) < 1e-9, r["label"]
        assert min(r["y"]) < 100.0, r["label"]
    assert sum(1 for r in runs if r["running"]) == 1
    # NO RUN APPEARS TWICE. The live one has a dated-looking provisional
    # trough, so it reached the chart both as a completed liquidation and as
    # the running one -- two lines for one market, the grey one asserting the
    # bottom the banner above it denies. Caught in a browser, by reading the
    # end-of-line labels and seeing 2019 on two of them.
    peaks = [r["peak"] for r in runs]
    assert len(peaks) == len(set(peaks)), peaks


def test_the_turn_window_changes_what_is_found(seed):
    """It is a control, not a constant, so the page exposes it."""
    counts = {w: len(cycles.herd_summary(seed, window=w)["liquidations"])
              for w in cycles.HERD_WINDOW_CHOICES}
    assert len(set(counts.values())) > 1, counts


def test_the_two_inventory_series_disagree_about_depth(seed):
    """Which is why the page offers both and always names the one it shows.
    Beef cows fall materially harder than the all-cattle headline."""
    import statistics as _st
    med = {}
    for key in cycles.INVENTORY:
        h = cycles.herd_summary(seed, key)
        med[key] = _st.median(q["drop"] for q in h["liquidations"])
    assert med["beef_cows"] < med["all_cattle"] - 0.03, med


def test_the_herd_numbers_on_the_page(herd):
    """Pinned against the committed seed. These move when the seed is
    regenerated and they SHOULD -- update them deliberately rather than
    loosening the assertions."""
    ctx = herd["context"]
    assert ctx["peak"] == 2019
    assert ctx["year"] == 2026
    assert ctx["years"] == 7
    assert -0.14 < ctx["drop"] < -0.11          # about -12.7%
    assert ctx["still_falling"] is True
    assert ctx["median_drop"] < ctx["drop"]      # the typical one went deeper
    assert ctx["n_peers"] == 5                   # 1934, 1955, 1975, 1982, 1996
    assert -0.19 < ctx["median_drop"] < -0.17    # about -18.0%
    assert ctx["deeper"] == 4                    # 4 of 5 fell further than this
