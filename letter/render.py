"""
Render the letter to HTML, laid out for print.

Phrasing follows the sent letters rather than improving on them -- "Live cash-
222.85 versus 219.05 week before", "Choice cutout- Up 0.77 at 376.08- Tues PM."
Clients have been reading this wording for years and the generator is not the
place to redesign it.

MISSING VALUES ARE LOUD. Anything a source did not return renders as a marked
[[?]] instead of quietly disappearing, and build.py lists every one before it
finishes. A bullet that silently vanished between the draft and the PDF is the
exact failure this generator exists to remove, so it must not be able to happen
here either.
"""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from . import chart as chart_mod
from . import config

import base64
import functools

MISSING = '<span class="missing">[[?]]</span>'

@functools.lru_cache(maxsize=8)
def _asset_uri(name: str) -> str:
    """
    An image from assets/, inlined as a data URI.

    EMBEDDED, NOT LINKED, for three reasons that all matter here. The PDF is
    produced by headless Edge and then emailed: a <img src="assets/..."> would
    resolve relative to wherever the HTML happens to sit, a jpsi.com URL would
    need the network at print time and would silently drop to a broken-image box
    if it were slow, and neither survives the file being forwarded. A data URI
    is part of the document.

    Returns "" when the file is missing, so a letter still builds -- letterhead
    is presentation, and losing it must not cost the numbers.
    """
    path = Path(__file__).resolve().parent.parent / "assets" / name
    try:
        return ("data:image/png;base64,"
                + base64.b64encode(path.read_bytes()).decode("ascii"))
    except OSError:
        return ""



# -- Formatting ---------------------------------------------------------------

def price(v, dp: int = 3) -> str:
    """
    Futures style: up to three decimals, trailing zeros trimmed, never fewer
    than two. 220.700 -> 220.70, 224.675 -> 224.675.
    """
    if v is None:
        return MISSING
    s = f"{float(v):.{dp}f}".rstrip("0")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def signed(v, dp: int = 3) -> str:
    if v is None:
        return MISSING
    return ("+" if float(v) >= 0 else "-") + price(abs(float(v)), dp)


def money(v) -> str:
    return MISSING if v is None else f"{float(v):,.2f}"


def head(v) -> str:
    return MISSING if v is None else f"{float(v):,.0f}"


def head_k(v) -> str:
    """
    Head counts rounded to the nearest thousand, which is how the letter quotes
    them. AMS estimates the current year in whole thousands already, but the
    year-ago columns are actuals -- 229,195 -- and printing that next to a
    rounded 210,000 would imply a precision the current figure does not have.
    """
    return MISSING if v is None else f"{round(float(v) / 1000) * 1000:,.0f}"


def updown(v) -> str:
    """'Up 0.77' / 'Down 0.21' -- the letter's own phrasing for cutout moves."""
    if v is None:
        return MISSING
    return f"{'Up' if float(v) >= 0 else 'Down'} {abs(float(v)):.2f}"


def pct(v) -> str:
    return MISSING if v is None else f"{float(v):.1f}"


def _esc(s) -> str:
    return html.escape(str(s))


def eighths(v) -> str:
    """
    531.25 -> "531'2". How the grain trade writes a corn quote, and how Ross
    writes it: "5'4 lower at 531'2".

    Rounded to the nearest eighth rather than truncated, and a value that rounds
    up to a full cent carries into the whole number -- 530.9999 is 531'0, never
    530'8, which is not a price anyone would recognise.
    """
    if v is None:
        return MISSING
    f = float(v)
    sign = "-" if f < 0 else ""
    f = abs(f)
    whole, frac = int(f), round((f - int(f)) * 8)
    if frac == 8:
        whole, frac = whole + 1, 0
    # A whole cent drops the eighths entirely -- "528", not "528'0", which is
    # how Ross writes it: "-8'6 at 528".
    return f"{sign}{whole}" if frac == 0 else f"{sign}{whole}'{frac}"


def trim(v) -> str:
    """
    220.0 -> "220", 222.5 -> "222.50", 350.0 -> "350".

    How the letter writes a cash price: no trailing ".00", but a real decimal
    keeps both places. "220-222.50 FOB live. 350 Dressed." is verbatim from the
    9/18 letter.
    """
    if v is None:
        return MISSING
    f = float(v)
    return f"{f:,.0f}" if abs(f - round(f)) < 1e-9 else f"{f:,.2f}"


def trim_range(lo, hi) -> str:
    """A range, collapsed to one number when both ends agree."""
    if lo is None:
        return MISSING
    return trim(lo) if hi is None or abs(float(hi) - float(lo)) < 1e-9 else f"{trim(lo)}-{trim(hi)}"


