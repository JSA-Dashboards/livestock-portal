"""Proof that the Mexican border year-end projection is arithmetic, not vibes.

The 2026 series below is verbatim AMS: every head count is one the border
report published, so a change in the pace rule fails here against real figures
rather than against a fixture that can be edited until it agrees.

Everything this pins is something that fails SILENTLY. A pace taken over the
wrong window, a projection counting weekends, or a denominator that quietly
drops the days nothing crossed all produce a plausible number on a tile with
nothing to show it is wrong.

    python -m pytest tests/test_border_pace.py -q
"""

import os
import pathlib
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (os.path.join(_HERE, "..", "apps", "mexican_feeder_imports"),
                   os.path.join(_HERE, "..")):
    if os.path.isfile(os.path.join(_candidate, "border.py")):
        sys.path.insert(0, _candidate)
        break
else:  # pragma: no cover
    raise RuntimeError("border.py not found next to app.py")

from border import (  # noqa: E402
    KNOWN_PORTS,
    year_outlook,
    NON_REPORTING,
    NORMAL_YEARS,
    PACE_WINDOW,
    WATCH_PORT,
    WATCH_PORT_EXPECTED,
    WATCH_PORT_EXPECTED_ON,
    cohort_at,
    curve_at,
    daily_pace,
    latest_restart,
    port_profile,
    project_year_end,
    ramp_weeks,
    reporting_days,
    watch_window,
)

# AMS daily border receipts, 2026, from the reopening of Douglas AZ on 24
# August through 1 October -- the grand-total row, as daily_receipts returns
# it. The week of 08-31 really is 100 head and four zeros; that near-dead week
# is what makes the window choice matter.
SERIES_2026 = [
    ("2026-08-24", 700), ("2026-08-25", 600), ("2026-08-26", 600),
    ("2026-08-27", 600), ("2026-08-28", 0),
    ("2026-08-31", 100), ("2026-09-01", 0), ("2026-09-02", 0),
    ("2026-09-03", 0), ("2026-09-04", 0),
    # 2026-09-07 is Labor Day -- AMS published nothing, so there is no row.
    ("2026-09-08", 800), ("2026-09-09", 900), ("2026-09-10", 900),
    ("2026-09-11", 800),
    ("2026-09-14", 900), ("2026-09-15", 900), ("2026-09-16", 950),
    ("2026-09-17", 1000), ("2026-09-18", 1050),
    ("2026-09-21", 1000), ("2026-09-22", 1000), ("2026-09-23", 1000),
    ("2026-09-24", 1500), ("2026-09-25", 1900),
    ("2026-09-28", 1350), ("2026-09-29", 600), ("2026-09-30", 1600),
    ("2026-10-01", 550),
]

TOTAL_2026 = 21_300


def test_fixture_matches_the_published_total():
    """Guards the fixture itself, so a typo in it cannot pass as a pace change."""
    assert sum(h for _d, h in SERIES_2026) == TOTAL_2026
    assert len(SERIES_2026) == 28


# ── reporting days ──────────────────────────────────────────────────────────

def test_reporting_days_skips_weekends():
    # Mon 5 Oct to Fri 9 Oct is five; extend over the weekend and it stays five.
    assert reporting_days(date(2026, 10, 5), date(2026, 10, 9)) == 5
    assert reporting_days(date(2026, 10, 5), date(2026, 10, 11)) == 5
    assert reporting_days(date(2026, 10, 3), date(2026, 10, 4)) == 0


def test_reporting_days_skips_holidays():
    """Columbus Day week is four days. A naive weekday count says five."""
    assert date(2026, 10, 12) in NON_REPORTING
    assert reporting_days(date(2026, 10, 12), date(2026, 10, 16)) == 4
    # Thanksgiving week: the Thursday goes, the Friday stays. AMS published on
    # the day after Thanksgiving in 2023, so it is not a non-reporting day.
    assert reporting_days(date(2026, 11, 23), date(2026, 11, 27)) == 4
    assert date(2026, 11, 27) not in NON_REPORTING


