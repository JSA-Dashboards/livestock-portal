"""
US Beef Trade -- the traps that do not raise.

Three classes of thing are pinned here, and none of them would fail loudly on
its own:

  * the WASDE text parse, against the XML of the SAME release. The page reads
    the 24 KB text file because twenty-five releases of the 2 MB XML is 50 MB
    for two numbers apiece; the XML earns its keep here instead, as an
    independent oracle. A fixed-width parse that has silently shifted a column
    produces plausible numbers, and only a second parser catches it.
  * the ERS shaping, where `World total` is a ROW in the file. Summing every
    country double-counts the total exactly, and a doubled beef export figure
    is still a perfectly believable beef export figure.
  * the join between them -- that ERS and WASDE are the same series on the
    same basis. The whole page is an actual-against-forecast comparison, so if
    that stops being true the page is wrong rather than merely stale.

Fixtures are committed under tests/fixtures/beef_trade/ and are USDA's own
published files, trimmed to the table in question. They are US Government
works, so unlike the Sterling tracker there is nothing here that cannot sit in
a public repo.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "beef_trade"))

import trade_flows as tf      # noqa: E402
import wasde                  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "beef_trade"
WASDE_TXT = FIX / "wasde0926_meats.txt"
WASDE_XML = FIX / "wasde0926_sr32.xml"
ERS_CSV = FIX / "ers_beef_monthly_sample.csv"


# -- helpers -----------------------------------------------------------------

def _parsed():
    return wasde.parse(WASDE_TXT.read_text(encoding="utf-8"))


def _xml_truth():
    """
    {(commodity, year, month_label): {attribute: value}} straight out of the
    structured release -- the oracle the text parser is checked against.

    Deliberately a SEPARATE implementation, not a shared helper: a bug in one
    reader that the other inherits is not a check.
    """
    root = ET.fromstring(WASDE_XML.read_text(encoding="utf-8"))
    rep = root.find("Report") if root.tag != "Report" else root
    name_map = {
        "Beginning stocks": "beginning_stocks",
        "Production 1/": "production",
        "Imports": "imports",
        "Total Supply": "total_supply",
        "Exports": "exports",
        "Ending Stocks": "ending_stocks",
        "Total Use": "total_use",
    }
    out = {}
    for cg in rep.iter("m1_commodity_group"):
        # The XML carries the footnote marker on the commodity name --
        # "Total Red\r\nMeat 5/" -- and the text parser strips it. Strip it
        # here too, so the two are compared on the figures rather than on a
        # labelling convention neither claims to share.
        com = re.sub(r"\s*\d+\s*/\s*$", "",
                     " ".join((cg.get("m1_commodity1") or "").split()))
        for yg in cg.iter("m1_year_group"):
            label = (yg.get("m1_market_year1") or "").strip()
            year = int(label[:4])
            for mg in yg.iter("m1_month_group"):
                mon = (mg.get("m1_forecast_month1") or "").strip()
                vals = {}
                for ag in mg.iter("m1_attribute_group"):
                    attr = " ".join((ag.get("m1_attribute1") or "").split())
                    key = name_map.get(attr)
                    if key is None:
                        continue
                    cell = ag.find(".//Cell")
                    if cell is None:
                        continue
                    raw = (cell.get("m1_cell_value1") or "").replace(",", "")
                    try:
                        vals[key] = float(raw)
                    except ValueError:
                        pass
                out[(com, year, mon)] = vals
    return out


def _ers_frame():
    df = pd.read_csv(ERS_CSV, encoding="utf-8-sig")
    out = pd.DataFrame({
        "flow": df["TRADE_FLOW"].astype(str).str.strip(),
        "country": df["GEOGRAPHY_DESC"].astype(str).str.strip(),
        "year": df["YEAR_ID"].astype(int),
        "month": df["TIMEPERIOD_ID"].astype(int),
        "mil_lb": pd.to_numeric(df["AMOUNT"], errors="coerce")
        * tf.THOUSAND_LB_TO_MILLION_LB,
    }).dropna(subset=["mil_lb"])
    return out[out["flow"].isin(tf.FLOWS)].reset_index(drop=True)


# -- the WASDE text parser, against the XML ---------------------------------

def test_text_parse_matches_the_xml_figure_for_figure():
    """
    THE CHECK THAT LICENSES READING THE TEXT FILE AT ALL.

    Every commodity, every year, every attribute. A shifted column survives
    _row_ok only if it happens to preserve both accounting identities, which
    is why this exists on top of them.
    """
    truth = _xml_truth()
    got = _parsed()
    assert got.series, "parsed nothing"

    checked = 0
    for s in got.series:
        for month_label, vals in ((s.current_month, s.current),
                                  (s.prior_month, s.prior)):
            if not vals:
                continue
            key = (s.commodity, s.year, month_label or "")
            assert key in truth, f"text parse invented {key}"
            for attr, value in vals.items():
                if attr == "per_capita":
                    continue
                assert truth[key].get(attr) == pytest.approx(value), (
                    f"{key} {attr}: text {value} vs xml {truth[key].get(attr)}")
                checked += 1
    assert checked >= 100, f"only {checked} figures compared"


def test_every_parsed_row_satisfies_both_accounting_identities():
    """
    beginning + production + imports == total supply, and
    total supply - exports - ending stocks == total use.

    _collect already refuses a row that fails, so this is really asserting
    that refusal has not been loosened into uselessness -- and that the
    fixture's rows all pass, i.e. the guard is not silently dropping real data.
    """
    got = _parsed()
    rows = [v for s in got.series for v in (s.current, s.prior) if v]
    assert len(rows) >= 15
    for v in rows:
        assert wasde._row_ok(v)


def test_a_shifted_column_is_refused():
    """
    The failure the identities exist for: a layout change that moves every
    figure one column left. The numbers stay individually plausible.
    """
    line = "    2025             602   26071    5388   32061    2579     577   28905    59.2"
    # _collect never sees the year -- _YEAR_ROW has already taken it -- so go
    # through the real regex rather than hand-feeding a tail that does not
    # match what production passes.
    tail = wasde._YEAR_ROW.match(line).group(3)
    good = wasde._collect(tail)
    assert good["imports"] == 5388.0 and good["exports"] == 2579.0

    # One column dropped from the right: eight figures become seven, the
    # per-capita slot swallows total use, and every remaining number is still
    # a believable beef figure.
    short = " ".join(tail.split()[:-1])
    assert wasde._collect(short) == {}, "a row one column short was accepted"

    # One column dropped from the LEFT, which is the nastier shape: the count
    # is restored by the per-capita figure sliding into total use, so only the
    # accounting identities can reject it.
    slid = " ".join(tail.split()[1:] + ["0.0"])
    assert len(slid.split()) == len(wasde.COLUMNS)
    assert wasde._collect(slid) == {}, "a left-shifted row was accepted"


def test_commodity_names_split_across_lines_are_rejoined():
    """
    The report wraps a long name: "TotalRed" / "Meat5/" and "Total" /
    "Poultry6/". Getting this wrong attaches Total Red Meat's figures to a
    commodity called "TotalRed" and loses them -- no error, just a key nobody
    looks up.
    """
    got = _parsed()
    assert "Total Red Meat" in got.commodities()
    assert "Total Poultry" in got.commodities()
    # "RedMeat& Poultry" is complete on ONE line and carries no trailing
    # padding, which is why the join cannot be decided on padding.
    assert "Red Meat & Poultry" in got.commodities()
    assert "Beef" in got.commodities()


def test_default_year_is_the_earliest_forecast_not_the_latest():
    """
    WASDE carries the following marketing year from May onward. Defaulting to
    the latest would switch the page's headline mid-season, from the year
    being revised to one nobody is trading yet.
    """
    got = _parsed()
    beef = got.get("Beef")
    assert beef.year == 2026 and beef.status == "Proj."
    assert 2027 in got.years("Beef")


def test_revision_comes_from_the_prior_month_row_in_the_same_file():
    """
    Each release prints last month's estimate beside this month's, so the
    month-over-month revision needs no stored history and no second request.
    """
    got = _parsed()
    beef = got.get("Beef")
    assert (beef.current_month, beef.prior_month) == ("Sep", "Aug")
    assert got.value("Beef", "imports") == 6262.0
    assert got.revision("Beef", "imports") == pytest.approx(130.0)
    assert got.revision("Beef", "exports") == pytest.approx(10.0)


def test_revision_is_none_and_not_zero_when_there_is_nothing_to_compare():
    """
    An actual year has no prior-month row. Zero would say "USDA did not
    revise this", which is a different statement from "there is no comparison".
    """
    got = _parsed()
    assert got.value("Beef", "imports", 2025) == 5388.0
    assert got.revision("Beef", "imports", 2025) is None


def test_the_table_header_is_not_read_as_data():
    """
    The meats table opens with a rule of "=", four lines of column headings,
    then a second rule. Starting at the first rule reads the headings as rows;
    treating the second as the END closes the table before Beef's first line
    and the parse returns a report month and no commodities -- which looks
    like a report that has stopped publishing rather than a parser bug. It
    cost one debugging round on 2026-10-07.
    """
    got = _parsed()
    assert got.report_month == "September 2026"
    assert len(got.commodities()) == 7


# -- the ERS shaping ---------------------------------------------------------

def test_world_total_is_a_row_and_the_countries_sum_to_it():
    """
    THE DOUBLE-COUNT. `World total` is published in the same column as the
    partners, so a groupby that forgets to exclude it returns exactly twice
    the real figure -- and twice a beef export month is still a number that
    looks like a beef export month.
    """
    df = _ers_frame()
    rec = tf.reconciles(df)
    assert rec["ok"], rec
    assert rec["checked"] > 0

    naive = df[df["flow"] == "Exports"].groupby(["year", "month"])["mil_lb"].sum()
    correct = tf.monthly(df, "Exports").set_index(["year", "month"])["mil_lb"]
    joined = pd.concat([naive.rename("naive"), correct.rename("ok")],
                       axis=1).dropna()
    assert (joined["naive"] / joined["ok"]).round(6).eq(2.0).all(), (
        "the naive sum is meant to be exactly double; if it is not, the "
        "fixture no longer exercises the trap")


def test_monthly_reads_usdas_published_total_not_a_sum_of_partners():
    df = _ers_frame()
    m = tf.monthly(df, "Imports")
    direct = (df[(df["flow"] == "Imports") & (df["country"] == tf.WORLD)]
              .set_index(["year", "month"])["mil_lb"])
    for _, row in m.iterrows():
        assert direct[(row["year"], row["month"])] == pytest.approx(
            row["mil_lb"])


def test_country_tables_exclude_the_world_total_row():
    """
    Left in, it is the first row of every "top sources" table, at 100% share.
    """
    df = _ers_frame()
    for flow in tf.FLOWS:
        c = tf.countries(df, flow, 2025, 12, top=20)
        assert tf.WORLD not in set(c["country"])


def test_seasonal_projection_is_not_a_straight_annualisation():
    """
    Beef imports run heavy in the first quarter, so YTD x 12/n reads high all
    spring. The projection scales YTD by the share of the year those months
    normally carry instead, and the two must differ.
    """
    df = _ers_frame()
    p = tf.pace(df, "Imports", 2026, 6, forecast=6262.0)
    naive = p["ytd"] * 12.0 / 6.0
    assert p["projection"] is not None
    assert abs(p["projection"] - naive) > 1.0, (
        "the projection collapsed to a straight annualisation")
    shape = tf.seasonal_shape(df, "Imports", 2026)
    assert shape.sum() == pytest.approx(1.0, abs=1e-6)


def test_seasonal_shape_uses_only_complete_years():
    """
    A part year's monthly shares would sum to one over the months it happens
    to have, silently re-weighting every other month.
    """
    df = _ers_frame()
    shape = tf.seasonal_shape(df, "Imports", 2026)
    assert len(shape) == 12
    assert shape.sum() == pytest.approx(1.0, abs=1e-6)


def test_pace_returns_none_rather_than_guessing_without_a_forecast():
    df = _ers_frame()
    p = tf.pace(df, "Exports", 2026, 8, forecast=None)
    assert p["ytd"] is not None
    assert p["required"] is None and p["implied_vs_forecast"] is None


def test_net_trade_is_imports_less_exports():
    df = _ers_frame()
    nt = tf.net_trade(df)
    assert not nt.empty
    assert (nt["net"] - (nt["imports"] - nt["exports"])).abs().max() < 1e-9


# -- the join: ERS and WASDE are the same series -----------------------------

def test_ers_reproduces_the_wasde_actual_for_the_completed_year():
    """
    THE CLAIM THE WHOLE PAGE RESTS ON. WASDE's 2025 beef line is Imports 5,388
    and Exports 2,579; ERS's 2025 world totals are 5,387.95 and 2,579.08.

    If this ever fails, the actual-versus-forecast panels are comparing two
    different series and the page is wrong rather than stale -- which is why
    the page runs the same check live, in `basis_agrees`, instead of trusting
    this test to still describe production.
    """
    df = _ers_frame()
    w = _parsed()
    chk = tf.basis_agrees(df, 2025,
                          w.value("Beef", "imports", 2025),
                          w.value("Beef", "exports", 2025))
    assert chk["ok"] is True, chk
    assert chk["ers_imports"] == pytest.approx(5388.0, abs=tf_tolerance())
    assert chk["ers_exports"] == pytest.approx(2579.0, abs=tf_tolerance())


def tf_tolerance():
    """WASDE prints whole million pounds; ERS carries decimals."""
    return 2.0


def test_basis_check_declines_to_judge_an_incomplete_year():
    """
    Eight months of ERS against a full-year WASDE actual would always look
    like a divergence. `ok` is None -- not False -- so the page can say
    "nothing to check" rather than crying wolf every January.
    """
    df = _ers_frame()
    chk = tf.basis_agrees(df, 2026, 6262.0, 2343.0)
    assert chk["ok"] is None


def test_basis_check_fails_loudly_when_the_series_diverge():
    df = _ers_frame()
    chk = tf.basis_agrees(df, 2025, 9999.0, 2579.0)
    assert chk["ok"] is False


# -- module hygiene ----------------------------------------------------------

def test_wasde_module_is_generic_and_not_beef_specific():
    """
    It was written for this page and is meant to be reusable by the next one
    that wants a WASDE line. A hard-coded "Beef" anywhere in it is the first
    step back to a second WASDE reader -- the snowflake_db.py-times-five
    problem, which CLAUDE.md records at length.
    """
    src = (ROOT / "wasde.py").read_text(encoding="utf-8")
    body = "\n".join(
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("#"))
    # The docstring legitimately uses beef as the worked example; code must not.
    import ast
    tree = ast.parse(src)
    ast.get_docstring(tree)
    code = ast.unparse(ast.Module(
        body=[n for n in tree.body
              if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))],
        type_ignores=[]))
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "Beef" not in node.value, (
                f"wasde.py hard-codes a commodity: {node.value!r}")
    assert body  # the file is not empty


def test_both_modules_carry_a_cache_schema():
    """
    `st.cache_data` keys on the decorated function and never on the modules it
    calls, so adding a key to `load()` changes nothing on the deployed page and
    the section renders "-" with nothing raising. The trap is recorded for
    `leverage.SCHEMA` and `am_cutout.SCHEMA`; these are the third and fourth.
    """
    assert isinstance(wasde.SCHEMA, int)
    assert isinstance(tf.SCHEMA, int)
    page = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    assert "wasde.SCHEMA" in page and "tf.SCHEMA" in page


def test_the_page_is_registered_in_the_portal():
    home = (ROOT / "Home.py").read_text(encoding="utf-8")
    assert "apps/beef_trade/app.py" in home
    assert "beef-trade" in home


def test_the_tile_grid_never_strands_a_single_tile():
    """
    Thirteen dashboards at four per row is 4/4/4/1. The grid borrows one from
    the row above instead; this pins the arithmetic rather than the rendering.
    """
    per_row = 4
    for n in range(2, 40):
        rows = [list(range(i, min(i + per_row, n)))
                for i in range(0, n, per_row)]
        if len(rows) > 1 and len(rows[-1]) == 1:
            rows[-1].insert(0, rows[-2].pop())
        assert sum(len(r) for r in rows) == n
        assert all(len(r) >= 2 for r in rows), (n, [len(r) for r in rows])


# -- the annual chart's axis -------------------------------------------------

def test_the_annual_chart_axis_is_categorical():
    """
    THE FORECAST BAR THAT RENDERED NOWHERE. Plotly type-sniffs an axis, and
    "2014".."2025" are numeric strings, so the axis comes out LINEAR and
    "2026F" has no position on it. The bar is not dropped -- the trace is
    there, the legend entry draws, and the y-axis still stretches to fit the
    value -- so the only symptom is a chart with headroom and no bar.

    Asserted on the figure spec rather than by rendering, and the figure
    builder is split out of the page for exactly that reason.
    """
    import plotly.graph_objects as go

    df = _ers_frame()

    # Rebuilt here rather than imported, because importing app.py executes
    # Streamlit calls. The two must stay in step, which the next assertion
    # enforces by reading the page's own source.
    page = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    assert '"type": "category"' in page, (
        "annual_figure no longer forces a categorical x-axis; the WASDE "
        "forecast bar will silently stop rendering")

    m = tf.monthly(df, "Imports")
    complete = m.groupby("year")["month"].count()
    years = [int(y) for y in complete[complete == 12].index]
    assert years, "fixture has no complete years"

    fig = go.Figure()
    fig.add_trace(go.Bar(x=[str(y) for y in years], y=[1.0] * len(years)))
    fig.add_trace(go.Bar(x=["2026F"], y=[6262.0]))
    fig.update_layout(xaxis={"type": "category"})
    assert fig.layout.xaxis.type == "category"
    cats = [x for t in fig.data for x in t.x]
    assert "2026F" in cats and str(years[-1]) in cats


def test_net_run_is_computed_and_does_not_assert_a_crossover_year():
    """
    The caption under the net-trade chart said "the US crossed over durably in
    2024". The series says otherwise: the run starts in 2023, and the US was a
    net EXPORTER in 2021 and 2022. A caption that hard-codes a figure above it
    will disagree with it -- this repo has paid for that before -- so the page
    reads this off the data.
    """
    df = _ers_frame()
    run = tf.net_run(df)
    assert run["start"] == 2023
    assert run["years"] >= 3
    assert run["flipped"] >= 1, "the sign really has changed inside the fixture"
    assert run["first"] < run["latest"], "the scale claim must hold"

    # The years immediately before the run were net EXPORT years, which is the
    # specific fact the old caption got wrong.
    nt = tf.net_trade(df)
    complete = nt.groupby("year")["month"].count()
    annual = nt[nt["year"].isin(complete[complete == 12].index)] \
        .groupby("year")["net"].sum()
    assert annual[2021] < 0 and annual[2022] < 0


def test_net_run_counts_only_complete_years():
    """
    2026 is eight months in. Counting it would put a part year's net beside
    full ones and could start or break a run on half the evidence.
    """
    df = _ers_frame()
    run = tf.net_run(df)
    assert run["start"] + run["years"] - 1 == 2025


def test_the_wasde_year_is_a_calendar_year_and_ers_proves_it():
    """
    WASDE's grain tables are split MARKETING years -- corn 2026/27 runs
    September to August -- and the meats table in the same report is plain
    calendar years. Nothing in the file labels which is which.

    The proof is the join: ERS summed January to December 2025 reproduces
    WASDE's 2025 beef line exactly. If the meats year were split, a Jan-Dec
    sum could not land on it. So the page's whole year-to-date-against-
    forecast arithmetic rests on this, and it is worth a test of its own
    rather than being folded into the basis check.
    """
    df = _ers_frame()
    w = _parsed()
    m_i = tf.monthly(df, "Imports")
    jan_dec = m_i[(m_i["year"] == 2025) & (m_i["month"].between(1, 12))]
    assert len(jan_dec) == 12
    assert float(jan_dec["mil_lb"].sum()) == pytest.approx(
        w.value("Beef", "imports", 2025), abs=2.0)

    # A split year would shift the window, and it must NOT also reproduce the
    # figure -- otherwise the assertion above proves nothing.
    #
    # IT DISCRIMINATES ON PRECISION, NOT ON BEING WILDLY WRONG, and the first
    # version of this test got that backwards by demanding a 50 million lb
    # miss. A corn-style September-August window lands at 5,415.7 against
    # WASDE's 5,388 -- only 27.7 out, because US beef imports ran at a
    # similar rate through late 2024 and late 2025. Jan-Dec lands within
    # 0.05. That is a factor of about 500, which is conclusive, but a reader
    # who expects the wrong window to look obviously wrong will be surprised.
    prev = m_i[(m_i["year"] == 2024) & (m_i["month"] >= 9)]
    part = m_i[(m_i["year"] == 2025) & (m_i["month"] <= 8)]
    split = float(prev["mil_lb"].sum() + part["mil_lb"].sum())
    calendar_miss = abs(float(jan_dec["mil_lb"].sum())
                        - w.value("Beef", "imports", 2025))
    split_miss = abs(split - w.value("Beef", "imports", 2025))
    assert split_miss > 10.0, (
        "a September-August window reproduces the WASDE figure too; this "
        "test no longer establishes which window USDA used")
    assert split_miss > calendar_miss * 100


def test_the_page_says_the_year_is_a_calendar_year():
    page = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    assert "calendar year" in page


# -- the forecast percentages ------------------------------------------------

def test_pct_returns_none_rather_than_zero_without_a_base():
    """
    "USDA is forecasting no change" and "there is nothing to compare against"
    are different answers. A 0.0% merges them, and the panel would print a
    confident "+0.0%" where it has nothing. Same rule as Wasde.revision.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_bt_page", ROOT / "apps" / "beef_trade" / "app.py")
    assert spec is not None

    # app.py runs Streamlit at import, so the helpers are exercised through a
    # local re-definition check instead: assert they exist and are pure.
    src = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    assert "def pct(new, base):" in src
    assert "def delta_pair(" in src

    ns = {}
    body = src[src.index("def pct(new, base):"):src.index("def delta_pair(")]
    exec(body, ns)                                      # noqa: S102
    pct = ns["pct"]
    assert pct(110.0, 100.0) == pytest.approx(10.0)
    assert pct(90.0, 100.0) == pytest.approx(-10.0)
    assert pct(100.0, 100.0) == 0.0
    assert pct(100.0, 0) is None
    assert pct(100.0, None) is None
    assert pct(None, 100.0) is None


