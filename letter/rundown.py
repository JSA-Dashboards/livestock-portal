"""
The Cattle Market Rundown slide.

One client-facing slide of the day's fundamentals, in the shape Ross has been
typing by hand into PowerPoint: cash trade, carcass weights, cutout, grading,
the feeder index, and the two year-to-date rates.

IT NEVER FETCHES, AND THAT IS THE WHOLE POINT.

`rows()` takes the ctx `build.gather()` has already assembled and formats it.
It has no import path to `sources`, no `requests`, and no database handle --
the same rule `render.py` follows, and a test asserts it. The reason is not
tidiness. CLAUDE.md records twice that the letter and a dashboard quoted the
same figure and disagreed, each defensible in isolation and neither raising,
and both took a morning to find. A slide built from a SECOND set of fetches
would be a third number in that argument. Built from the ctx, the slide and
the letter are the same arithmetic by construction and cannot drift.

MISSING FIGURES ARE MARKED, NEVER DROPPED.

A bullet that silently disappears reads as "nothing to report there", which on
a client slide is a statement -- and a wrong one. Anything a source did not
return prints `[[?]]`, exactly as the letter does, so a hole looks like a hole.
`missing()` counts them so the page can refuse to hand over a deck that is
quietly full of them.

THE FIGURES THIS FIXES, recorded because they were wrong on the hand-typed
slide for 2026-10-05 and the whole point of automating it is that they stop
being wrong:

    carcass weights   "as of 8/19/26" for a week ending 9/19/26 -- a typo in
                      the month, invisible because a four-week-old weight
                      looks no different from a two-week-old one. The week
                      ending is now printed from the data.
    Slaughter YTD     -7.7% against USDA's published -7.5%
    Beef Prod YTD     -5.3% against USDA's published -5.2%
                      Both are read straight off USDA's own Change rows, so
                      they are not our arithmetic -- the hand-typed pair had
                      been carried over from the previous week's slide.
    Feeder Index      337.79 against 337.66. Not an error either way: the
                      headline index date is the first business day after
                      CME's last file, so its row is still filling when the
                      slide is built on Monday afternoon. It moves after you
                      type it.

The 5-day average is the five sessions BEFORE the one being reported. See
`sources.fetch_cutout`, which carried the other convention until 2026-10-06.
"""

from __future__ import annotations

import pathlib
from datetime import date, datetime, timedelta

# Plain text, not render.MISSING -- that one is wrapped in a <span> for the
# letter's CSS and would print the markup inside a PowerPoint text box.
MISSING = "[[?]]"

TITLE = "Cattle Market Rundown"


# -- formatting ---------------------------------------------------------------
# Each of these mirrors how the figure reads on the slide Ross has been typing,
# down to the punctuation. They are separate from render.py's helpers because
# that module's emit HTML and escape for it.

def _f(v):
    """float or None, tolerating the strings USDA sometimes sends."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:,.2f}"


def head(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:,.0f}"


def signed_head(v) -> str:
    """'+40,881' -- a week-on-week head change, always signed."""
    v = _f(v)
    return MISSING if v is None else f"{v:+,.0f}"


def signed_money(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:+.2f}"


def lbs(v) -> str:
    """'891#' -- the trade's own way of writing a carcass weight."""
    v = _f(v)
    return MISSING if v is None else f"{v:,.0f}#"


def pct1(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:.1f}%"


def signed_pct1(v) -> str:
    """'-7.5%'. Unsigned when positive, because '+2.1% YTD' is not how it reads."""
    v = _f(v)
    return MISSING if v is None else f"{v:.1f}%"


def short_date(d) -> str:
    """
    '9/19/26'. Built by hand rather than with strftime because the no-pad
    directive is %-d on Linux and %#d on Windows, and this runs on both.
    """
    d = _as_date(d)
    return MISSING if d is None else f"{d.month}/{d.day}/{d.year % 100:02d}"