def test_reporting_days_is_inclusive_of_both_ends():
    assert reporting_days(date(2026, 10, 5), date(2026, 10, 5)) == 1


def test_rest_of_2026_is_sixty_one_reporting_days():
    """The denominator of the live projection. Four holidays fall in it."""
    assert reporting_days(date(2026, 10, 2), date(2026, 12, 31)) == 61


# ── pace ────────────────────────────────────────────────────────────────────

def test_pace_is_the_trailing_window_not_the_whole_span():
    """The distinction the whole design rests on.

    Averaged from the reopening the rate is 761 head/day; over the trailing
    fortnight it is 1,155. Those differ by a third and the projection built on
    the first one is 24,000 head lower.
    """
    assert daily_pace(SERIES_2026) == 1155.0
    whole_span = TOTAL_2026 / len(SERIES_2026)
    assert round(whole_span) == 761
    assert daily_pace(SERIES_2026) > whole_span * 1.4


def test_zero_crossing_days_stay_in_the_denominator():
    """A published zero is a reporting day on which nothing crossed.

    Drop them and the week of 08-31 -- one 100-head Monday and four zeros --
    reads as 100 head/day, faster than the fortnight that followed it.
    """
    ramp = SERIES_2026[:10]          # both opening weeks, five of them zero
    assert daily_pace(ramp, window=10) == 260.0
    nonzero = [(d, h) for d, h in ramp if h]
    assert sum(h for _d, h in nonzero) / len(nonzero) > 500


def test_pace_needs_a_full_window():
    assert daily_pace(SERIES_2026[-3:]) is None
    assert daily_pace([]) is None
    assert daily_pace(SERIES_2026, window=len(SERIES_2026) + 1) is None


def test_pace_window_is_two_whole_reporting_weeks():
    """Not a tuning knob: a non-multiple of five changes the day-of-week mix."""
    assert PACE_WINDOW == 10
    assert PACE_WINDOW % 5 == 0


def test_pace_does_not_depend_on_input_order():
    assert daily_pace(list(reversed(SERIES_2026))) == daily_pace(SERIES_2026)


# ── the projection ──────────────────────────────────────────────────────────

def test_projection_against_the_real_series():
    p = project_year_end(SERIES_2026, today=date(2026, 10, 2))
    assert p["crossed"] == TOTAL_2026
    assert p["pace"] == 1155.0
    assert p["days_left"] == 61
    assert p["through"] == "2026-10-01"
    assert p["projected"] == pytest.approx(91_755)
    assert p["projected"] == p["crossed"] + p["pace"] * p["days_left"]


def test_projection_counts_from_the_last_report_not_from_today():
    """The report lags. Counting from today drops the days in between.

    Run the same series on 9 October, a week after the last report: the days
    left must grow to cover 2 October onward, because cattle crossed on those
    days and the series has merely not caught up.
    """
    near = project_year_end(SERIES_2026, today=date(2026, 10, 2))
    late = project_year_end(SERIES_2026, today=date(2026, 10, 9))
    assert near["days_left"] == late["days_left"] == 61
    assert near["projected"] == late["projected"]


def test_projection_is_not_capped():
    """Unlike the quota tracker's, which clamps at the tranche limit.

    Nothing caps a border. A tenfold pace must give a tenfold projection, not
    a figure pinned to some notional ceiling.
    """
    hot = [(d, h * 10) for d, h in SERIES_2026]
    p = project_year_end(hot, today=date(2026, 10, 2))
    assert p["projected"] == pytest.approx(917_550)
    assert p["projected"] > 817_550              # above the whole of 2023


def test_projection_ignores_prior_years():
    """A 2025 row in the series must not land in the 2026 total."""
    with_prior = [("2025-07-10", 5_000)] + SERIES_2026
    p = project_year_end(with_prior, today=date(2026, 10, 2))
    assert p["crossed"] == TOTAL_2026


def test_projection_degrades_to_none_rather_than_guessing():
    assert project_year_end([]) is None
    assert project_year_end([("2026-10-01", 100)], today=date(2026, 10, 2)) is None
    assert project_year_end([("2025-03-01", 100)], today=date(2026, 10, 2)) is None