def test_the_wasde_panel_shows_the_forecast_change_as_a_percentage():
    """
    What change USDA is forecasting is the question the panel exists to
    answer, and it was previously answerable only by dividing two tiles in
    your head. The year-on-year move is now a tile value in its own right.
    """
    src = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    assert 'f"USDA {year} forecast vs {year - 1}"' in src
    assert 'f"{yoy:+,.1f}%"' in src
    # The month-over-month revision carries its percentage beside the absolute.
    assert "delta_pair(rev, rev_pct," in src
    # And the next calendar year is expressed against this one.
    assert "nxt_vs_now = pct(nxt_val, now)" in src


def test_the_forecast_percentages_are_right_for_the_fixture():
    """
    Arithmetic, against the figures the committed release actually carries:
    2026 imports 6,262 against 2025's 5,388 actual is +16.2%, and the
    month-over-month revision from August's 6,132 is +2.1%.
    """
    w = _parsed()
    now = w.value("Beef", "imports")
    base = w.value("Beef", "imports", 2025)
    prior = w.get("Beef").prior["imports"]
    nxt = w.value("Beef", "imports", 2027)

    assert (now / base - 1.0) * 100.0 == pytest.approx(16.22, abs=0.01)
    assert (now / prior - 1.0) * 100.0 == pytest.approx(2.12, abs=0.01)
    assert (nxt / now - 1.0) * 100.0 == pytest.approx(-3.39, abs=0.01)

    # Exports move the other way, which is the whole story of the page.
    e_now = w.value("Beef", "exports")
    e_base = w.value("Beef", "exports", 2025)
    assert (e_now / e_base - 1.0) * 100.0 == pytest.approx(-9.15, abs=0.01)


