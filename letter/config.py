"""
Masthead, branding and the handful of choices the letter's content depends on.

Everything a human would want to change without reading code lives here.
"""
from __future__ import annotations

# ── Masthead ─────────────────────────────────────────────────────────────────
# The 9/18/26 PDF went out as "AgMarket.Net Cattle Report", which became
# "JSA Livestock Update". Both spellings are kept so a revert is one edit.
TITLE = "JSA Livestock Update"
TITLE_PREVIOUS = "AgMarket.Net Cattle Report"

# ── AM and PM ────────────────────────────────────────────────────────────────
# Two reports a day, not one. PM is everything built so far: written after the
# close, and the rundown is a recap of a session that has finished.
#
# AM is a different animal, and the difference is imposed by the clock rather
# than by choice. At 07:30 there is no settle, no PM cutout, and no completed
# session to recap -- what IS fresh is the morning feeder index call that the
# daily run freezes into fci_snapshots, which CLAUDE.md records as "the number
# that goes out, and the one comparable to CIH's and Compass's morning sheets".
#
# AM_SECTIONS is therefore NOT yet the real thing: it mirrors PM until the
# actual morning format is known. Do not assume it is right.
SESSIONS = ["AM", "PM"]
DEFAULT_SESSION = "PM"

# ── Which report the authoring page opens on ─────────────────────────────────
# Before noon you are writing the morning brief; after it, the evening letter.
# One number to move if that split is ever wrong.
SESSION_SWITCH_HOUR = 12

# CENTRAL, NOT THE SERVER'S CLOCK, and this is the whole difficulty. Streamlit
# Cloud runs UTC, where 07:30 in Anthon is 12:30 -- already past the switch --
# so a plain datetime.now() would open on PM every single morning, which is
# exactly the case this exists to get right. Reading a named zone also keeps
# DST correct without a second thought.
LETTER_TZ = "America/Chicago"


def session_for_now(now=None) -> str:
    """
    "AM" or "PM" by the clock in Anthon.

    Never raises. A host with no tz database falls back to DEFAULT_SESSION,
    which costs one click rather than a page -- and `now` is injectable so the
    behaviour is testable without waiting for the afternoon.
    """
    if now is None:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(LETTER_TZ))
        except Exception:
            return DEFAULT_SESSION
    return "AM" if now.hour < SESSION_SWITCH_HOUR else "PM"

TITLE_BY_SESSION = {
    "am": "JSA AM Daily Cattle Report",
    "pm": "JSA PM Daily Cattle Report",
}


def title_for(session: str = DEFAULT_SESSION) -> str:
    return TITLE_BY_SESSION.get(str(session).strip().lower(), TITLE)

# ── The page frame ───────────────────────────────────────────────────────────
# A hairline rule around the letter, in the sage from the JSA monogram
# (#5e7164, the same value the dashboards use). Set FRAME to "" to drop it.
#
# HAIRLINE AND SAGE, NOT BLACK AND BOLD. A heavy box around a business letter
# reads as a certificate. At 0.75pt in the brand colour it reads as stationery,
# which is the point -- it should be the last thing noticed, not the first.
FRAME = "#5e7164"
FRAME_WIDTH = "0.75pt"
# The frame is drawn at the PAGE MARGIN (see @page in render.py, 0.52in) and the
# text is padded in from there, so there is no inset to set here any more --
# move the @page margin and the body padding together if the frame should sit
# further in or out.

# ── Signature block (page 3 of the printed letter) ───────────────────────────
SIGNATURE = {
    "name": "Ross Baldwin",
    "company": "John Stewart and Associates",
    "city": "Anthon, IA",
    "web": "www.jpsi.com",
    "office": "712-373-3276",
    "cell": "712-870-0556",
}

SIGN_OFF_TUESDAY = "Have a good evening,"
# The morning report's own wording. Never explicitly chosen -- they were neutral
# stand-ins for "Have a good evening", which is plainly wrong on a 07:30 report
# -- but they have survived several rounds of review without comment, so treat
# them as accepted rather than pending. One edit each to change.
SIGN_OFF_AM = "Have a good day,"
# EMPTY ON PURPOSE, 2026-09-24. This read "Morning report for {stamp}:" directly
# under a masthead reading "JSA AM Daily Cattle Report 9/24/26" -- the same two
# facts twice, at the top of a brief whose whole budget is three minutes.
#
# The evening intros are NOT redundant and stay: "For the week through the close
# on 9/24/26" names the PERIOD the letter covers, which its masthead does not.
# The morning brief covers one morning, and the masthead already said which.
#
# Put a string back here and it renders again; the renderer skips it when empty.
INTRO_AM = ""
SIGN_OFF_FRIDAY = "Have a good weekend,"