_PM_DAYS = {0: "Mon", 1: "Tues", 2: "Wed", 3: "Thurs", 4: "Fri", 5: "Sat", 6: "Sun"}


def _settle_stamp(ctx: dict) -> str:
    """
    "9/23/26" for the session the AM report's futures actually settled in.

    READ OFF THE CONTRACTS, NOT COMPUTED FROM THE ISSUE DATE. The prior session
    is not yesterday on a Monday, and it is not yesterday after a holiday
    either; subtracting a day would print a date on which nothing settled, on
    exactly the mornings a reader is most likely to be checking. The rows
    already carry settle_date, so the heading states it.

    Live Cattle and Feeders settle the same day. If a feed ever disagreed the
    newer date wins rather than the label being dropped -- which session this is
    is the whole point of the line, and a day of skew beats no date at all.
    """
    dates = []
    for key in ("live_cattle", "feeder_cattle"):
        for con in ctx.get(key) or []:
            try:
                dates.append(date.fromisoformat(str(con.get("settle_date") or "")[:10]))
            except ValueError:
                continue
    if not dates:
        return ""
    d = max(dates)
    return f"{d.month}/{d.day}/{d.strftime('%y')}"


def _pm_label(report_date) -> str:
    """' Tues PM.' from the cutout's own report date, or '' if unknown."""
    if not report_date:
        return ""
    try:
        d = date.fromisoformat(str(report_date)[:10])
    except ValueError:
        return ""
    return f" {_PM_DAYS[d.weekday()]} PM."


# -- Sections -----------------------------------------------------------------

def _bullets(items) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _commentary(items) -> str:
    """Commentary bullets are escaped -- they are typed prose, not markup."""
    return _bullets([_esc(i) for i in items])


def futures_block(title: str, contracts: list, basis: str) -> str:
    key = "change_week" if basis == "week" else "change_day"
    rows = [f"{_esc(c['month'])}: {signed(c.get(key))} at {price(c.get('settle'))}"
            for c in contracts]
    if not rows:
        rows = [MISSING]
    return f"<h2>{_esc(title)}</h2>{_bullets(rows)}"


def technicals_block(tech: dict, commentary: list, label: str) -> str:
    """
    Computed levels first, then the read.

    The moving averages are stated as fact because they are arithmetic. Swing
    highs and lows are offered in the draft but only appear here if the
    commentary refers to them -- the letter's published support and resistance
    are a judgement, and printing a computed number in their place would be
    putting words in Ross's mouth.
    """
    lines = []
    ma = tech.get("ma", {}) if tech else {}
    # An average over a gapped series is wrong, not approximate -- marked, never
    # printed as a figure. See technicals.build.
    trustworthy = tech.get("complete", True) if tech else True
    for window in config.MA_WINDOWS:
        # Both key types on purpose. technicals.build() returns int keys, but the
        # context is cached to JSON between the fetch run and the --no-fetch
        # re-render, and JSON has no integer keys -- 9 comes back as "9". Looking
        # up only the int made the moving averages disappear from the re-rendered
        # letter with no error, which is the one thing this file must not allow.
        v = ma.get(window)
        if v is None:
            v = ma.get(str(window))
        if v is not None:
            shown = price(v) if trustworthy else MISSING
            lines.append(f"{window}-day moving average at {shown}")
    lines.extend(_esc(c) for c in commentary)
    if not lines:
        return ""
    month = tech.get("month", "") if tech else ""
    heading = f"{month} {label}".strip()
    return f"<h3>{_esc(heading)}</h3>{_bullets(lines)}"


def cash_trade_block(cash: dict) -> str:
    live, dressed, vol = cash.get("live", {}), cash.get("dressed", {}), cash.get("volume", {})
    rows = [
        f"Live cash- {money(live.get('this_week'))} versus {money(live.get('last_week'))} week before",
        f"Dressed cash- {money(dressed.get('this_week'))} versus {money(dressed.get('last_week'))} week before",
        f"Negotiated trade- {head(vol.get('confirmed'))} versus {head(vol.get('confirmed_last_week'))} week before",
        f"1-14-day window- {head(vol.get('d14'))} head versus {head(vol.get('d14_last_week'))} week before",
        f"15-30-day window- {head(vol.get('d30'))} head versus {head(vol.get('d30_last_week'))} week before",
    ]
    return "<h2>Last week&rsquo;s cash trade:</h2>" + _bullets(rows)