def test_delta_pair_does_not_wrap_a_percentage_in_parentheses():
    """
    IN USDA'S OWN REPORTS PARENTHESES MEAN NEGATIVE -- the trap
    letter/sterling.py and am_cutout both document, where (2.23) is a $2.23
    fall. A page of USDA figures that renders "130 (2.1%)" is read by exactly
    the audience most likely to take the 2.1% as a cut.

    Also pins that the arrow carries the sign and the figures after it do
    not, which the first version got wrong and printed "v -0.8%".
    """
    src = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("def delta_pair("):src.index("def fmt(")]
    ns = {}
    exec(body, ns)                                      # noqa: S102
    dp = ns["delta_pair"]

    def text(html):
        # The CSS class carries hyphens of its own ("tile-delta-neu"), so the
        # sign check has to look at the rendered text and not the markup.
        return re.sub(r"<[^>]+>", "", html).strip()

    both = text(dp(130.0, 2.12, " vs Aug"))
    assert "(" not in both and ")" not in both, both
    assert "130" in both and "2.1%" in both and "▲" in both

    down = text(dp(None, -0.77, " vs 2026"))
    assert "-" not in down, f"double negative: {down}"
    assert "▼" in down and "0.8%" in down

    assert "unchanged" in dp(0.0, 0.0, " vs Aug")
    assert "&mdash;" in dp(None, None)


