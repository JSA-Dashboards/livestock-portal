"""
The southeastern long-history panel, and the things about it that fail quietly.

This series exists because the twelve plains markets on the US Cow Herd page
reported no bred cows to USDA before 2019 -- the legacy auction archive holds
zero Oklahoma, zero Missouri and zero Texas bred-cow rows across 2000-2019, so
their floor is permanent. Five southeastern barns did report throughout.

Everything here is about the shipped data file rather than the arithmetic,
because the arithmetic runs once in scripts/build_southeast_retention.py and
the page only reads its output. A bad file renders a perfectly plausible chart.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "us_cow_herd"))

import southeast  # noqa: E402

DATA = json.loads((ROOT / "apps" / "us_cow_herd" / "data"
                   / "southeast_retention.json").read_text(encoding="utf-8"))


def test_the_file_ships_and_loads():
    d = southeast.load()
    assert d is not None
    assert d["series"], "an empty series renders an empty chart, not an error"


def test_years_are_contiguous():
    """A missing year would draw as a gap the chart gives no reason for."""
    years = [r["year"] for r in DATA["series"]]
    assert years == sorted(years)
    assert years == list(range(years[0], years[-1] + 1)), f"gap in {years}"


def test_it_actually_reaches_the_years_it_exists_for():
    """The whole point is pre-2019. If the build silently lost the legacy half
    the chart still renders -- just starting at 2019, like the plains one."""
    years = [r["year"] for r in DATA["series"]]
    assert min(years) <= 2010, "this panel exists to reach 2010 and earlier"
    assert 2015 in years and 2011 in years


def test_the_panel_is_balanced_every_barn_in_every_year():
    """The invariant that failed silently the first time.

    The first version of this panel carried Athens GA, which reports no bred
    cows in 2010 or 2011, and Orangeburg SC, which all but stops after 2019 --
    22 sale-dates that year, then 2, 1, 1, none, none, 4. So 2011 stood on
    three barns and the whole modern half ran on four while the caption said
    five. Neither shows up in the chart: fewer barns still draws a bar, at a
    level set by whichever markets happened to report.
    """
    n = len(DATA["panel"])
    for r in DATA["series"]:
        assert r["barns"] == n, (
            f"{r['year']} has {r['barns']} of {n} barns -- the panel is not "
            f"balanced, so this year is measuring a different set of markets")


def test_every_year_has_real_coverage():
    """A thin year is the failure that charts plausibly.

    2018 on the plains panel was three months at one barn and medianed to 1.61,
    which would have printed as the tallest bar on that chart. The same trap
    applies here, so months and barns are carried per row and checked.
    """
    for r in DATA["series"]:
        assert r["months"] >= southeast.MIN_MONTHS, r
        assert r["n"] >= 150, r


def test_a_part_year_declares_its_months():
    """A ten-month bar beside twelve-month bars is a true number telling a
    false story; the label has to say so on its own."""
    for r in DATA["series"]:
        if r["months"] < 12:
            assert "span" in r and len(r["span"]) == 2, r
        else:
            assert "span" not in r, r
    assert southeast.span(DATA["series"]) in (None, tuple(DATA["series"][-1].get("span", []))) \
        or southeast.span(DATA["series"]) == DATA["series"][-1].get("span")


def test_ratios_are_in_a_sane_band():
    """Read naively the legacy archive mixes $/cwt and $/head bred prices with
    nothing distinguishing them, which computes to about 0.11 instead of 1.1 --
    a factor of ten that looks like a market collapse and charts fine."""
    for r in DATA["series"]:
        assert 0.5 < r["ratio"] < 3.0, r


def test_the_sources_are_labelled_and_hand_over_once():
    """2008-2018 is the legacy archive, 2019 on is MARS, and the handover
    happens exactly once. A second 'legacy' year after a 'mars' one would mean
    the build had mixed its sources."""
    seq = [r["source"] for r in DATA["series"]]
    assert set(seq) <= {"legacy", "mars", "both"}
    assert seq[0] == "legacy" and seq[-1] == "mars"
    # once it has left legacy it never returns
    first_mars = next(i for i, s in enumerate(seq) if s == "mars")
    assert all(s == "mars" for s in seq[first_mars:]), seq


def test_the_panel_is_named_and_is_not_the_plains_panel():
    """The caption names these barns because a reader who thinks they are the
    twelve markets above will compare two levels that must never be compared."""
    panel = DATA["panel"]
    assert len(panel) >= 5
    joined = " ".join(panel).lower()
    for plains in ("joplin", "woodward", "el reno", "ada", "billings", "salina"):
        assert plains not in joined, f"{plains} is a plains barn"
    assert all(b.split(", ")[-1] in {"GA", "SC", "NC", "TN", "KY"} for b in panel), panel


def test_baseline_is_this_panel_s_own_and_not_the_plains_figure():
    """The two panels sit about 0.25 apart and the offset is not stable before
    2019, so a shared 'normal' line would put one panel's baseline under the
    other's bars."""
    base = southeast.baseline(DATA["series"])
    assert base is not None
    yrs = {r["year"]: r["ratio"] for r in DATA["series"]}
    window = [yrs[y] for y in range(*southeast.BASELINE_YEARS) if y in yrs]
    assert window, "baseline window has no years in this series"
    assert min(window) - 0.01 <= base <= max(window) + 0.01