def _as_date(d):
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if not d:
        return None
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _weekday(d) -> str:
    """'Monday', for the 'Choice- 378.26. +4.07 Monday PM.' line."""
    d = _as_date(d)
    return d.strftime("%A") if d else MISSING


def _diff(a, b):
    a, b = _f(a), _f(b)
    return None if a is None or b is None else a - b


# -- the slide ----------------------------------------------------------------

def rows(ctx: dict) -> list:
    """
    The slide as (indent_level, text) pairs, in order.

    Levels mirror the hand-typed deck: 0 is a top bullet, 3 is the delivery
    split nested under the volume total. Returning structure rather than a
    rendered string is what lets the page preview it as markdown and the
    exporter lay it out as real PowerPoint bullets from the same source.
    """
    cash = ctx.get("cash") or {}
    cutout = ctx.get("cutout") or {}
    weights = ctx.get("carcass_weights") or {}
    fci = ctx.get("fci") or {}
    slaughter = ctx.get("slaughter") or {}

    live = cash.get("live") or {}
    dressed = cash.get("dressed") or {}
    vol = cash.get("volume") or {}

    out = [(0, "Last week's cash trade")]
    out.append((1, f"{money(live.get('this_week'))} live versus "
                   f"{money(live.get('last_week'))} week earlier"))
    out.append((1, f"{money(dressed.get('this_week'))} dressed versus "
                   f"{money(dressed.get('last_week'))} week earlier"))
    out.append((1, f"Volume: {signed_head(_diff(vol.get('confirmed'), vol.get('confirmed_last_week')))}/hd WoW"))
    out.append((2, f"{head(vol.get('confirmed'))} head total"))
    out.append((3, f"1-14-day: {head(vol.get('d14'))}. "
                   f"{signed_head(_diff(vol.get('d14'), vol.get('d14_last_week')))}/hd WoW"))
    out.append((3, f"15-30 day: {head(vol.get('d30'))}. "
                   f"{signed_head(_diff(vol.get('d30'), vol.get('d30_last_week')))}/hd WoW"))

    # THE WEEK ENDING IS PRINTED, NOT ASSUMED. This report runs about a
    # fortnight behind, which is long enough that a wrong date is invisible --
    # it is how "8/19/26" survived on the hand-typed slide.
    steers = weights.get("steers") or {}
    out.append((0, f"Actual carcass weights as of {short_date(weights.get('week_ending'))}- "
                   f"{lbs(weights.get('value'))} versus {lbs(weights.get('last_week'))} LW "
                   f"and {lbs(weights.get('year_ago'))} LY"))
    out.append((1, f"Steers- {lbs(steers.get('value'))} versus {lbs(steers.get('last_week'))} LW "
                   f"and {lbs(steers.get('year_ago'))} LY"))

    choice = cutout.get("choice") or {}
    select = cutout.get("select") or {}
    when = _weekday(cutout.get("report_date"))
    out.append((0, f"Choice- {money(choice.get('value'))}. "
                   f"{signed_money(choice.get('change'))} {when} PM."))
    out.append((1, f"5-day average- {money(choice.get('avg5'))}."))
    out.append((0, f"Select- {money(select.get('value'))}. "
                   f"{signed_money(select.get('change'))} {when} PM."))
    out.append((1, f"5-day average- {money(select.get('avg5'))}."))

    # Derived here rather than taken from the feed: USDA publishes the two
    # cutouts and the spread is their difference, so computing it guarantees
    # the three numbers on the slide are consistent with each other.
    grading = cutout.get("grading") or {}
    out.append((0, f"Choice/Select spread: {money(_diff(choice.get('value'), select.get('value')))}"))
    out.append((1, f"Choice & Higher- {pct1(grading.get('pct'))}"))

    out.append((0, f"Feeder Index: {money(fci.get('value'))}"))

    weekly = slaughter.get("weekly") or {}
    beef = slaughter.get("beef_production") or {}
    out.append((0, f"Slaughter {signed_pct1(weekly.get('ytd_chg_pct'))} YTD"))
    out.append((0, f"Beef Production {signed_pct1(beef.get('ytd_chg_pct'))} YTD"))
    return out