# -- the quarterly tables (Cash Cattle Trade's WASDE panel) ------------------

QUARTERLY_TXT = FIX / "wasde0926_quarterly.txt"


def _prices():
    return wasde.parse_quarterly(
        QUARTERLY_TXT.read_text(encoding="utf-8"),
        wasde.QUARTERLY_PRICES_TITLE, wasde.QUARTERLY_PRICE_COLUMNS)


def test_annual_rows_sit_at_the_left_margin_like_a_year_heading():
    """
    THE ROWS THE PANEL ACTUALLY WANTS. Quarter rows are indented ("     III*")
    and the annual rows are NOT -- "AugProj." and "SepProj." start at column
    zero, exactly like a year heading. The first version of the period regex
    required leading whitespace, so every annual row was dropped: the table
    parsed, all four quarters were right, and `annual()` returned None with
    nothing raising.
    """
    q = _prices()
    periods = {(r.year, r.period) for r in q.rows}
    assert (2026, "AugProj.") in periods
    assert (2026, "SepProj.") in periods
    assert (2025, "Annual") in periods


def test_the_steer_forecast_and_its_revision():
    q = _prices()
    annual, is_fc = q.annual("steer", 2026)
    assert is_fc is True
    assert annual == pytest.approx(237.35)
    assert q.prior_annual("steer", 2026) == pytest.approx(245.35)
    # USDA cut the 2026 forecast $8.00/cwt in one month.
    assert annual - q.prior_annual("steer", 2026) == pytest.approx(-8.00)
    # A completed year reads its "Annual" row and is not a forecast.
    assert q.annual("steer", 2025) == (pytest.approx(224.37), False)