def test_the_generator_refuses_to_write_when_the_sources_overlap():
    """Concatenation is only legitimate because the two halves share no sale
    date. If USDA back-fills the archive, the build must stop rather than
    double-count the shared weeks into a median."""
    src = (ROOT / "scripts" / "build_southeast_retention.py").read_text(encoding="utf-8")
    assert "sys.exit(" in src and "overlap" in src
    i = src.index("if overlap:")
    assert "sys.exit(" in src[i:i + 600], "overlap is detected but not fatal"


# --- the droplet job -------------------------------------------------------

DEPLOY = ROOT / "deploy"
REFRESH = DEPLOY / "refresh_southeast.py"
WRAPPER = DEPLOY / "run_southeast_retention.sh"
INSTALLER = DEPLOY / "install_southeast_cron.sh"
FROZEN = ROOT / "apps" / "us_cow_herd" / "data" / "southeast_legacy.json"


def test_the_refresh_job_does_not_reimplement_the_archive_parse():
    """It reads the frozen legacy half; it must never re-derive it.

    The archive is 960MB of CSV and static. A second parser of it, running
    unattended on a droplet where nobody would see it drift, is the
    snowflake_db.py-times-five problem with no renderer to catch it -- and a
    job that recomputed the past weekly could quietly produce a different one.
    """
    import ast
    tree = ast.parse(REFRESH.read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert "zipfile" not in imported, "the refresh job is parsing the archive"
    assert "csv" not in imported, "the refresh job is parsing the archive"


def test_the_frozen_half_matches_the_panel_it_was_built_for():
    """A frozen file from a different barn set would merge into a series that
    is half one panel and half another, and still draw nineteen bars."""
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert set(frozen["panel"]) == set(frozen["slugs"]), "panel/slug maps disagree"
    assert set(frozen["handover"]) <= set(frozen["panel"]), "handover names a stranger"
    obs_barns = {o[0] for o in frozen["obs"]}
    assert obs_barns <= set(frozen["panel"]), f"observations from {obs_barns - set(frozen['panel'])}"
    assert sorted(frozen["panel"].values()) == sorted(DATA["panel"]), \
        "the frozen half was built for a different panel than the series ships"


def test_the_frozen_half_stops_at_every_barns_handover():
    """The legacy rows must already be filtered. If any survive past a barn's
    first MARS date the refresh job would merge a week the live feed also
    carries, double-counting that barn in the median."""
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    h = frozen["handover"]
    bad = [(b, d) for b, d, _ in frozen["obs"] if b in h and d >= h[b]]
    assert not bad, f"{len(bad)} legacy rows past the handover, e.g. {bad[:3]}"


def test_cron_calls_the_wrapper_and_never_python_directly():
    """The droplet keeps credentials in a .env FILE, not root's environment.
    A crontab line calling .venv/bin/python gets none of it, so the job would
    install cleanly and record nothing for ever. Sourcing .env is the whole
    reason the wrapper exists."""
    src = INSTALLER.read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if l.startswith("CRON_LINE="))
    assert "run_southeast_retention.sh" in line
    assert "/bin/python" not in line and "python3" not in line
    # The line invokes $ALERT, so check both halves: that the line goes
    # through it, and that it resolves to the host's alerting wrapper.
    assert "$ALERT" in line, (
        "this host has no MAILTO and no MTA -- a bare entry fails silently")
    alert = next(l for l in src.splitlines() if l.startswith("ALERT="))
    assert "cron-alert" in alert, alert
    assert 'if [ ! -x "$ALERT" ]' in src, (
        "a missing cron-alert must be a hard stop, not a warning")