def test_projection_accepts_date_objects_as_well_as_labels():
    as_dates = [(date(*(int(x) for x in d.split("-"))), h) for d, h in SERIES_2026]
    assert (project_year_end(as_dates, today=date(2026, 10, 2))["projected"]
            == project_year_end(SERIES_2026, today=date(2026, 10, 2))["projected"])


def test_the_window_choice_actually_moves_the_answer():
    """If it did not, none of the reasoning above would be load-bearing."""
    wide = project_year_end(SERIES_2026, today=date(2026, 10, 2),
                            window=len(SERIES_2026))
    narrow = project_year_end(SERIES_2026, today=date(2026, 10, 2))
    assert narrow["projected"] - wide["projected"] > 20_000


# ── the watch port and its sensitivity ──────────────────────────────────────

def test_november_december_is_forty_one_reporting_days():
    """Thanksgiving and Christmas come out; the day after Thanksgiving does not.

    NO LONGER THE PAGE'S DENOMINATOR, and the docstring used to say it was.
    The watch-port note now sizes its window from the announced reopening --
    see the watch_window tests below -- so this pins reporting_days itself over
    a span the series has real coverage of, nothing more. A test whose
    docstring claims to guard a figure the page has stopped printing is the
    "test that holds a mistake in place" this repo already records.
    """
    assert reporting_days(date(2026, 11, 1), date(2026, 12, 31)) == 41


def test_black_friday_is_a_reporting_day_and_thanksgiving_is_not():
    """Read off 2023, the only Nov-Dec in this series the border ran through.

    AMS published on 2023-11-24, the day after Thanksgiving. 2024 looks like a
    counter-example and is not -- the border shut on 2024-11-25 and every
    weekday after it is missing, which is a closure rather than a holiday.
    """
    assert reporting_days(date(2026, 11, 26), date(2026, 11, 26)) == 0
    assert reporting_days(date(2026, 11, 27), date(2026, 11, 27)) == 1


def test_the_watch_window_starts_at_the_announced_reopening():
    """23 reporting days, not the 41 the Columbus note hard-coded.

    A crossing expected back on 30 November cannot carry cattle on the 18
    reporting days of November before it, and the same sentence that quotes
    the window says so. Priced at the restart rates the page uses, the
    difference is about 9,000 head on a 152,485 projection.
    """
    w = watch_window("2026-10-28", date(2026, 11, 30))
    assert w["days"] == 23
    assert w["start"] == "2026-11-30" and w["end"] == "2026-12-31"
    assert w["lapsed"] is False
    # the reopening day itself counts: all three 2026 reopenings carried cattle
    # on day one (Douglas 700, Santa Teresa 400, Columbus 650 head)
    assert reporting_days(date(2026, 12, 1), date(2026, 12, 31)) == 22


def test_the_watch_window_never_prices_days_that_have_already_passed():
    """The defect this function exists to stop, and the reason it takes `through`.

    Anchored on the announced date alone the window stays 23 all through
    December while the port stays shut -- adding head on days the projection
    has already counted as actual.
    """
    assert watch_window("2026-12-04", date(2026, 11, 30))["days"] == 18
    assert watch_window("2026-12-11", date(2026, 11, 30))["days"] == 13
    assert watch_window("2026-12-30", date(2026, 11, 30))["days"] == 1


def test_the_watch_window_is_a_subset_of_the_projections_own_days_left():
    """What licenses adding the increment to the projected box at all.

    If the window could ever exceed days_left the page would be projecting
    beyond the year it is projecting.
    """
    for through in ("2026-10-28", "2026-11-27", "2026-12-04", "2026-12-24"):
        series = SERIES_2026 + [(through, 1000)]
        proj = project_year_end(series, today=date(2026, 12, 31))
        assert watch_window(through, date(2026, 11, 30))["days"] <= proj["days_left"]


