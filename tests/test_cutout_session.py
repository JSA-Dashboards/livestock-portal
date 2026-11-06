"""
Which boxed beef report the letter is quoting, and the stamp that says so.

Added 2026-11-06 on Ross's "can we have every am and pm email show when the
choice/select cutouts are updated? some of them will say, Tuesday PM or
Tuesday AM" and then "use the morning cutout too when it's fresher".

Two things are pinned here and they fail differently:

  * THE STAMP. Two of the four letter formats carried no date on the cutout
    at all -- the morning brief and the Friday letter -- so a reader could
    not tell yesterday's close from today's. Nothing in the suite rendered
    either of those lines with a populated cutout, so there was no test to
    extend.

  * WHICH REPORT. LM_XB402 (the ~10:55 CT morning read) and LM_XB403 (the
    ~3pm close) are different reports. The letter takes the morning one when
    it is strictly newer, which means the word on the stamp is now a claim
    about USDA's data rather than decoration -- and a wrong one is invisible,
    because a morning cutout is a perfectly plausible afternoon cutout.

    python -m pytest tests/test_cutout_session.py -q
"""
import ast
import inspect
import pathlib
import re
from datetime import date

import pytest

from letter import build, config, render, rundown, sources

REPO = pathlib.Path(__file__).resolve().parent.parent
DOT = "·"

# A Thursday close and a Friday morning read, carrying the real figures off
# the two live reports on 2026-11-06 -- the day this was built, when the PM in
# hand was 11-05 and the morning report was 11-06.
PM_CUT = {"choice": {"value": 361.56, "change": -0.94, "avg5": 364.94},
          "select": {"value": 352.32, "change": -4.33, "avg5": 354.71},
          "report_date": "2026-11-05", "session": "PM",
          "grading": {"pct": 87.5, "pct_last_week": 87.9,
                      "report_date": "2026-11-03"}}

AM_CUT = {"choice": {"value": 360.73, "change": -0.83, "avg5": 363.80},
          "select": {"value": 353.39, "change": 1.07, "avg5": 354.85},
          "report_date": "2026-11-06", "session": "AM"}

# EVERY FORMAT, DERIVED. config.CHANGE_BASIS_BY_KIND is the canonical list of
# letter formats, so a fifth one added later is covered here by construction
# rather than by somebody remembering to extend a literal tuple. The portal
# already learned that lesson on test_the_list_of_refresh_pages_is_complete,
# which found a seventh page on its first run.
KINDS = tuple(config.CHANGE_BASIS_BY_KIND)

# How many cutout LINES each format prints. The morning brief carries one line
# holding both grades; the three evening formats carry one per grade.
#
# ASSERTED RATHER THAN ASSUMED, for two reasons. Every negative assertion here
# ("Mon" not in ...) passes vacuously against an empty list. And a per-line
# check is the only kind that notices ONE grade regressing while the other is
# fine -- the first run of the mutation harness reverted the slide's Choice
# row alone and a joined-string substring match let it straight through.
LINES_PER_FORMAT = {"am": 1, "tuesday": 2, "recap": 2, "friday": 2}


def ctx(kind, cut):
    """
    The thinnest context build_html will render, for any format.

    issue_date is deliberately a DIFFERENT WEEKDAY from either cutout's
    report_date, which is what lets these tests catch a stamp built from the
    letter rather than from the report.
    """
    return {"kind": kind, "session": "am" if kind == "am" else "pm",
            "issue_date": date(2026, 11, 9),            # a MONDAY
            "change_basis": config.CHANGE_BASIS_BY_KIND[kind],
            "live_cattle": [], "feeder_cattle": [],
            "cash": {}, "cutout": cut, "slaughter": {},
            "commentary": {"headlines": ["h"], "market_action": ["m"],
                           "key_headlines": ["k"], "comments": ["c"]}}