def rundown_block(fci: dict, slaughter: dict, cutout: dict,
                  daily: dict = None, weights: dict = None) -> str:
    rows = []
    daily = daily or {}
    weights = weights or {}

    if config.INCLUDE_FEEDER_INDEX:
        rows.append(f"Feeder cattle index- {money((fci or {}).get('value'))}")

    # Daily and WTD come from AMS 3208, which is a different report from the
    # weekly SJ_LS712 the carcass weights use -- see sources.parse_3208.
    rows.append(f"Daily slaughter- {head_k(daily.get('current_day'))} head")
    rows.append(
        f"WTD slaughter- {head_k(daily.get('wtd'))} head versus "
        f"{head_k(daily.get('wtd_week_ago'))} LW and "
        f"{head_k(daily.get('wtd_year_ago'))} LY")

    # AMS 3658 actuals -- the series the Cattle Weights dashboard shows. If the
    # MARS key is missing this renders [[?]] rather than silently substituting
    # SJ_LS712's estimate, which is a different number.
    rows.append(f"Avg carcass wts- {head(weights.get('value'))}# versus "
                f"{head(weights.get('last_week'))}# LW and "
                f"{head(weights.get('year_ago'))}# LY")

    ch, se = cutout.get("choice", {}), cutout.get("select", {})
    # The "Tues PM" tag comes from the DATA's report date, not the issue date.
    # LM_XB403 PM publishes about 3pm Central, so a letter written earlier
    # carries the PREVIOUS session's cutout -- and labelling that "Tues PM" on a
    # Tuesday would be a false claim about which print it is. Deriving the day
    # from the report makes it say "Mon PM" instead, which is true.
    pm = _pm_label(cutout.get("report_date"))
    rows.append(f"Choice cutout- {updown(ch.get('change'))} at {money(ch.get('value'))}-{pm}")
    rows.append(f"Select cutout- {updown(se.get('change'))} at {money(se.get('value'))}-{pm}")
    rows.append(f"5-day averages- Choice {money(ch.get('avg5'))}. Select {money(se.get('avg5'))}.")

    g = cutout.get("grading", {})
    rows.append(f"Choice &amp; Higher Grading %- {pct(g.get('pct'))} versus {pct(g.get('pct_last_week'))} LW")

    return "<h2>Cattle market rundown:</h2>" + _bullets(rows)


# -- Friday-only sections -----------------------------------------------------
#
# Friday punctuates differently from Tuesday and the difference is kept rather
# than tidied: "Choice cutout: -0.21 at 371.94" against Tuesday's "Choice
# cutout- Down 0.21 at 371.94- Tues PM." Clients read both every week.

def yoy(v) -> str:
    """-7.5 -> '7.5% lower YoY'. USDA gives a signed change; the letter words it."""
    if v is None:
        return MISSING
    f = float(v)
    if f == 0:
        return "unchanged YoY"
    return f"{abs(f):.1f}% {'lower' if f < 0 else 'higher'} YoY"


def signed2(v) -> str:
    return MISSING if v is None else f"{float(v):+.2f}"


def friday_rundown_block(fci: dict, slaughter: dict, cutout: dict,
                         daily: dict = None, weights: dict = None) -> str:
    """Friday's rundown: Tuesday's, plus the completed week and both YTD rates."""
    daily, weights = daily or {}, weights or {}
    wk = (slaughter or {}).get("weekly") or {}
    bp = (slaughter or {}).get("beef_production") or {}
    rows = []

    if config.INCLUDE_FEEDER_INDEX:
        rows.append(f"Feeder Cattle Index: {money((fci or {}).get('value'))}")

    rows.append(f"Daily slaughter: {head_k(daily.get('current_day'))}")
    rows.append(
        f"Weekly slaughter: {head_k(wk.get('value'))} compared to "
        f"{head_k(wk.get('last_week'))} head LW and {head_k(wk.get('year_ago'))} LY")
    rows.append(f"YTD slaughter: {yoy(wk.get('ytd_chg_pct'))}")
    rows.append(f"Beef production: {yoy(bp.get('ytd_chg_pct'))}")
    rows.append(f"Avg carcass wts: {head(weights.get('value'))}# versus "
                f"{head(weights.get('last_week'))}# LW and {head(weights.get('year_ago'))}# LY")

    g = (cutout or {}).get("grading", {})
    rows.append(f"Choice grading: {pct(g.get('pct'))}% versus {pct(g.get('pct_last_week'))}% LW")

    ch, se = (cutout or {}).get("choice", {}), (cutout or {}).get("select", {})
    rows.append(f"Choice cutout: {signed2(ch.get('change'))} at {money(ch.get('value'))}")
    rows.append(f"Select cutout: {signed2(se.get('change'))} at {money(se.get('value'))}")
    rows.append(f"5-day averages: Choice {money(ch.get('avg5'))}. Select {money(se.get('avg5'))}")

    return "<h2>Cattle market rundown:</h2>" + _bullets(rows)