def test_an_expected_date_from_a_previous_year_prices_nothing():
    """The one state nothing reminds anybody about.

    WATCH_PORT_EXPECTED_ON is maintained by hand. Left at 30 November 2026 and
    read on 2027-02-01 with the port still shut, the window would otherwise be
    229 reporting days -- and the caption would read "expected back 30 November
    2026, which leaves 229 reporting days in 2027", pricing a hundred thousand
    head off a date fourteen months old.
    """
    w = watch_window("2027-02-01", date(2026, 11, 30))
    assert w["stale"] is True
    assert w["days"] == 0 and w["lapsed"] is True
    # the same constant one year on is ordinary, not stale
    fresh = watch_window("2027-02-01", date(2027, 11, 30))
    assert fresh["stale"] is False and fresh["days"] == 23


def test_a_date_that_has_passed_is_flagged_rather_than_ignored():
    """The window shrinks correctly either way; the SENTENCE has to change.

    "expected back 30 November 2026 - which leaves 18 reporting days from
    Dec 05" reads as though the date is still ahead.
    """
    assert watch_window("2026-10-28", date(2026, 11, 30))["overdue"] is False
    assert watch_window("2026-12-04", date(2026, 11, 30))["overdue"] is True
    assert watch_window("2026-11-30", date(2026, 11, 30))["overdue"] is True


def test_every_watch_port_state_renders_something():
    """A panel that disappears without saying why is the whole defect here.

    Four states rendered nothing: the date gone stale, no restart old enough to
    price from, the year's reporting days run out, and no expected date at all.
    Source-level because they are layout facts and there is no other way to
    assert a branch exists.
    """
    page = (pathlib.Path(__file__).resolve().parents[1]
            / "apps" / "mexican_feeder_imports" / "app.py"
            ).read_text(encoding="utf-8-sig")
    for branch in (
            'if _w and not _w["running"] and _nd and _rates:',
            'elif _w and not _w["running"] and (_win or {}).get("stale"):',
            'elif _w and not _w["running"] and _nd and not _rates:',
            'elif _w and not _w["running"] and (_win or {}).get("lapsed"):',
            'elif _w and not _w["running"] and not bd.WATCH_PORT_EXPECTED_ON:',
            'elif _w and _w["running"]:'):
        assert branch in page, f"missing branch: {branch}"


def test_the_page_multiplies_only_the_reporting_day_rate():
    """The silent 1.63x, pinned at the one place it could come back.

    per_day is head per day the crossing CARRIED cattle. Multiplied by a span
    of reporting days it reads 63% high for Nogales, and worse for the smaller
    intermittent crossings a reopening note is about. The only legitimate use
    of per_day on this page is the figure the caption names and rejects.
    """
    page = (pathlib.Path(__file__).resolve().parents[1]
            / "apps" / "mexican_feeder_imports" / "app.py"
            ).read_text(encoding="utf-8-sig")
    uses = [l.strip() for l in page.splitlines() if '_w["per_day"]' in l]
    assert uses, "the rejected figure should still be named on the page"
    for line in uses:
        assert line.startswith("_naive ="), (
            f"per_day must only feed the figure the caption rejects: {line}")
    assert "per_reporting_day" in page, (
        "the like-for-like rate has to be the one on the page")


def test_the_watch_window_lapses_rather_than_going_negative():
    w = watch_window("2026-12-31", date(2026, 11, 30))
    assert w["days"] == 0 and w["lapsed"] is True


def test_no_expected_date_prices_nothing():
    """"Expected back, no date" has to render no figure, not a figure of zero."""
    assert watch_window("2026-10-28", None) is None


def test_the_expected_date_and_the_prose_agree():
    """Two spellings of one expectation, and they drifted once already.

    WATCH_PORT_EXPECTED read "end of October 2026" while the page sized its
    window from a hard-coded 1 November. Only the date may feed a number, but
    the prose is what a reader sees, so they have to name the same month.
    """
    if WATCH_PORT_EXPECTED_ON is None:
        return
    assert WATCH_PORT_EXPECTED_ON.strftime("%B") in WATCH_PORT_EXPECTED
    assert str(WATCH_PORT_EXPECTED_ON.year) in WATCH_PORT_EXPECTED