def missing(rows_: list) -> int:
    """How many figures came back empty. The page refuses to export on this."""
    return sum(text.count(MISSING) for _, text in rows_)


def as_markdown(rows_: list) -> str:
    """The preview on the page. Four spaces per level is Streamlit's nesting."""
    return "\n".join(f"{'    ' * lvl}- {text}" for lvl, text in rows_)


# -- is the number you are about to send actually today's? --------------------

def freshness(ctx: dict, today: date = None) -> dict:
    """
    Whether the PM cutout on this slide is today's or a previous session's.

    Streamlit Community Cloud has no scheduler, so nothing can rebuild this at
    3pm on its own -- the tab is built when it is opened. That makes "which
    session am I looking at" the question the page has to answer out loud,
    because the failure it prevents is silent: the cutout for the previous
    session is a perfectly good number and looks exactly like today's. It is
    the same trap as the stale futures feed in CLAUDE.md, where every check
    asked whether data came back and it had.

    `stale` is deliberately false at a weekend and before the PM release --
    there is no session to be behind on, so saying "stale" would train the
    reader to ignore it.
    """
    today = today or date.today()
    cutout = ctx.get("cutout") or {}
    got = _as_date(cutout.get("report_date"))

    # Last weekday on or before today: Sat/Sun fall back to Friday.
    expected = today
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)

    if got is None:
        return {"stale": True, "report_date": None, "expected": expected,
                "message": "No cutout in this build — the slide has no Choice or Select."}
    if got >= expected:
        return {"stale": False, "report_date": got, "expected": expected,
                "message": f"PM cutout for {_weekday(got)} {short_date(got)} is in."}
    return {"stale": True, "report_date": got, "expected": expected,
            "message": (f"Still showing {_weekday(got)} {short_date(got)} — "
                        f"{_weekday(expected)}'s PM cutout has not landed yet. "
                        f"It is released around 3pm CT; press Fetch latest data after that.")}


# -- PowerPoint ---------------------------------------------------------------

# 16:9, which is what the deck these slides go into uses. python-pptx's default
# template is 4:3 and would letterbox the slide inside Ross's deck.
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5

# Point size per indent level, matching the hand-typed slide's taper.
#
# THESE ARE SET BY THE VERTICAL BUDGET, not by taste. The body box runs from
# BODY_TOP to BODY_BOT and the logo sits below it; at 20/17/15/14 the 18 rows
# came to about 6.1in, ran past the box and printed the last line THROUGH the
# logo. A point off each level buys roughly 0.33in, which is one wrapped line
# of headroom for a week whose carcass line runs long.
#
# Deliberately fixed rather than autofit: a placeholder that shrinks to fit
# would give a different type size whenever the content grew by a line, and a
# slide that is subtly smaller than last week's is the sort of thing nobody
# reports and everybody notices.
_SIZES = {0: 19, 1: 16, 2: 14, 3: 13}
# Left margin per level, in inches. The bullet hangs back into _HANG.
_MARGIN_IN = {0: 0.28, 1: 0.74, 2: 1.20, 3: 1.66}
_HANG_IN = 0.26

# Where the body starts and where the logo sits. Kept as module constants so
# the test can do the collision arithmetic without rendering anything.
BODY_TOP_IN = 0.95
LOGO_TOP_IN = 6.80
LOGO_H_IN = 0.50


def text_height_in(rows_: list) -> float:
    """
    Estimated rendered height of the body, in inches.

    An ESTIMATE on purpose -- the real height depends on the font metrics
    PowerPoint uses, which nothing here can see. 1.22x the point size is the
    usual single-line spacing for Calibri and is close enough to catch the
    failure that actually happened (text running 0.05in into the logo). It is
    used by the test, not by the layout, so a slightly wrong constant costs a
    margin of safety rather than a wrong slide.
    """
    pts = sum(_SIZES.get(lvl, 13) * 1.22 + 2 for lvl, _ in rows_)
    return pts / 72.0