def cutout_lines(kind, cut):
    """Every rendered cutout line of one format, tags stripped."""
    html = render.build_html(ctx(kind, cut))
    flat = re.sub(r"<[^>]+>", "\n", html).replace("&middot;", DOT)
    lines = [l.strip() for l in flat.split("\n") if "utout" in l and l.strip()]
    assert len(lines) == LINES_PER_FORMAT[kind], (kind, lines)
    return lines


# -- the stamp is on every format --------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_every_format_dates_its_cutout(kind):
    """
    Ross: "I want that for every email version."

    Before this, only the Monday full letter and the Tue/Wed/Thu recap
    carried a stamp. The morning brief and the Friday letter printed a
    Choice/Select figure with nothing saying which session it was.
    """
    for line in cutout_lines(kind, PM_CUT):
        assert "Thurs PM" in line, (kind, line)


@pytest.mark.parametrize("kind", KINDS)
def test_the_day_comes_from_the_report_not_the_letter(kind):
    """
    THE WHOLE CORRECTNESS OF THE STAMP, and it was guarded in exactly one
    helper before this.

    LM_XB403 publishes about 3pm Central, so a letter written earlier carries
    the previous session. The ctx above is issued on a MONDAY against a
    Thursday report, so a stamp derived from issue_date would say "Mon" --
    a false claim about which print the reader is holding.
    """
    for line in cutout_lines(kind, PM_CUT):
        assert "Thurs" in line, (kind, line)
        assert "Mon" not in line, f"{kind} dated the cutout from the issue date: {line}"


@pytest.mark.parametrize("kind", KINDS)
def test_the_session_comes_from_the_report_not_the_letter(kind):
    """
    The same claim about the OTHER half of the stamp, and the easier one to
    get wrong: deriving AM/PM from `kind == "am"` would stamp "AM" on the
    morning brief, which quotes an AFTERNOON report every day of its life.

    Both directions are checked, because a stamp that always agreed with the
    format would pass a one-sided version of this.
    """
    for line in cutout_lines(kind, PM_CUT):
        assert "Thurs PM" in line, (kind, line)
    for line in cutout_lines(kind, AM_CUT):
        assert "Fri AM" in line, (kind, line)


def test_the_morning_brief_says_PM_when_it_is_quoting_the_close():
    """
    Named separately because it is the case Ross's wording invites and the
    one that would be wrong: the 07:30 brief cannot have that morning's
    9:30am read -- it is not published for another three hours -- so it is
    quoting yesterday's close and must say so.
    """
    line, = cutout_lines("am", PM_CUT)
    assert "Cutout (Thurs PM)" in line
    assert "AM" not in line


def test_the_detector_can_fail():
    """
    A guard that cannot fail is the thing it guards against. The two sessions
    must render differently on every format, or the tests above would pass
    against a stamp that ignored the session entirely.
    """
    for kind in KINDS:
        assert cutout_lines(kind, PM_CUT) != cutout_lines(kind, AM_CUT), kind


# -- punctuation, which is per-format on purpose -----------------------------

def test_friday_keeps_its_own_punctuation():
    """
    CLAUDE.md and the comment at the head of that section keep Friday's
    colons and signed numbers apart from Tuesday's dashes and words
    deliberately -- clients read both every week. So the stamp is joined with
    the letter's own middle dot there, never with the recap's dash.
    """
    fri = cutout_lines("friday", PM_CUT)
    assert f"Choice cutout: -0.94 at 361.56 {DOT} Thurs PM." in fri[0], fri
    assert not any("361.56- " in l for l in fri), "Friday imported the recap's dash"

    recap = cutout_lines("recap", PM_CUT)
    assert "Choice cutout- Down 0.94 at 361.56- Thurs PM." in recap[0], recap


def test_the_friday_stamp_trips_no_neighbouring_guard():
    """
    tests/test_source_warnings.py asserts "est." and "w/e" appear NOWHERE in
    friday_rundown_block's output -- whole-block negative assertions, so a
    stamp wording either of those would fail over there and read as a
    weekly-slaughter problem.
    """
    html = render.friday_rundown_block({}, {}, PM_CUT, {}, {})
    assert "est." not in html
    assert "w/e" not in html