def test_the_annual_equals_the_mean_of_its_four_quarters():
    """
    THE ONLY AUDIT A PRICE TABLE OFFERS. The meats table has two accounting
    identities; this one has none, so a shifted column would be invisible
    from the row alone. USDA's footnote says the annual is a simple average
    of months and each quarter is three months, so the two are the same
    arithmetic: 237.3525 against a printed 237.35.
    """
    q = _prices()
    audit = q.reconciles("steer", 2026)
    assert audit["ok"] is True, audit
    assert audit["mean"] == pytest.approx(237.3525)
    assert audit["quarters"] == 4


def test_the_audit_declines_to_judge_a_part_published_year():
    """
    2027 has two quarters published, which is every forecast year before the
    following May. `ok` is None -- not False -- so the page can stay quiet
    instead of crying wolf for eight months of every year.
    """
    q = _prices()
    assert q.reconciles("steer", 2027)["ok"] is None
    assert q.reconciles("steer", 2025)["ok"] is None


def test_quarter_number_is_a_map_and_not_the_length_of_the_numeral():
    """
    The obvious shortcut -- len("III") == 3 -- is right for I, II and III and
    calls IV Q2. It shipped for about ten minutes and labelled the last two
    quarters of the year "Q3 proj" and "Q2 proj".
    """
    assert [wasde.quarter_number(r) for r in ("I", "II", "III", "IV")] == [1, 2, 3, 4]
    assert wasde.quarter_number("Annual") is None
    assert wasde.quarter_number("SepProj.") is None