def test_watch_port_names_a_crossing_ams_actually_reports():
    """A typo here does not raise -- it silently removes the note.

    port_profile() returns None for a crossing it cannot find, and the page
    reads None as "this port is open, say nothing". So a misspelt WATCH_PORT
    looks exactly like a reopened one.

    THIS TEST CHECKS SPELLING AND NOTHING ELSE, which is how the panel came to
    vanish unnoticed on 2026-10-26: Columbus reopened, WATCH_PORT still said
    "Columbus", the whole block stopped rendering and the suite stayed green.
    Whether the named crossing is still SHUT cannot be asserted here -- it is a
    fact about Snowflake, not about this module -- so the page now says so
    itself, and test_the_page_says_so_when_the_watch_port_reopens pins that.
    """
    if WATCH_PORT is None:
        return                       # cleared once the port reopens; fine
    cities = {p.split(",")[0].strip().upper() for p in KNOWN_PORTS}
    assert WATCH_PORT.upper() in cities
    assert WATCH_PORT_EXPECTED, "a watch port with no expected date says nothing"


def test_the_page_says_so_when_the_watch_port_reopens():
    """The block retiring itself is right; retiring silently is not.

    Source-level because it is a layout fact, and there is no other way to
    assert that a branch exists. What it stops coming back is three days of a
    page with a reopened crossing in WATCH_PORT, double-counted in the 2027
    scenarios, and no sign on the page that anything had changed.
    """
    page = (pathlib.Path(__file__).resolve().parents[1]
            / "apps" / "mexican_feeder_imports" / "app.py"
            ).read_text(encoding="utf-8-sig")
    assert 'if _w and not _w["running"]' in page
    assert 'elif _w and _w["running"]' in page, (
        "a watch port that has reopened must say so, not leave a hole")


def test_normal_years_exclude_the_closure_years():
    """2025 was three-quarters shut; a rate read from it is not a normal rate."""
    assert "2025" not in NORMAL_YEARS
    assert "2026" not in NORMAL_YEARS
    assert NORMAL_YEARS == ("2023", "2024")