def cash_cattle_block(regional: dict) -> str:
    """
    North and South negotiated ranges.

    "Undefined" is USDA's own state when a region has too little confirmed trade
    for a market test. It is printed as the letter prints it -- a real answer,
    not a gap, so it is never marked [[?]].
    """
    regions = (regional or {}).get("regions") or {}
    rows = []
    for name in ("North", "South"):
        r = regions.get(name)
        if not r:
            rows.append(f"{name}: {MISSING}")
            continue
        if r.get("undefined"):
            rows.append(f"{name}: Undefined")
            continue
        bits = []
        if r.get("live_low") is not None:
            lo, hi = r["live_low"], r["live_high"]
            bits.append(f"{money(lo)}-{money(hi)} FOB live" if lo != hi
                        else f"{money(lo)} FOB live")
        if r.get("dressed_low") is not None:
            lo, hi = r["dressed_low"], r["dressed_high"]
            bits.append(f"{money(lo)}-{money(hi)} Dressed" if lo != hi
                        else f"{money(lo)} Dressed")
        rows.append(f"{name}: {'. '.join(bits) if bits else 'Undefined'}.")
    return "<h2>Cash Cattle Trade</h2>" + _bullets(rows)


def cftc_block(cftc: dict) -> str:
    """
    Managed money net long for both contracts.

    The as-of date is PRINTED FROM THE DATA, never typed. The 9/18/26 letter
    was headed "as of 9/8/26" while carrying the 9/15 report's figures; taking
    the date from the same rows as the numbers makes that impossible.
    """
    if not cftc or not cftc.get("markets"):
        return f"<h2>CFTC Report</h2>{_bullets([MISSING])}"
    as_of = cftc.get("as_of", "")
    try:
        y, m, d = as_of.split("-")
        stamp = f"{int(m)}/{int(d)}/{y[2:]}"
    except (ValueError, AttributeError):
        stamp = as_of

    rows = []
    for name in ("Live Cattle", "Feeder Cattle"):
        mk = cftc["markets"].get(name)
        if not mk:
            rows.append(f"{name}: {MISSING}")
            continue
        rows.append(f"{name}:")
        rows.append(f"Net Long: {head(mk.get('net_long'))} contracts")
        rows.append(f"WoW Change: {head(mk.get('wow'))} contracts")
    return (f"<h2>CFTC Report as of {_esc(stamp)}:</h2>"
            "<div>Managed Money Traders (Futures Only)</div>" + _bullets(rows))


def cof_block(cof: dict) -> str:
    """
    The monthly Cattle on Feed table, or nothing at all.

    Actual and Year-Ago come from cof_recap's computation, so On-Feed reads
    100.7 and the Year-Ago basis 98.9 where the old Excel sheet read 100.8 and
    99. Guesses are typed in -- USDA does not publish them and nothing derives
    them -- so a missing guess prints an em dash rather than a marked gap.
    """
    if not cof or not cof.get("include"):
        return ""
    actual, year_ago, guesses = cof.get("actual", {}), cof.get("year_ago", {}), cof.get("guesses", {})

    def cell(v):
        return "&mdash;" if v is None else f"{float(v):.1f}"

    # Labels and headers punctuated as the letter punctuates them: a trailing
    # hyphen on each row label, colons on the first two column heads but not on
    # Year-Ago. Copied from the 9/18/26 letter rather than tidied.
    rows = "".join(
        f"<tr><td>{label}-</td><td>{cell(actual.get(key))}</td>"
        f"<td>{cell(guesses.get(key))}</td><td>{cell(year_ago.get(key))}</td></tr>"
        for key, label in (("on_feed", "On-Feed"), ("placed", "Placed"), ("marketed", "Marketed"))
    )
    return (
        f"<h2>{_esc(cof.get('title') or 'COF Report')}</h2>"
        "<table class='cof'><thead><tr><th></th><th>Actual:</th><th>Guesses:</th>"
        "<th>Year-Ago</th></tr></thead><tbody>" + rows + "</tbody></table>"
    )


# -- Page ---------------------------------------------------------------------

