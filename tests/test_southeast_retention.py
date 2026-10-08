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


def test_every_year_has_real_coverage():
    """A thin year is the failure that charts plausibly.

    2018 on the plains panel was three months at one barn and medianed to 1.61,
    which would have printed as the tallest bar on that chart. The same trap
    applies here, so months and barns are carried per row and checked.
    """
    for r in DATA["series"]:
        assert r["months"] >= southeast.MIN_MONTHS, r
        assert r["barns"] >= 3, r
        assert r["n"] >= 50, r


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