class _Cur:
    """Returns canned rows in call order, which is all port_profile needs."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.sql = []

    def execute(self, sql):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return self._rows.pop(0)


class _Conn:
    def __init__(self, rows):
        self._cur = _Cur(rows)

    def cursor(self):
        return self._cur


def test_port_profile_arithmetic():
    """head/days is the rate WHILE OPEN, and share is against named-port head."""
    conn = _Conn([
        (261_600, 234),                   # the port, over the normal years
        (2_103_400,),                     # all named ports, same years
        (date(2025, 5, 12), "Arizona"),   # last seen, ever, and its state
        (0,),                             # rows this year -> not running
        (381,),                           # the border's own reporting days
    ])
    prof = port_profile(conn, "Nogales", this_year=2026)
    assert prof["head"] == 261_600
    assert prof["days"] == 234
    assert prof["per_day"] == pytest.approx(261_600 / 234)
    assert prof["share"] == pytest.approx(261_600 / 2_103_400)
    assert prof["state"] == "Arizona"
    # spelled the way the rest of the page spells a crossing
    assert prof["state_abbr"] == "AZ"
    assert prof["last_seen"] == "2025-05-12"
    assert prof["running"] is False


def test_per_day_and_per_reporting_day_are_different_units():
    """The silent 1.63x this page shipped, and the reason both keys exist.

    `days` counts only the days the crossing carried cattle -- Nogales had 234
    of the border's 381 reporting days across 2023-24 -- so per_day assumes a
    head every single day when it is multiplied by a span. The caption did
    exactly that: 1,118 x 23 where the truthful figure is 687 x 23.
    """
    conn = _Conn([(261_600, 234), (2_103_400,),
                  (date(2025, 5, 12), "Arizona"), (0,), (381,)])
    prof = port_profile(conn, "Nogales", this_year=2026)
    assert prof["per_day"] == pytest.approx(1_117.9, abs=0.1)
    assert prof["per_reporting_day"] == pytest.approx(686.6, abs=0.1)
    assert prof["per_day"] / prof["per_reporting_day"] == pytest.approx(1.63, abs=0.01)


def test_port_profile_knows_a_running_port():
    conn = _Conn([(315_550, 260), (2_103_400,),
                  (date(2026, 10, 1), "Arizona"), (22,), (381,)])
    assert port_profile(conn, "Douglas", this_year=2026)["running"] is True


def test_port_profile_is_none_for_a_crossing_with_no_history():
    """None rather than a zero rate: there is nothing to project from."""
    assert port_profile(_Conn([(None, 0)]), "Nowhere", this_year=2026) is None
    assert port_profile(_Conn([(0, 0)]), "Nowhere", this_year=2026) is None


# The six restarts this border has had, as cumulative head by elapsed
# reporting day -- the real figures, so the cohort arithmetic is pinned against
# what AMS published rather than against round numbers chosen to agree. Only
# the day-23 total matters to these tests, so the ladders are truncated there.
_RESTARTS = [
    {"port": "Nogales", "state": "Arizona", "from": "2025-02-19",
     "cum": [0] * 22 + [11_850]},
    {"port": "Douglas", "state": "Arizona", "from": "2025-02-06",
     "cum": [0] * 22 + [14_300]},
    {"port": "Douglas", "state": "Arizona", "from": "2026-08-24",
     "cum": [0] * 22 + [14_900]},
    {"port": "Santa Teresa", "state": "New Mexico", "from": "2025-02-05",
     "cum": [0] * 22 + [15_350]},
    {"port": "Presidio", "state": "Texas", "from": "2025-02-21",
     "cum": [0] * 22 + [16_050]},
    {"port": "Santa Teresa", "state": "New Mexico", "from": "2026-09-24",
     "cum": [0] * 22 + [16_800]},
    # three reporting days old: too young to answer a 23-day question
    {"port": "Columbus", "state": "New Mexico", "from": "2026-10-26",
     "cum": [650, 1_150, 1_550]},
]


def test_a_restart_too_young_for_the_window_answers_nothing():
    """The "across its first 3" problem, which shipped on the Columbus note.

    Three reporting days is not evidence about a twenty-three-day window, and
    once both are printed as "head a day" a reader cannot tell them apart.
    """
    young = latest_restart(_RESTARTS, "Columbus")
    assert curve_at(young, 23) is None
    assert curve_at(young, 3)["rate"] == pytest.approx(1_550 / 3)


def test_the_restart_cohort_is_measured_at_one_age():
    """515 to 730 head a reporting day, and Nogales' own is the slowest of them."""
    cohort = cohort_at(_RESTARTS, 23)
    assert [c["port"] for c in cohort] == [
        "Nogales", "Douglas", "Douglas", "Santa Teresa", "Presidio",
        "Santa Teresa"]
    assert cohort[0]["rate"] == pytest.approx(11_850 / 23)
    assert cohort[-1]["rate"] == pytest.approx(16_800 / 23)
    assert cohort_at(_RESTARTS, 23, exclude="Nogales")[0]["port"] == "Douglas"