CSS = """
/* THE PAGE MARGIN IS WHERE THE FRAME GOES, and the text is inset the rest of
   the way with padding. The obvious construct -- keep a 0.9in margin and push a
   fixed frame outward with NEGATIVE offsets -- renders in headless
   --print-to-pdf and is clipped when the same letter prints from inside the
   preview iframe, because a negative-offset fixed box is only safe in a root
   context. Printed from the app it simply vanished, with nothing to say why.
   No negative offsets anywhere now: the frame sits at inset 0, which is the
   page box, and the text is moved in from it. */
@page { size: letter; margin: 0.52in; }
* { box-sizing: border-box; }
body {
  font-family: Calibri, Carlito, "Segoe UI", system-ui, sans-serif;
  font-size: 11.5pt; line-height: 1.32; color: #000; margin: 0;
  /* Restores the original 0.9in / 0.85in text block exactly: 0.52 + 0.38 = 0.90
     down the page, 0.52 + 0.33 = 0.85 across. The measured one-page geometry is
     therefore unchanged -- 6.8in of text width, 9.2in of height. */
  padding: 0.38in 0.33in;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
/* Masthead is a row now: title left, logo hard right. baseline rather than
   center so the wordmark sits on the same line as the title rather than
   floating above it. */
.masthead { font-weight: 700; font-size: 13pt; margin: 0 0 14px;
            display: flex; align-items: baseline; justify-content: space-between;
            gap: 18px; }
.masthead img { height: 0.34in; width: auto; align-self: center; }
/* THE WATERMARK SITS BEHIND THE TEXT, not over it. z-index -1 puts it under
   the content, which only works because the page background lives on <html>
   -- put a background on <body> and this disappears underneath it.
   position:fixed so it is placed against the PAGE box in print, and it does
   not participate in layout at all, which is why letterhead costs the
   one-page brief nothing. */
html { background: #fff; }
/* THE FRAME COSTS NO LAYOUT, same trick as the watermark. position:fixed keeps
   it out of flow, so it cannot push the morning brief onto a second page, and
   in print Chrome positions it against the PAGE box -- hence the NEGATIVE
   offsets, which walk it out of the text area and into the margin. A frame
   drawn with a border on <body> would be in flow and would repaginate. */
.frame { position: fixed; z-index: -1; pointer-events: none; }
.wm { position: fixed; left: 50%; top: 46%; transform: translate(-50%, -50%);
      width: 4.4in; opacity: 0.07; z-index: -1; pointer-events: none; }
table.band { width: 100%; border-collapse: collapse; margin: 0 0 -10px; }
/* The two blocks sit TOGETHER on the left, not at opposite edges of the page.
   A 50/50 split put Cattle Futures at the horizontal midpoint and opened a
   lane of white space between two short lists. The first cell now shrinks to
   its own widest line -- width:1% with nowrap is the usual idiom for a
   shrink-to-fit table cell -- and the second takes the remainder, so the
   gutter is a deliberate 42px instead of whatever the page had left over. */
table.band > tr > td, table.band td { vertical-align: top; padding: 0; }
table.band td:first-child { width: 1%; white-space: nowrap; padding-right: 42px; }
table.band h2:first-child { margin-top: 0; }
table.band ul { margin-bottom: 0; }
.intro { margin: 0 0 14px; }
h2 { font-size: 11.5pt; font-weight: 700; margin: 16px 0 4px; }
/* A qualifier on a heading, not part of it: lighter and smaller so the
   heading still reads as one word at a glance. */
h2 .asof { font-weight: 400; font-size: 9.5pt; color: #444; }
h3 { font-size: 11.5pt; font-weight: 400; margin: 10px 0 3px; }
ul { margin: 0 0 4px; padding-left: 22px; }
li { margin: 1px 0; }
.missing {
  background: #ffe8a3; border: 1px solid #c79b12; color: #7a5c00;
  padding: 0 4px; border-radius: 3px; font-weight: 700;
}
table.cof { border-collapse: collapse; margin: 6px 0 4px; font-size: 11pt; }
table.cof th, table.cof td { padding: 1px 16px 1px 0; text-align: left; }
table.cof th { font-weight: 700; }
table.cof td:first-child { font-weight: 600; }
.signoff { margin: 18px 0 26px; }
/* THE CHART COSTS NO VERTICAL SPACE, and that is the only reason it is allowed
   on a one-page brief. Floated right before the sign-off, it drops into the
   band beside the signature block -- measured empty at 1.89in tall by 4.97in
   wide -- so the text flows up its left and the page does not grow. Make it
   taller than that band and the letter runs to two pages; a test checks. */
.dayplot-wrap { float: right; margin: 2px 0 6px 18px; }
.dayplot { display: block; }
/* One page is the product: a three-minute brief that spills its
   disclaimer onto a second sheet has stopped being one. Tightened for
   the morning only -- the evening letter keeps its roomier spacing. */
body.am h2 { margin: 12px 0 3px; }
body.am .intro { margin: 0 0 10px; }
body.am .signoff { margin: 14px 0 18px; }
body.am .sig .disclaimer { margin-top: 22px; }
/* The evening letter keeps its own page for the signature and the
   disclaimer, matching the printed letter clients already receive. The
   morning brief does not: it is one page, and pushing six lines of
   signature onto a second doubles a three-minute read. */
.sig { margin-top: 4px; }
.sig.own-page { page-break-before: always; }
.sig div { margin: 0; }
/* .sig .disclaimer, not .disclaimer: ".sig div" above is the more specific
   selector, so a bare .disclaimer rule loses to it and the margin-top is
   silently dropped -- which is why the risk text sat hard against the cell
   number with no gap at all. */
.sig .disclaimer {
  margin-top: 30px; font-size: 8pt; line-height: 1.35; color: #222; text-align: justify;
}
"""