def _bullet(para, lvl: int):
    """
    Put a real bullet glyph and a hanging indent on the paragraph.

    SETTING para.level IS NOT ENOUGH ON A PLAIN TEXT BOX. A level only selects
    a style from the layout's list styles, and a blank-layout text box has
    none -- so the first build came out as flat, unindented, bullet-less text
    that still reported the right `level` through python-pptx. It inspected
    fine and looked wrong, which is the failure mode worth guarding.

    Writing buChar and the margins explicitly also makes the slide render the
    same in Google Slides and LibreOffice, which read a missing bullet
    definition differently from PowerPoint.
    """
    from pptx.util import Inches
    from pptx.oxml.ns import qn

    pPr = para._p.get_or_add_pPr()
    pPr.set("marL", str(Inches(_MARGIN_IN.get(lvl, 1.66)).emu))
    pPr.set("indent", str(-Inches(_HANG_IN).emu))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    buFont = pPr.makeelement(qn("a:buFont"), {"typeface": "Arial"})
    buChar = pPr.makeelement(qn("a:buChar"), {"char": "•"})
    pPr.append(buFont)
    pPr.append(buChar)


def build_pptx(rows_: list, out, title: str = TITLE, logo=None):
    """
    Write the slide to `out` -- a path, or any file-like object.

    Takes ROWS, not ctx, so the writer knows nothing about where the figures
    came from and the page can memoise on the rows alone. A hidden Streamlit
    tab still executes every rerun, so without that the letter page would
    rebuild a PowerPoint file on every keystroke in the commentary boxes.

    A BLANK LAYOUT WITH EXPLICIT TEXT BOXES, not a title+content placeholder.
    The placeholder layout autofits text by shrinking it, so a week with a long
    carcass line would silently come out in a different size from last week's
    slide -- the sort of difference nobody reports and everybody notices. Fixed
    boxes and fixed sizes mean every week's slide is the same slide.

    Imported lazily so that a missing python-pptx breaks the download button
    and nothing else on the page.
    """
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)
    slide = prs.slides.add_slide(prs.slide_layouts[6])   # 6 == blank

    tb = slide.shapes.add_textbox(Inches(0.45), Inches(0.22),
                                  Inches(SLIDE_W_IN - 0.9), Inches(0.72))
    p = tb.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = title
    run.font.size = Pt(36)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    body = slide.shapes.add_textbox(Inches(0.45), Inches(0.95),
                                    Inches(SLIDE_W_IN - 0.9), Inches(5.9))
    tf = body.text_frame
    tf.word_wrap = True
    first = True
    for lvl, text in rows_:
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        para.level = lvl
        para.space_after = Pt(2)
        _bullet(para, lvl)
        r = para.add_run()
        r.text = text
        r.font.size = Pt(_SIZES.get(lvl, 14))
        r.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    if logo is not None:
        try:
            # LOGO_TOP must clear the bottom of the text. At 0.62in high and
            # 0.95in off the floor the logo sat at 6.55in and the 18 rows ran
            # to 6.60in, so the last line -- "Beef Production -5.2% YTD" --
            # printed straight through the wordmark. It rendered without
            # complaint and only a picture of the slide showed it.
            # tests/test_rundown.py now asserts the clearance arithmetically
            # so nobody has to take that picture again.
            slide.shapes.add_picture(str(logo), Inches(0.45),
                                     Inches(LOGO_TOP_IN), height=Inches(LOGO_H_IN))
        except Exception:
            # A missing or unreadable logo must not cost Ross the deck.
            pass

    # A str/Path goes to disk; anything else is a file-like (BytesIO on the
    # page, which never touches the container's filesystem).
    prs.save(str(out) if isinstance(out, (str, pathlib.Path)) else out)
    return out
