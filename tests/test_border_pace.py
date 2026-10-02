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
    NON_REPORTING,
    NORMAL_YEARS,
    PACE_WINDOW,
    WATCH_PORT,
    WATCH_PORT_EXPECTED,
    daily_pace,
    port_profile,
    project_year_end,
    reporting_days,
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
    """The denominator of the Columbus sensitivity on the page.

    Thanksgiving and Christmas come out; the day after Thanksgiving does not.
    Pinned because the note quotes head counts built on it, and a holiday
    added to NON_REPORTING by mistake would move them with nothing to show it.
    """
    assert reporting_days(date(2026, 11, 1), date(2026, 12, 31)) == 41


def test_watch_port_names_a_crossing_ams_actually_reports():
    """A typo here does not raise -- it silently removes the note.

    port_profile() returns None for a crossing it cannot find, and the page
    reads None as "this port is open, say nothing". So a misspelt WATCH_PORT
    looks exactly like a reopened one.
    """
    if WATCH_PORT is None:
        return                       # cleared once the port reopens; fine
    cities = {p.split(",")[0].strip().upper() for p in KNOWN_PORTS}
    assert WATCH_PORT.upper() in cities
    assert WATCH_PORT_EXPECTED, "a watch port with no expected date says nothing"


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
        (237_600, 187),              # the port, over the normal years
        (2_103_400,),                # all named ports, same years
        (date(2024, 11, 21),),       # last seen, ever
        (0,),                        # rows this year -> not running
    ])
    prof = port_profile(conn, "Columbus", this_year=2026)
    assert prof["head"] == 237_600
    assert prof["days"] == 187
    assert prof["per_day"] == pytest.approx(237_600 / 187)
    assert prof["share"] == pytest.approx(237_600 / 2_103_400)
    assert prof["last_seen"] == "2024-11-21"
    assert prof["running"] is False


def test_port_profile_knows_a_running_port():
    conn = _Conn([(315_550, 260), (2_103_400,), (date(2026, 10, 1),), (22,)])
    assert port_profile(conn, "Douglas", this_year=2026)["running"] is True


def test_port_profile_is_none_for_a_crossing_with_no_history():
    """None rather than a zero rate: there is nothing to project from."""
    assert port_profile(_Conn([(None, 0)]), "Nowhere", this_year=2026) is None
    assert port_profile(_Conn([(0, 0)]), "Nowhere", this_year=2026) is None


def test_columbus_sensitivity_is_material():
    """If reopening moved the projection trivially the note would be noise.

    At Columbus's own normal rate over November and December it adds more
    than half the entire projection again, which is why it gets a paragraph
    rather than a clause.
    """
    base = project_year_end(SERIES_2026, today=date(2026, 10, 2))["projected"]
    nd = reporting_days(date(2026, 11, 1), date(2026, 12, 31))
    assert (237_600 / 187) * nd > base * 0.5