# The recap letter opens on nothing, for the reason INTRO_AM is empty: the
# masthead already reads "JSA PM Daily Cattle Report 9/24/26", and unlike the
# Tuesday and Friday intros there is no PERIOD to name -- a recap covers the
# session its date already gives. Put a string here and it renders.
INTRO_RECAP = ""

# Verbatim from the 9/18/26 PDF. Reproduced exactly -- this is the compliance
# text, not prose, so it is never regenerated or reflowed.
DISCLAIMER = (
    "Trading commodity futures, options on futures, cash commodities, and "
    "over-the-counter derivative products involves substantial risk of loss and "
    "may not be suitable for all investors. This communication is provided for "
    "informational purposes only and does not constitute investment advice, a "
    "recommendation, or an offer or solicitation to buy or sell any futures, "
    "options, cash commodities, or derivative products. John Stewart & "
    "Associates, Inc. does not accept orders to buy or sell any financial "
    "instruments via email. The information contained herein has been obtained "
    "from sources believed to be reliable; however, its accuracy and "
    "completeness are not guaranteed. Any opinions expressed are solely those of "
    "the author, are subject to change without notice, and should not be relied "
    "upon as a basis for investment decisions. Past performance is not "
    "indicative of future results. This message may contain confidential or "
    "proprietary information intended solely for the use of the designated "
    "recipient. © John Stewart & Associates, Inc. {year}"
)

# ── Which format each weekday uses ───────────────────────────────────────────
# There are TWO letter formats, not five. Friday is the week-in-review -- it
# drops the weekly cash block, expands the rundown with the completed week and
# both YTD rates, and adds regional cash, CFTC and the monthly Cattle on Feed
# table. Every other weekday uses the standard format, which is the one the
# Tuesday letter has always used.
#
# The format ids stay "tuesday" and "friday" because that is what render.py and
# commentary.py switch on, and what the existing drafts and tests are keyed by.
# The DAY is what you pick; the format is what it produces.
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# THREE PM FORMATS. The full letter opens the week on MONDAY, the recap carries
# Tuesday through Thursday, and Friday is the week-in-review. Moved here from
# Monday/Tuesday on 2026-09-24 at Ross's request -- the long letter belongs at
# the start of the week, and the three middle days are alike.
#
# THE FORMAT ID "tuesday" NOW RUNS ONLY ON MONDAY, which is as confusing as it
# sounds. The ids are historical: they are what render.py, commentary.py, the
# tests and the stored drafts all switch on, and renaming one touches thirty-odd
# places for no behaviour change. They are internal -- draft files are named by
# the DAY (commentary_pm_monday_<date>.md), so the mismatch never reaches a
# filename or the page. Read the id as a LAYOUT NAME with an unfortunate
# spelling: "tuesday" is the full letter, "recap" the short one.
FORMAT_FOR_DAY = {
    "monday": "tuesday",
    "tuesday": "recap",
    "wednesday": "recap",
    "thursday": "recap",
    "friday": "friday",
}


def format_for(day: str, session: str = "pm") -> str:
    """
    Which layout a (day, session) pair produces.

    THE AM REPORT HAS ONE FORMAT, ALL FIVE DAYS. It does not switch to the
    week-in-review on a Friday the way the PM report does -- there is no week to
    review at 07:30, and the morning note is deliberately shorter than any of
    the evening ones. So the day only selects a format in the PM session.
    """
    if str(session).strip().lower() == "am":
        return "am"
    return FORMAT_FOR_DAY.get(str(day).strip().lower(), "tuesday")


def day_for_date(d) -> str:
    """The weekday name a date falls on, clamped to a working day."""
    name = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "friday", "monday"][d.weekday()]
    return name


# ── Futures ──────────────────────────────────────────────────────────────────
# CME product codes as Massive spells them. The letter always leads with the
# front THREE outright contracts, which is what makes Oct/Dec/Feb (Live Cattle)
# and Sep/Oct/Nov (Feeders) fall out on their own -- those are simply the
# nearest three listed months for each product. Nothing here needs editing at a
# contract roll.
LIVE_CATTLE_CODE = "LE"
FEEDER_CATTLE_CODE = "GF"
N_CONTRACTS = 3

# ── Chart of the day (morning brief) ─────────────────────────────────────────
# Sessions on the bottom-right chart. 60 is about a quarter -- long enough to
# show the trend the letter is describing, short enough that 3.1 inches of width
# is still one readable line rather than a smear.
CHART_SESSIONS = 60

