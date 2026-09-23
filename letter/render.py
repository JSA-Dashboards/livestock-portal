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

from . import config

MISSING = '<span class="missing">[[?]]</span>'


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


_PM_DAYS = {0: "Mon", 1: "Tues", 2: "Wed", 3: "Thurs", 4: "Fri", 5: "Sat", 6: "Sun"}


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

    rows = "".join(
        f"<tr><td>{label}</td><td>{cell(actual.get(key))}</td>"
        f"<td>{cell(guesses.get(key))}</td><td>{cell(year_ago.get(key))}</td></tr>"
        for key, label in (("on_feed", "On-Feed"), ("placed", "Placed"), ("marketed", "Marketed"))
    )
    return (
        f"<h2>{_esc(cof.get('title') or 'COF Report')}</h2>"
        "<table class='cof'><thead><tr><th></th><th>Actual</th><th>Guesses</th>"
        "<th>Year-Ago</th></tr></thead><tbody>" + rows + "</tbody></table>"
    )


# -- Page ---------------------------------------------------------------------

CSS = """
@page { size: letter; margin: 0.9in 0.85in; }
* { box-sizing: border-box; }
body {
  font-family: Calibri, Carlito, "Segoe UI", system-ui, sans-serif;
  font-size: 11.5pt; line-height: 1.32; color: #000; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.masthead { font-weight: 700; font-size: 13pt; margin: 0 0 14px; }
.intro { margin: 0 0 14px; }
h2 { font-size: 11.5pt; font-weight: 700; margin: 16px 0 4px; }
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
.signoff { margin: 18px 0 0; }
.sig { page-break-before: always; margin-top: 4px; }
.sig div { margin: 0; }
.disclaimer {
  margin-top: 26px; font-size: 8pt; line-height: 1.35; color: #222; text-align: justify;
}
"""


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
    intro = (f"For the week of {stamp}:" if kind == "friday"
             else f"For the week through the close on {stamp}:")
    sign_off = (config.SIGN_OFF_FRIDAY if kind == "friday" else config.SIGN_OFF_TUESDAY)

    body = [
        f'<div class="masthead">{_esc(config.TITLE)} {stamp}</div>',
        f'<p class="intro">{_esc(intro)}</p>',
        futures_block("Live Cattle", ctx["live_cattle"], ctx["change_basis"]),
        futures_block("Feeder Cattle", ctx["feeder_cattle"], ctx["change_basis"]),
    ]

    if kind == "friday" and c.get("key_headlines"):
        body.append("<h2>Key Headlines</h2>" + _commentary(c["key_headlines"]))
    elif c.get("market_action"):
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

    s = config.SIGNATURE
    body.append(
        '<div class="sig">'
        f'<div>{_esc(s["name"])}</div>'
        f'<div>{_esc(s["company"])}</div>'
        f'<div>{_esc(s["city"])}</div>'
        f'<div>{_esc(s["web"])}</div>'
        f'<div>Office: {_esc(s["office"])}</div>'
        f'<div>Cell: {_esc(s["cell"])}</div>'
        f'<div class="disclaimer">{_esc(config.DISCLAIMER.format(year=issue.year))}</div>'
        '</div>'
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(config.TITLE)} {stamp}</title>"
        f"<style>{CSS}</style></head><body>" + "".join(body) + "</body></html>"
    )