# -- The morning brief --------------------------------------------------------
#
# Built to be read in under three minutes, which is the whole product. Every
# block earns its place or it comes out: a section that says the same thing for
# three weeks stops being read, and takes the ones around it with it.

def am_cattle_rows(ctx: dict, per_product: int = 2) -> list:
    """
    The two nearby Live Cattle and Feeder Cattle contracts.

    YESTERDAY'S SETTLE AND ITS MOVE, not a week-to-date change: CME livestock
    does not open until 08:30 Central, so at the hour this goes out there is no
    session of its own to report and the prior close is the number the day is
    measured from. The evening letter quotes the week instead, which is why this
    reads change_day where that reads change_week.
    """
    rows = []
    for key, tag in (("live_cattle", "LC"), ("feeder_cattle", "FC")):
        for con in (ctx.get(key) or [])[:per_product]:
            rows.append(f"{_esc(con['month'])} {tag}: "
                        f"{signed(con.get('change_day'))} at {price(con.get('settle'))}")
    return rows


def am_blocks(ctx: dict, c: dict) -> list:
    """The AM report's sections, in reading order."""
    out = []

    # 1. The index first -- it is JSA's own number and the reason to open this.
    fci = ctx.get("fci") or {}
    if config.INCLUDE_FEEDER_INDEX and fci.get("value") is not None:
        # Same shape as the overnight quotes -- change first, then "at", then
        # the price. One reading pattern for every number on the page.
        #
        # No date on the line: the heading says Estimate, the brief is dated at
        # the top, and a second date here is one more thing to read past.
        rows = [("Estimate: " + (f"{signed(fci['change'], 2)} at {money(fci['value'])}"
                                 if fci.get("change") is not None else money(fci["value"])))]
        # Basis against the front feeder contract: one number that frames the
        # whole feeder complex before the open. Cash minus futures, the usual
        # convention, so a negative basis means the board is over the index.
        front = (ctx.get("feeder_cattle") or [None])[0]
        if front and front.get("settle") is not None:
            basis = float(fci["value"]) - float(front["settle"])
            rows.append(f"{_esc(front['month'])} feeders: {price(front['settle'])}")
            rows.append(f"Basis: {signed(basis, 2)}")
        cattle = am_cattle_rows(ctx)
        left = "<h2>JSA FCI Estimate</h2>" + _bullets(rows)
        if cattle:
            # The heading says WHICH SESSION these settled in. The rows are
            # yesterday's close and yesterday's move -- see am_cattle_rows --
            # and on a page dated today that is worth saying once, next to the
            # numbers, rather than leaving the reader to assume.
            settled = _settle_stamp(ctx)
            head = "Cattle Futures"
            if settled:
                head += f' <span class="asof">Settlement on {settled}</span>'
            out.append(
                '<table class="band"><tr>'
                f'<td>{left}</td>'
                f'<td><h2>{head}</h2>{_bullets(cattle)}</td>'
                "</tr></table>")
        else:
            out.append(left)

    # 2. Headlines -- written, and where border status lives.
    if c.get("headlines"):
        out.append("<h2>Headlines</h2>" + _commentary(c["headlines"]))

    # 3. Overnight. Cattle do not trade overnight, so this is grain and macro.
    #    Month BEFORE the commodity: "Dec Corn", not "Corn Dec".
    markets = [m for m in (ctx.get("outside") or []) if m.get("price") is not None]
    if markets:
        rows = []
        for m in markets:
            fmt = eighths if m.get("style") == "eighths" else money
            chg = m.get("change")
            chg_txt = (("+" if chg >= 0 else "") + fmt(chg)) if chg is not None else MISSING
            # Change BEFORE the price, joined by "at" -- the same shape the
            # evening letter uses for cattle ("Oct: +1.025 at 220.70") and the
            # shape Ross asked for: "Dec Corn -8'6 at 528".
            rows.append(f"{_esc(m.get('month') or '')} {_esc(m['label'])}: "
                        f"{chg_txt} at {fmt(m['price'])}")
        out.append("<h2>Overnight Markets</h2>" + _bullets(rows))

    # 4. Yesterday, for anyone who did not read the evening letter. One line
    #    each, no LW/LY triples -- that density belongs in the PM report.
    rows = []
    # Week to date by state, in the letter's own shorthand:
    #   "Cash  NE 221.00-222.50 live, 350 dressed"
    # Only states that actually traded are listed -- naming four every morning
    # so three can say "Undefined" is three wasted lines.
    regions = (ctx.get("regional_cash") or {}).get("regions") or {}
    traded = [(n, r) for n, r in regions.items() if not r.get("undefined")]
    if traded:
        for name, r in traded:
            bits = []
            if r.get("live_low") is not None:
                bits.append(f"{trim_range(r['live_low'], r['live_high'])} live")
            if r.get("dressed_low") is not None:
                bits.append(f"{trim_range(r['dressed_low'], r['dressed_high'])} dressed")
            rows.append(f"{_esc(name)}: {' &middot; '.join(bits)}")
    elif regions:
        rows.append("No established test this week")

    # NO WEEKLY WEIGHTED AVERAGE HERE. LM_CT150's "this week" is the last
    # COMPLETED week, published after it ends -- so on a Wednesday morning it is
    # the previous week's average sitting next to this week's daily trade, which
    # is two different weeks on adjacent lines. The state ranges above are the
    # current week. The weighted average still leads the evening letter, where
    # "Last week's cash trade" says plainly which week it means.

    cut = ctx.get("cutout") or {}
    ch, se = cut.get("choice", {}), cut.get("select", {})
    if ch.get("value") is not None:
        rows.append(f"Cutout: Choice {money(ch['value'])} {signed(ch.get('change'), 2)} "
                    f"&middot; Select {money(se.get('value'))} {signed(se.get('change'), 2)}")
    dsl = ctx.get("daily_slaughter") or {}
    if dsl.get("current_day") is not None:
        rows.append(f"Slaughter: Daily {head_k(dsl['current_day'])} &middot; "
                    f"WTD {head_k(dsl.get('wtd'))} "
                    f"({head_k(dsl.get('wtd_week_ago'))} LW, {head_k(dsl.get('wtd_year_ago'))} LY)")
    if rows:
        out.append("<h2>Cash Trade</h2>" + _bullets(rows))

    # 5. The week's releases as ONE list, each with its date -- rather than a
    #    "Today" block and a "This Week" block. A reader scanning for whether
    #    anything prints today finds it in the same place either way, and one
    #    list is a shorter read than two headings.
    items = (ctx.get("calendar") or {}).get("items") or []
    rows = [f"{_esc(i['label'])}: {_esc(i['when'])}"
            + (" <strong>(today)</strong>" if i.get("is_today") else "")
            for i in items]
    out.append("<h2>Upcoming USDA Reports</h2>"
               + _bullets(rows or ["None scheduled"]))
    return out