# The pool, and the words that make each one the RIGHT chart for a given
# morning. A different chart every day was the ask; picking it from what the
# letter is actually about is better than picking it at random, and costs one
# scan of the text Ross already typed.
#
# WORDS ARE PHRASES WHERE THE BARE WORD IS AMBIGUOUS. "fed" is fed cattle here
# and the Federal Reserve three lines down, so neither owns it -- "fed cattle"
# and "federal reserve" do. "basis" belongs to feeders because that is the basis
# this letter quotes. Getting this wrong costs a slightly-off chart, not a wrong
# number, which is why it is allowed to be a heuristic at all.
# HOW MUCH EACH SOURCE'S HEADLINE COUNTS when the chart is picked from the day's
# candidate list rather than from what Ross typed. Twenty-two headlines spanning
# Tyson, screwworm, corn and equities is a muddy signal, and without weighting
# the topic with the most STORIES wins -- which is not the same as the topic that
# matters. USDA is writing about this market specifically and is never
# speculative; the trade press is close behind; a general newsroom covering
# cattle at all is notable but it is one desk among many.
#
# Matched on a lowercase substring of the source name, so a new outlet lands on
# the default rather than needing an entry here.
CHART_SOURCE_WEIGHTS = {"usda": 3.0}
CHART_TRADE_SOURCES = (
    "beef magazine", "drovers", "meatingplace", "emeat", "global agritrends",
    "sterling", "meat+poultry", "brownfield", "northern ag", "agweb",
    "feedstuffs", "wattpoultry", "ag proud", "farm", "cattle",
)
CHART_TRADE_WEIGHT = 2.0
CHART_DEFAULT_SOURCE_WEIGHT = 1.0

CHART_POOL = [
    {"key": "feeders", "label": "Feeder Cattle", "code": FEEDER_CATTLE_CODE,
     "style": "decimal",
     "words": ("feeder", "calf", "calves", "stocker", "basis", "placement",
               "grazing", "wheat pasture", "feeder index",
               # The border story IS a feeder story -- Mexican cattle crossing
               # at Douglas are feeders, which is why the portal has a whole
               # dashboard for it. "import" is left out on purpose: beef imports
               # belong to the fed cattle side.
               "mexic", "screwworm", "border")},
    {"key": "live", "label": "Live Cattle", "code": LIVE_CATTLE_CODE,
     "style": "decimal",
     "words": ("fed cattle", "live cattle", "fat cattle", "packer", "slaughter",
               "cutout", "boxed", "carcass", "kill floor",
               # The packers BY NAME. headlines._RELEVANT has carried these
               # since the Kansas miss, and leaving them out here meant three
               # Tyson plant stories in one morning's candidate list scored
               # zero for Live Cattle. A packer story is a fed cattle story.
               "tyson", "jbs", "cargill", "national beef", "beef plant",
               "meatpacking", "packing plant")},
    {"key": "corn", "label": "Corn", "code": "ZC", "style": "eighths",
     "words": ("corn", "feed cost", "ration", "cost of gain", "grain", "bushel",
               "harvest", "new crop", "yield")},
    {"key": "sp", "label": "S&P", "code": "ES", "style": "decimal",
     "words": ("equit", "stock market", "s&p", "wall street", "risk-off",
               "risk off", "federal reserve", "macro", "recession")},
    {"key": "crude", "label": "Crude", "code": "CL", "style": "decimal",
     "words": ("crude", "oil", "energy", "diesel", "fuel", "opec", "gasoline")},
]

# WHICH NET CHANGE THE EVENING LETTER QUOTES -- CONFIRMED 2026-09-23.
#
# Checked against the letter Ross sent for 9/22/26. Every one of the six
# contracts is the settle minus the PRIOR FRIDAY'S settle, exact to the
# thousandth:
#
#   Oct LC  218.775 - 215.925 = +2.85     Sep FC  337.275 - 333.575 = +3.70
#   Dec LC  219.450 - 216.625 = +2.825    Oct FC  328.025 - 323.500 = +4.525
#   Feb LC  220.550 - 217.350 = +3.20     Nov FC  323.200 - 318.000 = +5.20
#
# So "week", not "day". build.py still writes BOTH into the data cache, which is
# what made the check possible and is worth keeping.
#
# THE MORNING BRIEF IS DIFFERENT and does not read this: it quotes the prior
# session's move, because CME livestock does not open until 08:30 Central and a
# week-to-date figure is not what a reader wants before the bell.
CHANGE_BASIS = "week"      # "week" | "day"

# Moving averages the Technicals section quotes.
MA_WINDOWS = (9, 20)

# ── Feeder cattle index ──────────────────────────────────────────────────────
# The letter quotes JSA'S OWN index estimate, read from fci_daily -- the number
# the CME Feeder Cattle Index dashboard headlines. See sources.fetch_feeder_index.
#
# This is the point of the distinction. notify_email.py in the
# cme-feeder-cattle-index repo records that CME licenses ITS PUBLISHED VALUES to
# JSA for internal display and non-display use, and that putting those in a
# client communication needs a separate agreement. The letter is a client
# communication, so it prints JSA's reconstruction instead -- JSA's own work
# product. CME's published series is still read, but only for its DATE, to pick
# which of our estimates is the headline.
#
# Set to False to drop the line entirely.
INCLUDE_FEEDER_INDEX = True