def test_quarters_are_marked_actual_or_projected_by_the_printed_asterisk():
    """
    USDA prints "III*" for a projection and "I" for a settled quarter. The
    panel says which is which, so the asterisk has to survive the parse.
    """
    q = _prices()
    by_period = {r.period: r for r in q.quarters(2026)}
    assert by_period["I"].projected is False
    assert by_period["II"].projected is False
    assert by_period["III"].projected is True
    assert by_period["IV"].projected is True


def test_two_tables_on_one_printed_page_are_found_separately():
    """
    Production and prices both sit on WASDE page 31, so the prices table has
    no page header above it and the month has to come from elsewhere in the
    document. Finding tables by title rather than by page is what keeps them
    apart at all.
    """
    txt = QUARTERLY_TXT.read_text(encoding="utf-8")
    prices = _prices()
    prod = wasde.parse_quarterly(txt, wasde.QUARTERLY_PRODUCTION_TITLE,
                                 wasde.QUARTERLY_PRODUCTION_COLUMNS)
    assert prices.report_month == "September 2026"
    assert prod.report_month == "September 2026"
    # Different tables, different numbers: a steer price is not a production
    # figure, so a mix-up would be obvious here and nowhere else.
    assert prices.annual("steer", 2026)[0] == pytest.approx(237.35)
    assert prod.annual("beef", 2026)[0] == pytest.approx(24877)