def test_a_missing_report_date_leaves_no_dangling_punctuation():
    """
    The recap interpolated the stamp as `at {money}-{pm}`, so a cutout with
    no report_date rendered "Choice cutout- Down 0.94 at 361.56-" on a client
    letter: a trailing dash leading nowhere. No test saw it, and every recap
    render in the suite was in exactly that state.
    """
    bare = {k: v for k, v in PM_CUT.items() if k != "report_date"}
    for kind in KINDS:
        for line in cutout_lines(kind, bare):
            assert not line.rstrip().endswith(("-", DOT)), f"{kind}: {line!r}"
            assert "()" not in line, f"{kind}: {line!r}"


# -- picking between the two reports -----------------------------------------

def test_the_morning_read_wins_only_when_it_is_strictly_later():
    """
    On a tie the CLOSE supersedes the morning of the same day: they describe
    one session and the close is the finished one. That is the whole reason
    the comparison is strict, and it is what makes the rule behave at 07:30 --
    before the morning release ams_2452.pdf still serves YESTERDAY's report,
    which ties yesterday's close, so the brief prints what it always has.
    """
    newer = sources.pick_cutout(PM_CUT, AM_CUT)
    assert newer["session"] == "AM" and newer["report_date"] == "2026-11-06"

    same_day_am = dict(AM_CUT, report_date="2026-11-05")
    tie = sources.pick_cutout(PM_CUT, same_day_am)
    assert tie["session"] == "PM", "the morning read displaced its own close"
    assert tie["choice"]["value"] == PM_CUT["choice"]["value"]

    older = sources.pick_cutout(PM_CUT, dict(AM_CUT, report_date="2026-11-04"))
    assert older["session"] == "PM"


def test_it_needs_no_clock():
    """
    Every date on this line comes from the reports themselves -- the rule
    _settle_stamp and the weekday half of the stamp already follow, because
    "yesterday" is wrong on a Monday and wrong after a holiday. pick_cutout
    therefore takes no `today` and cannot be made to answer differently by
    the hour it runs at.
    """
    assert list(inspect.signature(sources.pick_cutout).parameters) == ["pm", "am"]


def test_all_three_figures_come_from_one_report():
    """
    Level, change and 5-day average, or none of them. Taking the level from
    the morning and the average from the close would put two reports on one
    line and both halves would look perfectly reasonable.
    """
    got = sources.pick_cutout(PM_CUT, AM_CUT)
    for grade in ("choice", "select"):
        assert got[grade] == AM_CUT[grade], grade


def test_grading_survives_the_switch():
    """
    LSWFEDCC is a weekly report on its own date and has no morning edition,
    so it is untouched either way. Dropping it would blank the "Choice &
    Higher Grading %" line on every pre-3pm letter.
    """
    assert sources.pick_cutout(PM_CUT, AM_CUT)["grading"] == PM_CUT["grading"]


def test_either_side_missing_is_handled():
    assert sources.pick_cutout(PM_CUT, {})["session"] == "PM"
    assert sources.pick_cutout({}, AM_CUT)["session"] == "AM"
    assert sources.pick_cutout({}, {}) == {}


# -- the slide, which is built from the same ctx -----------------------------

def _slide_cutout(cut):
    """The slide's Choice and Select rows -- BOTH of them, separately."""
    rows = [t for _lvl, t in rundown.rows(ctx("tuesday", cut))
            if t.startswith(("Choice-", "Select-"))]
    assert len(rows) == 2, rows
    return rows


def test_the_slide_follows_the_same_report():
    """
    letter/rundown.py hard-coded the word "PM." It is built from the SAME ctx
    as the letter, so once the letter could carry a morning read the slide
    would have printed "Friday PM." over a morning number -- on the one-pager
    that goes to clients.
    """
    for row in _slide_cutout(PM_CUT):
        assert "Thursday PM." in row, row
    for row in _slide_cutout(AM_CUT):
        assert "Friday AM." in row, row


