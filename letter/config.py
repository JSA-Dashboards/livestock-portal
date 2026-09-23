"""
Masthead, branding and the handful of choices the letter's content depends on.

Everything a human would want to change without reading code lives here.
"""
from __future__ import annotations

# ── Masthead ─────────────────────────────────────────────────────────────────
# The 9/18/26 PDF went out as "AgMarket.Net Cattle Report". Ross is renaming it
# to "JSA Livestock Update"; both spellings are kept so the switch is one edit
# and the old name is recoverable if the rename is deferred.
TITLE = "JSA Livestock Update"
TITLE_PREVIOUS = "AgMarket.Net Cattle Report"

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
SIGN_OFF_FRIDAY = "Have a good weekend,"

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

FORMAT_FOR_DAY = {
    "monday": "tuesday",
    "tuesday": "tuesday",
    "wednesday": "tuesday",
    "thursday": "tuesday",
    "friday": "friday",
}


def format_for(day: str) -> str:
    """'wednesday' -> 'tuesday' (the standard format). Unknown days fall back."""
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

# WHICH NET CHANGE THE LETTER QUOTES -- UNCONFIRMED, PLEASE VERIFY.
#
# Tuesday's letter is headed "for the week through the close on 9/15/26", which
# reads as a week-to-date change (prior Friday's settle to the latest settle)
# rather than a one-session change. That is the assumption here, but it was
# inferred from the heading, never confirmed. build.py writes BOTH figures into
# out/data_<date>.json under "change_week" and "change_day" so the first run can
# be checked against a letter you already sent; flip this if "day" is right.
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