def test_wasde_prints_beef_production_twice_and_they_differ():
    """
    A TRAP FOR THE NEXT PAGE THAT WANTS THIS. The quarterly table says 24,877
    for 2026 and the supply-and-use table says 24,945. The gap is farm
    production -- 68 million lb, the same in both years on file. Two portal
    pages reading different tables would quote different beef production and
    both be right, which is the letter-versus-dashboard failure CLAUDE.md
    records twice.
    """
    txt = QUARTERLY_TXT.read_text(encoding="utf-8")
    prod = wasde.parse_quarterly(txt, wasde.QUARTERLY_PRODUCTION_TITLE,
                                 wasde.QUARTERLY_PRODUCTION_COLUMNS)
    meats = _parsed()
    commercial = prod.annual("beef", 2026)[0]
    including_farm = meats.value("Beef", "production")
    assert including_farm - commercial == pytest.approx(68, abs=1)

    commercial_25 = prod.annual("beef", 2025)[0]
    including_farm_25 = meats.value("Beef", "production", 2025)
    assert including_farm_25 - commercial_25 == pytest.approx(68, abs=1)


def test_cash_trade_imports_the_shared_wasde_and_does_not_copy_it():
    """
    `wasde.py` exists ONCE, at the repo root. Python caches modules by name,
    so a second copy under an app directory would mean whichever page loaded
    first decided which one every other page got -- the snowflake_db-times-
    five problem, which CLAUDE.md documents at length and which this module
    was written to avoid rather than to join.
    """
    copies = sorted(pth.relative_to(ROOT).as_posix()
                    for pth in ROOT.rglob("wasde.py")
                    if "__pycache__" not in pth.parts)
    assert copies == ["wasde.py"], copies

    page = (ROOT / "apps" / "cash_trade" / "app.py").read_text(encoding="utf-8")
    assert "import wasde" in page
    assert "wasde.SCHEMA" in page, "the cached fetch must key on the schema"


def test_the_cash_trade_panel_renders_above_the_lmr_guard():
    """
    WASDE comes from ESMIS over a different host from LMR. Below the outage
    guard the whole panel would vanish on exactly the days a reader most
    wants a reference price -- the same four-line shape the Saturday
    Slaughter view and the morning cutout panel use.
    """
    page = (ROOT / "apps" / "cash_trade" / "app.py").read_text(encoding="utf-8")
    body = page[page.index("with tab_weekly:"):]
    call = body.index("wasde_steer_panel()")
    guard = body.index("if not load_ok:")
    assert call < guard, "the WASDE panel moved below the LMR outage guard"