def test_the_letter_and_the_slide_cannot_disagree_about_the_session():
    """
    They are two surfaces quoting one figure, in adjacent tabs of one page.
    The repo records that failure five times; here it is prevented by both
    reading ctx["cutout"]["session"] rather than deciding for themselves.
    """
    for cut in (PM_CUT, AM_CUT):
        word = cut["session"]
        other = "AM" if word == "PM" else "PM"
        for kind in KINDS:
            for line in cutout_lines(kind, cut):
                assert word in line, (kind, line)
                assert f" {other}" not in line, (kind, line)
        for row in _slide_cutout(cut):
            assert f"{word}." in row, row
            assert f" {other}." not in row, row


def test_the_two_surfaces_keep_their_own_day_spelling():
    """
    The letter abbreviates ("Thurs") and the slide spells it out
    ("Thursday"). That difference predates this change and is deliberate;
    tests/test_rundown.py pins the slide's form by exact row equality, so
    merging the two helpers would quietly restyle a client deck.
    """
    assert all("Thurs PM" in l for l in cutout_lines("recap", PM_CUT))
    assert all("Thursday PM." in r for r in _slide_cutout(PM_CUT))


def test_the_banner_names_the_session():
    """
    A morning read is STALE for the banner's purpose even though it is
    today's. Before the letter could carry LM_XB402, a 1pm build held
    yesterday's close and the banner warned; letting today's morning read
    satisfy the date test would have silenced that warning on exactly the
    builds that still need it.
    """
    fresh = rundown.freshness(ctx("tuesday", AM_CUT), today=date(2026, 11, 6))
    assert fresh["session"] == "AM"
    assert fresh["stale"] is True
    assert "MORNING read" in fresh["message"] and "LM_XB402" in fresh["message"]

    closed = rundown.freshness(ctx("tuesday", dict(PM_CUT, report_date="2026-11-06")),
                               today=date(2026, 11, 6))
    assert closed["session"] == "PM" and closed["stale"] is False


# -- the operator warning, which is the only prompt to re-run after 3pm ------

def test_an_evening_letter_on_a_morning_read_still_says_so():
    """
    build.report_source_health's date test alone goes quiet once the cutout
    is dated today, and that warning is the only thing telling Ross to re-run
    after the close. Without this he would send a morning figure as the close
    with nothing said.
    """
    errors = []
    build.report_source_health(ctx("recap", AM_CUT), date(2026, 11, 6), "recap", errors)
    assert any("MORNING read" in e and "LM_XB402" in e for e in errors), errors

    quiet = []
    build.report_source_health(ctx("am", AM_CUT), date(2026, 11, 6), "am", quiet)
    assert not any("MORNING read" in e for e in quiet), (
        "the morning brief would warn every single day")


# -- the parser is not copied ------------------------------------------------

def test_sources_does_not_reimplement_the_morning_parser():
    """
    letter/sources.py loads apps/beef_cutout/am_cutout.py BY PATH, the route
    deploy/bank_am_cutout.py already takes. A second copy of a PDF parser is
    the snowflake_db-times-five problem, and it would let the letter and the
    Beef Cutout page disagree about what one report says.

    BY AST, WITH DOCSTRINGS DROPPED. sources.py's own prose names
    ams_2452.pdf while explaining why it does not hold that URL, so a
    substring search over the file matches the comment that documents the
    rule. Fifth time in this repo; see tests/test_cutout_five_day.py.
    """
    tree = ast.parse((REPO / "letter" / "sources.py").read_text(encoding="utf-8"))

    owned = {"parse_am", "fetch_am", "default_session"}
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not (owned & defined), f"{owned & defined} belongs to am_cutout"

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docstrings.add(d)
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value not in docstrings]
    assert not [s for s in literals if "ams_2452" in s], (
        "the morning PDF's URL is am_cutout's; load it, do not copy it")