def test_restarts_cluster_in_head_and_scatter_as_a_share_of_their_own_normal():
    """The measurement the whole pricing rests on, stated as arithmetic.

    A restart looks to be limited by what the crossing can process on the way
    back rather than by how big it used to be. Scaling the cohort by each
    port's own normal instead takes Santa Teresa's 24.9% -- low only because
    Santa Teresa is huge -- and lands Nogales at 278 head a day, below anything
    any crossing has managed coming back.
    """
    # port_profile(...)["per_day"] over NORMAL_YEARS, to a tenth
    normal = {"Nogales": 1_117.9, "Douglas": 1_214.4,
              "Santa Teresa": 2_454.7, "Presidio": 1_012.7}
    rates = [c["rate"] for c in cohort_at(_RESTARTS, 23)]
    shares = [c["rate"] / normal[c["port"]] for c in cohort_at(_RESTARTS, 23)]

    def _cv(v):
        m = sum(v) / len(v)
        return (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 / m

    assert _cv(rates) < 0.15
    assert _cv(shares) > 0.25
    # the ratio is the claim; the absolute above is only a sanity floor, and
    # pinning it at the measured 0.31 would make this brittle against an AMS
    # restatement rather than against the method changing
    assert _cv(shares) > 2 * _cv(rates)
    assert min(shares) * normal["Nogales"] < min(rates), (
        "the share route must land below every restart on file, which is why "
        "the page does not use it")


def test_the_watch_port_sensitivity_is_material_but_not_half_the_year():
    """Big enough for a paragraph, and nothing like the claim it replaces.

    The old test asserted the step change exceeded half the whole projection,
    which was true only of Columbus's while-open rate over a 41-day window --
    both of which the page has stopped using. On the restart cohort over 23
    days it is worth something between a twelfth and a sixth of the year.
    """
    base = project_year_end(SERIES_2026, today=date(2026, 10, 2))["projected"]
    nd = watch_window("2026-10-28", date(2026, 11, 30))["days"]
    cohort = cohort_at(_RESTARTS, nd)
    lo, hi = cohort[0]["rate"] * nd, cohort[-1]["rate"] * nd
    assert 0.08 < lo / base < 0.20
    assert hi > lo
    # and the rejected figure really is above every restart on file
    assert 1_117.9 * nd > hi


# ── next year, as scenarios ─────────────────────────────────────────────────
#
# The real 2023-24 shares, so the arithmetic is pinned against the border AMS
# actually reported rather than round numbers chosen to agree.
_SHARES = {"Santa Teresa": 878_950, "Douglas": 315_550, "Nogales": 261_600,
           "Columbus": 237_600, "Presidio": 199_500, "Pharr / Hidalgo": 63_300,
           "Del Rio": 46_250, "Laredo": 41_150, "Eagle Pass": 39_700,
           "Colombia Bridge": 19_800}
_NORMAL_DAYS = 381
_NORMAL_HEAD = 2_095_150          # the total row over those same 381 days


class _OutlookCur:
    """Answers the four queries year_outlook makes, in the order it makes them."""

    def __init__(self, open_ports):
        self._open = open_ports
        self._q = []

    def execute(self, sql):
        self._q.append(" ".join(sql.split()))
        return self

    def fetchall(self):
        q = self._q[-1]
        if "GROUP BY crossing_point" in q and "MIN(report_date)" in q:
            # crossing_debuts
            return [(p, "ST", "2026-08-24", "2026-10-05", 1000, 10)
                    for p in self._open]
        return [(p, h) for p, h in _SHARES.items()]        # port_shares

    def fetchone(self):
        q = self._q[-1]
        if "SUM(receipts_est), COUNT(*)" in q:             # normal_rate
            return (_NORMAL_HEAD, _NORMAL_DAYS)
        return (_NORMAL_DAYS,)                             # port_shares day count


class _OutlookConn:
    def __init__(self, open_ports=("Douglas", "Santa Teresa")):
        self._cur = _OutlookCur(list(open_ports))

    def cursor(self):
        return self._cur


def _outlook(**kw):
    return year_outlook(_OutlookConn(kw.pop("open_ports",
                                            ("Douglas", "Santa Teresa"))),
                        2027, SERIES_2026, today=date(2026, 10, 2), **kw)


def test_the_outlook_is_four_ordered_scenarios():
    o = _outlook()
    s = o["scenarios"]
    assert s["as_is"] < s["watch"] < s["mature"] < s["normal"], (
        "the scenarios must only ever get larger, or the page's ordering lies")
    assert o["year"] == 2027
    assert o["reporting_days"] == 249


def test_the_watch_scenario_scales_capacity_not_the_ports_own_old_rate():
    """The one error that arrives in the right units and is nearly 5x wrong.

    Columbus moved ~1,271 head on each day it ran in 2023-24, so "add it
    back" reads as +316,000 on a 249-day year. But its neighbours are at
    well under half their normal rate, and a crossing restarting from nothing
    does not instantly beat them two to one. Scaling share of port capacity
    gives an increment several times smaller.
    """
    o = _outlook()
    gained = o["scenarios"]["watch"] - o["scenarios"]["as_is"]
    naive = 1_271 * o["reporting_days"]
    assert gained == pytest.approx(
        o["scenarios"]["as_is"] * (o["watch_share"] / o["open_share"]))
    assert naive > 4 * gained, "the naive figure should be several times larger"


def test_a_closed_watch_port_adds_nothing():
    """No share, no increment — and the page then shows a dash, not a zero."""
    o = _outlook(watch="Nowhere")
    assert o["watch"] is None
    assert o["watch_share"] == 0
    assert o["scenarios"]["watch"] == pytest.approx(o["scenarios"]["as_is"])


def test_a_watch_port_that_has_already_reopened_is_dropped():
    """The 154,673-head error that was live from 2026-10-26.

    Columbus reopened that morning and WATCH_PORT still named it, so the panel
    offered +90,679 head for an event that had happened, on a pace that already
    contained its cattle, under a tile label reading
    "Douglas/Santa Teresa/Columbus/Columbus".
    """
    o = _outlook(watch="Columbus",
                 open_ports=("Douglas", "Santa Teresa", "Columbus"))
    assert o["watch"] is None
    assert o["watch_share"] == 0
    assert o["scenarios"]["watch"] == pytest.approx(o["scenarios"]["as_is"])


def test_mature_describes_one_set_of_ports_either_way():
    """The clincher, and the only thing that made the double count visible.

    `mature` is "these crossings at their normal rates". Columbus reopening
    moved nothing about which crossings those are, so the figure must not move
    -- and it jumped 16.6% on the day, with every number still a plausible head
    count.
    """
    before = _outlook(watch="Columbus", open_ports=("Douglas", "Santa Teresa"))
    after = _outlook(watch="Columbus",
                     open_ports=("Douglas", "Santa Teresa", "Columbus"))
    assert before["scenarios"]["mature"] == pytest.approx(
        after["scenarios"]["mature"])


def test_the_ramp_week_is_read_rather_than_typed():
    """The caption said "6,400 in week five this time" into week ten."""
    weeks = ramp_weeks(SERIES_2026)
    assert weeks[0]["week"] == 1 and weeks[0]["begin"] == "2026-08-24"
    assert weeks[0]["head"] == 2_500
    assert [w["week"] for w in weeks] == sorted(w["week"] for w in weeks)
    # the Labor Day week has four reporting days on file and AMS published four
    assert any(w["days"] < 5 for w in weeks)


def test_maturity_is_against_the_open_ports_own_normal():
    """Not against the whole border, or two open ports read as permanently broken."""
    o = _outlook()
    normal_for_those_ports = o["open_share"] * o["scenarios"]["normal"]
    assert o["maturity"] == pytest.approx(
        o["scenarios"]["as_is"] / normal_for_those_ports)
    assert 0 < o["maturity"] < 1


def test_the_normal_year_is_a_RATE_carried_onto_the_target_year():
    """2024's raw head is short — the border shut 22 Nov — so it is not a year.

    The scenario has to be head-per-reporting-day times the TARGET year's
    reporting days, which is larger than any single recorded year's total.
    """
    o = _outlook()
    assert o["normal_rate"] == pytest.approx(_NORMAL_HEAD / _NORMAL_DAYS)
    assert o["scenarios"]["normal"] == pytest.approx(
        o["normal_rate"] * o["reporting_days"])
    assert o["scenarios"]["normal"] > 1_277_600, "must exceed truncated 2024"


def test_shares_are_used_rather_than_summed_per_port_day_rates():
    """Per-port rates sum ~58% high because ports run different day counts.

    Pinned as a property of the result: the normal scenario has to equal the
    measured border rate times the year, never the sum of the port rates.
    """
    o = _outlook()
    assert o["open_share"] + o["watch_share"] < 1.0
    assert o["scenarios"]["mature"] == pytest.approx(
        (o["open_share"] + o["watch_share"]) * o["scenarios"]["normal"])


def test_outlook_needs_a_pace_and_degrades_to_none():
    assert year_outlook(_OutlookConn(), 2027, [], today=date(2026, 10, 2)) is None
    assert year_outlook(_OutlookConn(), 2027, SERIES_2026[-3:],
                        today=date(2026, 10, 2)) is None