def test_the_projection_tile_is_quoted_year_on_year_like_usdas_forecast():
    """
    THE PARALLEL IS THE POINT. The WASDE tile says USDA's 2026 import
    forecast is +16.2% on 2025; the projection tile says the actual pace is
    tracking +19.1% on the same base. Two percentages, one basis, one from
    USDA and one from the market -- the comparison the page exists to make,
    and it only holds if both are quoted the same way.

    It replaced a share of the forecast ("102.5% of USDA's 6,262"), which
    answered a question the caption underneath already answers in absolute
    terms and lined up with nothing else on the page.
    """
    src = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    assert "def projection_yoy_html(" in src
    assert "def share_html(" not in src, "the replaced helper is now dead code"
    assert 'projection_yoy_html(p["projection_yoy_pct"]' in src

    body = src[src.index("def projection_yoy_html("):src.index("def fmt(")]
    ns = {}
    exec(body, ns)                                      # noqa: S102
    render = ns["projection_yoy_html"]

    def text(markup):
        import html as _html
        return _html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()

    assert text(render(19.1, 2025, 5388.0)) == "▲ 19.1% vs 2025"
    assert text(render(-10.3, 2025, 2579.0)) == "▼ 10.3% vs 2025"
    assert "&mdash;" in render(None, 2025, 5388.0)
    assert "&mdash;" in render(19.1, 2025, None)
    assert "level with 2025" in render(0.0, 2025, 5388.0)


def test_the_projection_yoy_uses_the_full_prior_year_not_the_ytd_months():
    """
    `yoy_pct` compares like periods -- Jan-Aug against Jan-Aug. This one
    compares the projected FULL year against the completed one, which is
    what USDA's own forecast-versus-last-year percentage does. Putting a
    part-year comparison beside a full-year one under labels that look alike
    is the pairing this repo has been bitten by twice.
    """
    df = _ers_frame()
    p = tf.pace(df, "Imports", 2026, 8, 6262.0)
    assert p["prior_year_total"] == pytest.approx(5388.0, abs=1.0)
    assert p["projection_yoy_pct"] == pytest.approx(19.1, abs=0.2)

    # The two are genuinely different, so the distinction earns its keep:
    # Jan-Aug is +14.3%, the full-year projection +19.1%.
    assert p["yoy_pct"] == pytest.approx(14.3, abs=0.2)
    assert abs(p["projection_yoy_pct"] - p["yoy_pct"]) > 3.0

    # Derivable from the projection and the base, so the tile and the
    # caption underneath cannot drift apart.
    assert (p["projection"] / p["prior_year_total"] - 1.0) * 100.0 == \
        pytest.approx(p["projection_yoy_pct"])


def test_projection_yoy_is_none_until_the_prior_year_is_complete():
    """
    A projected full year against a part-year base would be a confident
    comparison of two different things.
    """
    df = _ers_frame()
    first = int(df["year"].min())
    p = tf.pace(df, "Imports", first, 8, 6000.0)
    assert p["prior_year_total"] is None
    assert p["projection_yoy_pct"] is None


def test_every_pace_tile_states_its_unit_and_rates_state_their_period():
    """
    535 beside a 6,262 forecast gives the reader no way to tell they are
    different kinds of number -- one is a year, the other a month -- and the
    gap reads as a collapse rather than a cadence. Flagged on the live page
    2026-10-07: the WASDE row had carried its units from the start and the
    four pace tiles had not.

    The two RATES must name the period as well as the unit; a bare
    "million lb" on a per-month figure is the same ambiguity one step on.
    """
    src = (ROOT / "apps" / "beef_trade" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("def pace_panel("):src.index("def monthly_chart(")]

    assert 'UNIT = "million lb"' in body
    assert 'RATE = "million lb per month"' in body

    # All four tiles carry one or the other.
    assert body.count("{UNIT} ·") + body.count("{RATE} ·") >= 4

    # The two rate tiles are the per-month ones, and they use RATE not UNIT.
    recent = body[body.index('"Recent monthly pace"'):]
    assert "{RATE} · average of the last 3 months" in recent[:300]
    needed = body[body.index('"Monthly pace needed"'):]
    assert "{RATE} · to reach USDA" in needed[:500]

    # And the two totals use UNIT, not RATE -- a year is not a rate.
    sofar = body[body.index("so far\", fmt(p[\"ytd\"])"):]
    assert "{UNIT} · Jan" in sofar[:300]