def test_the_wrapper_handles_a_missing_flock_explicitly():
    """`if ! flock -n 9` reads as 'could not get the lock' when flock is simply
    absent: command-not-found is 127, ! makes it true, and the job exits 0
    having done nothing while looking healthy."""
    src = WRAPPER.read_text(encoding="utf-8")
    assert "command -v flock" in src
    i = src.index("cd \"$APP_DIR\"")
    assert i < src.index("mkdir -p"), "cd must come before anything is created"


def test_the_installer_verifies_the_crontab_it_wrote():
    """A sibling installer reported success on a host where nothing had been
    installed. The write is not the install."""
    src = INSTALLER.read_text(encoding="utf-8")
    assert "crontab -l" in src and "grep -cF" in src
    i = src.index("installed=$(crontab -l")
    assert "exit 1" in src[i:i + 900], "the read-back is not fatal"


# --- the expansion view ----------------------------------------------------

def test_expansion_scores_are_the_out_of_sample_ones():
    """The page must not quote 17/18.

    That is the in-sample score of a cut fitted on the same 18 years it is
    scored against, with one free parameter. Leave-one-out gives 15/18 against
    a null of 13/18 for saying 'contract' every year. Both numbers are carried
    so the caption can show the honest one and name the other as fitted.
    """
    sys.path.insert(0, str(ROOT / "apps" / "us_cow_herd"))
    import expansion
    s = expansion.SCORE
    assert s["out_of_sample"] < s["in_sample"], (
        "if these are equal the leave-one-out check was not actually run")
    assert s["null"] < s["out_of_sample"] <= s["n"]
    app = (ROOT / "apps" / "us_cow_herd" / "app.py").read_text(encoding="utf-8")
    assert "_s['out_of_sample']" in app, "the caption must quote the honest score"


def test_the_threshold_is_drawn_as_a_band_not_a_line():
    """A hairline would claim a precision the fit has not got: refitting the
    cut without each year moves it between 1.064 and 1.102."""
    import expansion
    lo, hi = expansion.CUT_BAND
    assert hi > lo, "a band with no width is a line"
    assert lo <= expansion.CUTS["ret"][0] <= hi, "the fitted cut sits outside its own band"
    app = (ROOT / "apps" / "us_cow_herd" / "app.py").read_text(encoding="utf-8")
    assert "add_hrect" in app and "CUT_BAND" in app


def test_the_expansion_view_does_not_use_a_second_y_axis():
    """The retention ratio sits near 1.0 and the two volume series near 40%.
    A secondary axis lets whoever picks the scales draw any relationship they
    like, so the view uses two frames instead."""
    app = (ROOT / "apps" / "us_cow_herd" / "app.py").read_text(encoding="utf-8")
    i = app.index('if _view == _EXP_VIEW:')
    j = app.index('elif _view == _SE_VIEW:', i)
    block = app[i:j]
    assert "yaxis2" not in block and "secondary_y" not in block
    assert block.count("st.plotly_chart") == 2, "expected two separate frames"


def test_a_year_with_no_count_yet_is_not_called_a_contraction():
    """None and False are different answers. The current year has no January
    count behind it, and colouring it as a contraction would assert one."""
    import expansion
    src = (ROOT / "apps" / "us_cow_herd" / "expansion.py").read_text(encoding="utf-8")
    assert '"expanded": None if grew is None else' in src
    app = (ROOT / "apps" / "us_cow_herd" / "app.py").read_text(encoding="utf-8")
    assert "_col = {True:" in app and "None:" in app, (
        "the open year needs its own colour, not the contraction one")