def _signature_html(issue, own_page: bool = True) -> str:
    """The signature and disclaimer. Identical in every session and format."""
    s = config.SIGNATURE
    return (
        f'<div class="sig{" own-page" if own_page else ""}">'
        f'<div>{_esc(s["name"])}</div>'
        f'<div>{_esc(s["company"])}</div>'
        f'<div>{_esc(s["city"])}</div>'
        f'<div>{_esc(s["web"])}</div>'
        f'<div>Office: {_esc(s["office"])}</div>'
        f'<div>Cell: {_esc(s["cell"])}</div>'
        f'<div class="disclaimer">{_esc(config.DISCLAIMER.format(year=issue.year))}</div>'
        '</div>'
    )


def _page(title: str, stamp: str, body: list, body_class: str = "") -> str:
    cls = f' class="{body_class}"' if body_class else ""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(title)} {stamp}</title>"
        f"<style>{CSS}</style></head><body{cls}>" + "".join(body) + "</body></html>"
    )


def build_html(ctx: dict) -> str:
    """ctx carries the fetched data plus the commentary sections."""
    issue: date = ctx["issue_date"]
    c = ctx["commentary"]
    # Built by hand rather than with strftime: the letter uses unpadded 9/18/26,
    # and the "%-m" that produces on Linux raises ValueError on Windows, which is
    # where this actually runs.
    stamp = f"{issue.month}/{issue.day}/{issue.strftime('%y')}"

    # The two letters open differently: Tuesday reports the week so far, Friday
    # the week just closed.
    kind = ctx.get("kind", "tuesday")
    # The masthead names the SESSION -- "JSA AM Daily Cattle Report" against
    # "JSA PM Daily Cattle Report". Two reports a day, two names.
    title = config.title_for(ctx.get("session", config.DEFAULT_SESSION))
    # There is no close to report at 07:30, so the AM letter cannot use either
    # evening opening.
    if kind == "am":
        intro = config.INTRO_AM.format(stamp=stamp)
        sign_off = config.SIGN_OFF_AM
    elif kind == "friday":
        intro, sign_off = f"For the week of {stamp}:", config.SIGN_OFF_FRIDAY
    else:
        intro = f"For the week through the close on {stamp}:"
        sign_off = config.SIGN_OFF_TUESDAY

    # An empty intro renders nothing rather than an empty paragraph -- see
    # config.INTRO_AM, which is blank because the masthead already said it.
    # Letterhead on every letter, AM and PM alike -- it is the same company
    # writing. Both images are embedded; see _asset_uri.
    _logo, _mark = _asset_uri("logo-full.png"), _asset_uri("jsa-50-years.png")
    head = []
    if getattr(config, "FRAME", ""):

        head.append(
            f'<div class="frame" style="top:0;right:0;bottom:0;left:0;'
            f'border:{config.FRAME_WIDTH} solid {config.FRAME};"></div>')
    if _mark:
        head.append(f'<img class="wm" src="{_mark}" alt="">')
    head.append(
        f'<div class="masthead"><span>{_esc(title)} {stamp}</span>'
        + (f'<img src="{_logo}" alt="John Stewart and Associates">' if _logo else "")
        + '</div>')
    if intro:
        head.append(f'<p class="intro">{_esc(intro)}</p>')

    body = head + [
        futures_block("Live Cattle", ctx["live_cattle"], ctx["change_basis"]),
        futures_block("Feeder Cattle", ctx["feeder_cattle"], ctx["change_basis"]),
    ]

    # THE MORNING REPORT ENDS HERE. It is described as much simpler and shorter
    # than any evening letter, and most of what follows does not exist at 07:30
    # anyway -- no completed session to recap, no PM cutout, no settle for today.
    # Returning early rather than opting out section by section means a section
    # added to the PM letter later cannot silently appear in the AM one.
    #
    # SETTLED 2026-09-23, after Ross reviewed it section by section: the index
    # and its basis, the cattle board, his Headlines, the overnight grain and
    # macro quotes, week-to-date cash by state, and the month's USDA reports.
    # One page, under three minutes, and that budget is the product -- a section
    # added here has to earn its place against the reading time, not just fit.
    if kind == "am":
        body = list(head)                  # masthead, and the intro if there is one
        body.extend(am_blocks(ctx, c))
        # BEFORE the sign-off in source order, which is what puts a float in the
        # bottom-right corner: everything after it flows up its left side.
        body.append(chart_mod.chart_block(ctx.get("chart")))
        body.append(f'<p class="signoff">{_esc(sign_off)}</p>')
        body.append(_signature_html(issue, own_page=False))
        return _page(title, stamp, body, body_class="am")

    # HEADLINES LEAD, then the session recap. Friday has led with Key Headlines
    # since it was written and the morning brief leads with Headlines; as of
    # 2026-09-23 the standard evening letter does too, so all three open on what
    # happened before they explain it.
    #
    # Friday is still EITHER/OR rather than both: its Key Headlines section
    # replaced Market Action, and that format has no market_action key to render.
    if kind == "friday":
        if c.get("key_headlines"):
            body.append("<h2>Key Headlines</h2>" + _commentary(c["key_headlines"]))
    else:
        if c.get("headlines"):
            body.append("<h2>Headlines</h2>" + _commentary(c["headlines"]))
        if c.get("market_action"):
            body.append("<h2>Market Action</h2>" + _commentary(c["market_action"]))

    tech_lc = technicals_block(ctx.get("tech_lc"), c.get("technicals_lc", []), "Live Cattle")
    tech_fc = technicals_block(ctx.get("tech_fc"), c.get("technicals_fc", []), "Feeders")
    if tech_lc or tech_fc:
        body.append("<h2>Technicals</h2>" + tech_lc + tech_fc)

    if kind == "friday":
        # Friday drops the five-bullet weekly cash block and carries the
        # current-week regional ranges instead, further down.
        body.append(friday_rundown_block(ctx.get("fci"), ctx["slaughter"], ctx["cutout"],
                                         ctx.get("daily_slaughter"), ctx.get("carcass_weights")))
        body.append(cash_cattle_block(ctx.get("regional_cash")))
        if c.get("cash_recap"):
            body.append("<h2>Cash Trade Recap:</h2>" + _commentary(c["cash_recap"]))
        body.append(cftc_block(ctx.get("cftc")))
        cof_html = cof_block(ctx.get("cof"))
        if cof_html:
            body.append(cof_html)
            if c.get("cof_note"):
                body.append(_commentary(c["cof_note"]))
    else:
        body.append(cash_trade_block(ctx["cash"]))
        body.append(rundown_block(ctx.get("fci"), ctx["slaughter"], ctx["cutout"],
                                  ctx.get("daily_slaughter"), ctx.get("carcass_weights")))
        if c.get("fundamental"):
            body.append("<h2>Fundamental Rundown</h2>" + _commentary(c["fundamental"]))

    body.append(f'<p class="signoff">{_esc(sign_off)}</p>')
    body.append(_signature_html(issue))
    return _page(title, stamp, body)
