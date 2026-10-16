"""
Backgrounding Crush -- buy calves, put weight on them, sell feeders.

Same shape as the Fed Cattle Crush, different trade. There the question is
"what can I bid for feeders against the fed cattle board". Here it is "what can
I bid for CALVES against the feeder board", and the answer turns on one number
the fed version does not have:

    VALUE OF GAIN = (revenue - calf cost) / gain

What each hundredweight you put on is actually worth when you sell. Beat it
with your cost of gain and you make money; that is the entire trade. Profit per
head follows from it, but value of gain is the number a backgrounder decides
on, because it is directly comparable to a forage or grower-ration cost.

DEATH LOSS IS INSIDE THE COST OF GAIN. There is no death loss field: the page
describes what is in that number rather than asking for it or charging it
again, so nothing about death loss reaches total cost, profit or the
value-of-gain comparison, and profit per head stays exactly
(value of gain - cost of gain) x gain. Why it is worth describing: death loss
is a percentage of the PURCHASE price, so its share of a cost of gain moves
with the calf market and not with the ration -- the same 1% that cost about
$3.50/cwt of gain at $180 calves costs nearer $8.65 at today's, which is how
a cost of gain carried over from a cheaper year ends up understated.

WHY THE TWO LEGS COME FROM DIFFERENT PLACES.

  BUY  calves, 400-650 lb. There is no futures contract for a 500 lb calf --
       CME's feeder index starts at 700 lb -- so the buy side can only come
       from cash auction data. That is calf_sales, ingested from the same AMS
       barn reports behind the index, over the weight brackets the index
       discards.

  SELL feeders, 700-899 lb, months out. That IS the CME Feeder Cattle contract,
       so the sell leg prices off GF at the sale date plus a feeder basis --
       forward-looking and hedgeable, exactly as the fed cattle version prices
       its sale off Live Cattle.

Pricing the sale off today's cash feeder market instead would answer a question
nobody asked: a backgrounder selling in February cares what February feeders
are worth, not what they fetched this week.

THE CALF PRICE DEFAULT comes from the bracket that matches the entered start
weight, so changing start weight re-prices the calf. It is a starting point:
cash calf markets vary enormously by quality, fill, lot size and barn, and the
number to trust is the one the buyer knows for their own cattle.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

import cash_calves
from massive_api import MassiveApiError, get_futures_curve

JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
BG        = "#f6f8f7"
CARD_BG   = "#ffffff"
SURFACE2  = "#eef3f0"
BORDER    = "#d7e2dc"
MUTED     = "#5f7267"
TEXT      = "#32373c"
POS       = "#16a34a"
NEG       = "#dc2626"
AMBER     = "#d97706"

MONTH_LETTERS = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                 "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
MONTH_NAME = dict(zip(range(1, 13),
                      ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]))

# Backgrounding, not finishing: forage or a grower ration, lower daily gain,
# shorter than a feedyard. Starting points, all editable.
#
# COST OF GAIN IS NOT CHEAPER THAN FINISHING, which this page asserted at $95
# until it was checked. Iowa State's Livestock Enterprise Budgets for Iowa-2026
# (FM 1815 / B1-21) put all six of their beef systems within $4.43/cwt of each
# other -- backgrounding winter drylot $111.37, backgrounding summer pasture
# $109.40, and the four finishing systems $106.94 to $110.52. $95 sat below
# every one of them.
#
# The reason backgrounding is not cheaper is arithmetic, not agronomy: every
# per-head and per-day cost is spread over half as many pounds. At 2.0 ADG a
# $0.50/hd/day yardage is $25.00/cwt of gain against $15.38 at 3.25, and feed
# conversion does not rescue it -- a medium-frame steer runs 6.6:1 DM at 500 lb
# and 8.4:1 at 700 lb (UNL G2064), WORSE than a finishing closeout's 6.0-6.5:1.
#
# Backgrounding gain is cheap when it is cheap because the feed costs $114-134
# a ton of dry matter instead of $217 -- not because of conversion, and not
# because of corn.
#
# The one honest exception is worth knowing: strip out interest on the purchased
# calf and summer pasture backgrounding IS the cheapest gain in the book at
# $75.40/cwt. At today's calf values that interest line is enormous, so whether
# backgrounding looks cheap depends almost entirely on whether you charge it --
# which is exactly why the build-up shows it as its own line.
#
# DEATH LOSS IS INSIDE THAT $110 AND THE PAGE ONLY DESCRIBES IT. Two wrong
# versions shipped on 2026-10-16 before this one, both pulled at Ross's call:
# a cost line on top, which double counted because ISU's $109-111 is ALL-IN
# and carries death loss; then an input that split the $110 instead, which was
# arithmetically harmless and still wrong, because a control that changes no
# figure on the page is a control that misleads about what it does. What was
# wanted was the NOTE -- see DEATH_LOSS_PCT below.
#
# Two lessons worth keeping. A tile or a line that names a cost and sits
# beside other costs WILL be added on, whatever the help text says. And if
# this ever needs to CHARGE death loss rather than describe it, the cost of
# gain default has to come down to the feed/yardage/health/interest figure
# (~$102) in the same change, not afterwards.
DEFAULTS = {
    "start_wt": 525.0,
    "sell_wt": 800.0,
    "adg": 2.00,       # grower/forage, against ~3.25 in a feedyard
    "cog": 110.0,      # $/cwt of gain, ALL-IN incl. death loss -- ISU 2026, see above
    "basis": -2.00,    # feeder cash typically under the board
}

# THE RATE THE NOTE IS WORKED AT, AND IT IS NOT A FIELD. Death loss shipped as
# an input twice on 2026-10-16 -- first charging on top of the cost of gain,
# then splitting it -- and was removed both times. The second removal is the
# one to understand, because the field did no arithmetic harm: a box a user
# can change, sitting under a box it cannot change, reads as an input to the
# answer. It was not one. Every figure on this page is identical at any death
# rate, so the box could only mislead about what it was doing.
#
# What was actually wanted is the NOTE: cost of gain is all-in, death loss is
# in there, and here is roughly how much. That needs one representative rate,
# not a control. 1% is fair on cattle you know; the note says so and says to
# raise the cost of gain for cattle you do not.
DEATH_LOSS_PCT = 1.0

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{ background-color:{BG}; color:{TEXT}; }}
  [data-testid="stSidebar"] {{ background-color:{SURFACE2}; border-right:1px solid {BORDER}; }}
  .tile {{
    background:{CARD_BG}; border:1px solid {BORDER}; border-top:3px solid {JPSI_BLUE};
    border-radius:10px; padding:16px 20px; text-align:center; height:100%;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .tile-pos {{ border-top-color:{POS}; }}
  .tile-neg {{ border-top-color:{NEG}; }}
  .tile-label {{
    color:{MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{ color:{TEXT}; font-size:1.7rem; font-weight:700; line-height:1.1; }}
  .tile-value-pos {{ color:{POS}; }}
  .tile-value-neg {{ color:{NEG}; }}
  .tile-sub {{ color:{MUTED}; font-size:0.72rem; margin-top:5px; }}
  .sec-header {{
    color:{MUTED}; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.1em;
    padding:8px 0 4px; border-bottom:1px solid {BORDER}; margin-bottom:10px;
  }}
  .fld-label {{
    text-align:right; color:{TEXT}; font-size:0.86rem; font-weight:600;
    padding-top:0.55rem; line-height:1.2;
  }}
  .fld-row {{
    display:flex; align-items:baseline; gap:12px; padding:5px 0;
    border-top:1px solid {BORDER};
  }}
  .fld-row .fld-label {{ flex:0 0 46%; padding-top:0; }}
  .fld-derived {{ color:{TEXT}; font-size:1.0rem; font-weight:700; }}
  .fld-note {{
    display:block; color:{MUTED}; font-size:0.68rem; font-weight:400; margin-top:1px;
  }}
  .be-line {{ color:{MUTED}; font-size:0.82rem; margin:0 0 4px 2px; }}
  .be-line b {{ color:{TEXT}; font-size:0.95rem; }}
  .profit-box {{ border-radius:12px; padding:14px 18px; margin-top:10px; text-align:center; }}
  .profit-pos {{ background:{POS}; }}
  .profit-neg {{ background:{NEG}; }}
  .profit-label {{
    color:rgba(255,255,255,0.92); font-size:0.72rem; font-weight:700;
    text-transform:uppercase; letter-spacing:0.12em;
  }}
  .profit-value {{ color:#ffffff; font-size:2.1rem; font-weight:800; line-height:1.15; }}
  .profit-unit {{ font-size:1.0rem; font-weight:600; opacity:0.9; }}
  .vog {{
    border-radius:10px; padding:12px 16px; margin-top:10px;
    border:1px solid {BORDER}; background:{CARD_BG};
  }}
  .vog-lab {{ color:{MUTED}; font-size:0.68rem; text-transform:uppercase;
              letter-spacing:0.09em; }}
  .vog-val {{ font-size:1.5rem; font-weight:800; }}
  .srcline {{ color:{MUTED}; font-size:0.72rem; line-height:1.6; }}
  hr {{ border-color:{BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
</style>
""", unsafe_allow_html=True)


def tile(label, value, sub_="", kind=""):
    vc = {"pos": " tile-value-pos", "neg": " tile-value-neg"}.get(kind, "")
    tc = {"pos": " tile-pos", "neg": " tile-neg"}.get(kind, "")
    s = f'<div class="tile-sub">{sub_}</div>' if sub_ else ""
    return (f'<div class="tile{tc}"><div class="tile-label">{label}</div>'
            f'<div class="tile-value{vc}">{value}</div>{s}</div>')


def get_api_key() -> str:
    import os
    try:
        k = st.secrets.get("MASSIVE_API_KEY", "")
    except Exception:
        k = ""
    return k or os.environ.get("MASSIVE_API_KEY", "")


def contract_month(ticker, code):
    suffix = ticker[len(code):]
    if len(suffix) < 2 or suffix[0] not in MONTH_LETTERS:
        return None
    m = MONTH_LETTERS[suffix[0]]
    try:
        d = int(suffix[1:])
    except ValueError:
        return None
    base = date.today().year
    y = (base // 10) * 10 + d if d < 10 else 2000 + d
    while y < base - 1:
        y += 10
    return y, m


def label_contract(ticker, code):
    cm = contract_month(ticker, code)
    return f"{ticker} ({MONTH_NAME[cm[1]]} {cm[0]})" if cm else ticker


def pick_contract(curve, target):
    """First contract expiring ON OR AFTER the date -- you cannot sell into an
    expired contract, so nearest-by-distance is the wrong rule."""
    if curve is None or curve.empty:
        return None
    fwd = curve[pd.to_datetime(curve["expiration"]).dt.date >= target]
    row = fwd.iloc[0] if not fwd.empty else curve.iloc[-1]
    return {"ticker": row["ticker"], "price": float(row["price"]),
            "beyond_curve": fwd.empty}


@st.cache_data(ttl=900, show_spinner=False)
def load_gf(as_of: str):
    key = get_api_key()
    if not key:
        return None, "no MASSIVE_API_KEY"
    try:
        c = get_futures_curve("GF", key, date.fromisoformat(as_of), n_contracts=12)
        if c is None or c.empty:
            c = get_futures_curve("GF", key,
                                  date.fromisoformat(as_of) - timedelta(days=1),
                                  n_contracts=12)
        return c, None
    except MassiveApiError as e:
        return None, f"Massive API error: {e}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


ALL_STATES = "All states"
CASH_BRACKETS = [400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900]


@st.cache_data(ttl=3600, show_spinner=False)
def load_calf_prices():
    """
    {weight_low: $/cwt} head-weighted, trailing 21 days, from calf_sales.

    Returns empty rather than raising if the table is absent -- a missing cash
    feed should leave the user typing their own calf price, not staring at a
    broken page.
    """
    try:
        import snowflake_db as _db
        conn = _db.get_conn()
    except Exception:
        return {}, None
    try:
        since = ("DATEADD(day, -21, CURRENT_DATE())" if _db.use_snowflake()
                 else "date('now','-21 day')")
        rows = conn.cursor().execute(
            "SELECT weight_low, "
            "       SUM(head_count*avg_price)/NULLIF(SUM(head_count),0), "
            "       MAX(report_date) "
            f"FROM calf_sales WHERE report_date >= {since} "
            "GROUP BY weight_low").fetchall()
        out = {int(w): float(p) for w, p, _d in rows if p}
        asof = max((str(_db.iso(d)) for _w, _p, d in rows if d), default=None)
        return out, asof
    except Exception:
        return {}, None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _fmt_date(iso: str) -> str:
    """ISO to 'Sep 14' -- %-d is glibc-only and raises on Windows."""
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%b %d")
    except Exception:
        return str(iso)


def bracket_for(wt: float) -> int:
    """The 50 lb bracket a weight falls in, floored to AMS's grid."""
    return int(wt // 50 * 50)


def death_cost_per_head(calf_cost: float, death_pct: float) -> float:
    """
    $/head of death loss, valued at WHAT YOU PAID for the calf.

    NOTHING ON THIS PAGE ADDS THIS TO A COST. It is a slice of the cost of
    gain the user typed, not a line beside it -- see the comment on `death_c`
    at the build-up below for why that distinction is the whole feature.

    The loss is valued at the PURCHASE price, not the sale price, which is the
    convention the Fed Cattle Crush's build-up uses (`death_c` there is feeder
    value x death %) and the one this page's explainer has always quoted: a
    $2,165 calf, 1% to 5%, is $86.60 over 275 lb of gain = $31.50/cwt. It
    understates slightly -- a calf that dies has eaten something first -- and
    valuing it at the sale price would overstate, by charging the dead calf for
    gain it never put on. Purchase value is the conservative middle and it
    keeps the two crush pages splitting the figure the same way.

    It is taken off the BID rather than off the futures-implied value. The fed
    page uses futures there to break a circularity -- its death loss feeds cost
    of gain, which feeds the break-even, which feeds the bid. No circularity
    arises here precisely because this number feeds nothing.
    """
    return calf_cost * death_pct / 100.0


# ── Header ──────────────────────────────────────────────────────────────────
c_t, c_d = st.columns([6, 2])
with c_t:
    st.markdown("## JSA — Backgrounding Crush")
    st.caption("Buy calves, sell feeders · cash feeder market against the CME Feeder board")

gf, err = load_gf(date.today().isoformat())
calf_px, calf_asof = load_calf_prices()

with c_d:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Futures as of<br><span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{date.today().strftime('%b %d, %Y')}</span></div>", unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

if err or gf is None or gf.empty:
    st.error("Could not load the Feeder Cattle futures curve.")
    st.caption(f"Reads CME Feeder Cattle (GF) from the Massive futures API. "
               + (f"Detail: `{err}`" if err else ""))
    st.stop()

# Two tabs. The crush is a calculator; the cash lookup is a reference for what
# cattle are actually bringing, and they are read at different moments -- one
# when you are pricing a pen, the other when you are deciding what to go look
# at. Same pattern as the Fed Cattle Crush's build-up tab: a hidden tab still
# executes, so nothing here is conditional on which one is showing.
tab_crush, tab_cash = st.tabs(["Crush", "Cash Feeder Prices"])

with tab_crush:
    in_col, out_col = st.columns([1.05, 1])

    with in_col:
        st.markdown('<div class="sec-header">Your Cattle</div>', unsafe_allow_html=True)

        def field(label, fn):
            lc, fc = st.columns([0.92, 1.08])
            with lc:
                st.markdown(f'<div class="fld-label">{label}</div>', unsafe_allow_html=True)
            with fc:
                return fn()

        start_wt = field("Calf in-weight", lambda: st.number_input(
            "start_wt", 300.0, 750.0, DEFAULTS["start_wt"], 25.0,
            label_visibility="collapsed"))
        sell_wt = field("Sell weight", lambda: st.number_input(
            "sell_wt", 500.0, 1000.0, DEFAULTS["sell_wt"], 25.0,
            label_visibility="collapsed"))
        adg = field("Rate of gain", lambda: st.number_input(
            "adg", 0.25, 5.0, DEFAULTS["adg"], 0.05, label_visibility="collapsed",
            help="lb/head/day. Backgrounding on forage or a grower ration runs well "
                 "below a feedyard's 3.0-3.5."))
        cog = field("Cost of gain", lambda: st.number_input(
            "cog", 0.0, 300.0, DEFAULTS["cog"], 1.0, label_visibility="collapsed",
            help="$/cwt of gain, ALL-IN -- feed, yardage, health, interest on "
                 "the calf, AND DEATH LOSS. Iowa State's 2026 budgets put "
                 "backgrounding at $109-111/cwt, about the same as finishing "
                 "because every per-day cost is spread over half as many "
                 "pounds, and their figure already carries death loss. The "
                 "note below works out roughly how much of it that is at "
                 f"today's calf money, at a typical {DEATH_LOSS_PCT:,.0f}%. "
                 "Buying high-risk sale-barn calves means raising this number, "
                 "because death loss on them runs well above that."))
        # NO PLANT SHRINK LINE HERE, deliberately -- asked and answered 2026-09-14.
        #
        # The Fed Cattle Crush has one, because a packer buying fat cattle live pays
        # against a shrunk scale ticket and the full finish weight overstates
        # revenue. The sell side of THIS page is different: it prices against CME
        # Feeder Cattle futures, and that index is already quoted "FOB, 3% standing
        # shrink" -- the shrink is inside the price being used as the reference.
        # Applying it again to the weight would count it twice and understate the
        # calf bid, which is the number this page exists to produce.
        #
        # A backgrounder selling into a cash market on different terms should put
        # the difference in the basis below, where it belongs.
        basis = field("Feeder basis", lambda: st.number_input(
            "basis", -40.0, 40.0, DEFAULTS["basis"], 0.25,
            label_visibility="collapsed",
            help="$/cwt, cash minus futures at sale. Usually negative."))
        start_date = field("Start date", lambda: st.date_input(
            "start_date", date.today(), label_visibility="collapsed"))

    gain = sell_wt - start_wt
    warn = None
    if gain <= 0:
        warn = "Sell weight must be greater than the calf in-weight."
        days = 0
    elif adg <= 0:
        warn = "Rate of gain must be positive."
        days = 0
    else:
        days = int(round(gain / adg))
    finish_date = start_date + timedelta(days=days)

    if warn:
        with in_col:
            st.warning(warn)
        st.stop()

    auto = pick_contract(gf, finish_date)
    with st.expander("Override the contract", expanded=False):
        tickers = list(gf["ticker"])
        pick = st.selectbox("Feeder Cattle (sell)", tickers,
                            index=tickers.index(auto["ticker"]) if auto else 0,
                            format_func=lambda t: label_contract(t, "GF"))
        st.caption(
            "Feeder Cattle trades Jan, Mar, Apr, May, Aug, Sep, Oct and Nov. The "
            "page takes the first contract expiring **on or after** your sale date."
        )
    gf_price = float(gf[gf["ticker"] == pick]["price"].iloc[0])

    if auto and auto.get("beyond_curve"):
        st.warning(f"Your sale date is past the last listed contract "
                   f"({label_contract(auto['ticker'], 'GF')}), so that one is used.")

    # Calf price default tracks the START WEIGHT's bracket, so moving the in-weight
    # re-prices the calf -- the slide from 400 to 650 lb is steep and a fixed
    # default would be wrong the moment the weight changed.
    brk = bracket_for(start_wt)
    calf_seed = calf_px.get(brk)

    sale_price = gf_price + basis
    revenue = sell_wt / 100.0 * sale_price
    cog_cost = gain / 100.0 * cog
    calf_be = (revenue - cog_cost) / (start_wt / 100.0) if start_wt else 0.0

    with in_col:
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Sell date</span>'
            f'<span class="fld-derived">{finish_date.strftime("%b %d, %Y")}'
            f'<span class="fld-note">{days} days · {gain:,.0f} lb gain</span>'
            f'</span></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Feeder at sale</span>'
            f'<span class="fld-derived">${gf_price:,.3f}'
            f'<span class="fld-note">{label_contract(pick, "GF")} '
            f'{basis:+.2f} basis = ${sale_price:,.2f}</span></span></div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Cash calf, {brk}-{brk+49} lb</span>'
            f'<span class="fld-derived">'
            f'{"$%.2f" % calf_seed if calf_seed else "—"}'
            f'<span class="fld-note">'
            f'{"AMS barns, 21-day avg through " + str(calf_asof) if calf_seed else "no cash data yet"}'
            f'</span></span></div>', unsafe_allow_html=True)

    with out_col:
        st.markdown('<div class="sec-header">Bid Price — Calves</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="be-line">Calf break even <b>${calf_be:,.2f}</b> /cwt'
                    f'</div>', unsafe_allow_html=True)
        bid = st.number_input("Bid ($/cwt)", 0.0, 1000.0,
                              float(round(calf_seed if calf_seed else calf_be, 2)), 0.25,
                              label_visibility="collapsed",
                              help="What you would pay for the calves, $/cwt. "
                                   "Seeded from the cash market where available.")

    calf_cost = start_wt / 100.0 * bid
    total_cost = calf_cost + cog_cost
    profit = revenue - total_cost
    # The number a backgrounder actually decides on: what each cwt of gain is worth
    # once the calves are bought. Beat it with cost of gain and the trade works.
    vog = (revenue - calf_cost) / (gain / 100.0) if gain else 0.0
    breakeven = total_cost / (sell_wt / 100.0) if sell_wt else 0.0

    # DEATH LOSS IS DESCRIBED, NOT CHARGED AND NOT ASKED FOR.
    #
    # Two wrong versions shipped on 2026-10-16. The first added death loss to
    # total cost, which double counted it -- the $110 default is Iowa State's
    # ALL-IN figure and carries death loss already -- and moved every answer
    # the page gives with nothing raising. The second kept the input and made
    # it split the cost of gain instead, which was arithmetically harmless and
    # still wrong: a box the user can change, sitting under a box they cannot,
    # reads as an input to the answer when every figure on the page is
    # identical whatever it is set to.
    #
    # So there is no input, and `death_c` reaches NOTHING -- not total_cost,
    # not profit, not the value-of-gain comparison. The identity
    #
    #     profit == (vog - cog) x gain/100      exactly
    #
    # holds, and the caption's per-head figure still agrees with the Profit
    # tile. What is left is a note answering the question the cost of gain
    # field cannot: how much of that $110 is death loss at today's calf money.
    # Worth stating because it SCALES WITH THE CALF and not with the ration --
    # the same 1% was about $3.50/cwt at $180 calves and is $8.65 now.
    death_cost = death_cost_per_head(calf_cost, DEATH_LOSS_PCT)
    death_c = death_cost / (gain / 100.0) if gain else 0.0
    cog_other = cog - death_c      # feed, yardage, health, interest -- the rest
    death_share = (death_c / cog * 100.0) if cog else 0.0

    # THE NOTE, in the column it describes. Appended to in_col after the fact
    # because it needs `calf_cost`, which needs the bid, which is a widget in
    # the other column -- Streamlit appends to a container in script order, so
    # this lands under the derived rows above. Script order, not layout order,
    # the rule the crush pages already run on.
    #
    # The label says "of your cost of gain", not "Death loss", because a bare
    # cost name in a column of inputs is read as another cost. The arithmetic
    # is spelled out rather than just its answer for the same reason: "$8.65"
    # alone invites adding it to something, where "1% x $2,379.72 calf =
    # $23.80 over 2.75 cwt" reads as a slice of a number already on the page.
    with in_col:
        if death_c >= cog:
            # The entered cost of gain cannot contain this much death loss.
            # Unreachable at 1%, kept because DEATH_LOSS_PCT is a constant
            # someone may raise for a high-risk set: at 15% on a $2,400 calf
            # death loss alone is $130/cwt against a $110 cost of gain, and a
            # negative remainder under "feed, yardage, health" is nonsense.
            st.markdown(
                f'<div class="fld-row">'
                f'<span class="fld-label">Death loss in your cost of gain</span>'
                f'<span class="fld-derived" style="color:{AMBER}">${death_c:,.2f}'
                f'<span class="fld-note">{DEATH_LOSS_PCT:,.0f}% &times; '
                f'${calf_cost:,.2f} calf = ${death_cost:,.2f}/head over '
                f'{gain / 100:,.2f} cwt of gain — more than the whole '
                f'${cog:,.2f} above, so that figure is too low for these '
                f'cattle</span></span></div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="fld-row">'
                f'<span class="fld-label">Death loss in your cost of gain</span>'
                f'<span class="fld-derived">${death_c:,.2f}'
                f'<span class="fld-note">a typical {DEATH_LOSS_PCT:,.0f}% '
                f'&times; ${calf_cost:,.2f} calf = ${death_cost:,.2f}/head, '
                f'over {gain / 100:,.2f} cwt of gain &nbsp;·&nbsp; '
                f'{death_share:,.0f}% of the ${cog:,.2f} above, leaving '
                f'${cog_other:,.2f} for feed, yardage, health and interest'
                f'</span></span></div>', unsafe_allow_html=True)

    with out_col:
        pk = "pos" if profit >= 0 else "neg"
        st.markdown(
            f'<div class="profit-box profit-{pk}">'
            f'<div class="profit-label">Profit</div>'
            f'<div class="profit-value">{"+" if profit >= 0 else "-"}'
            f'${abs(profit):,.2f}<span class="profit-unit">/head</span></div></div>',
            unsafe_allow_html=True)
        vk = POS if vog >= cog else NEG
        st.markdown(
            f'<div class="vog"><span class="vog-lab">Value of gain</span><br>'
            f'<span class="vog-val" style="color:{vk}">${vog:,.2f}</span>'
            f'<span style="color:{MUTED};font-size:0.8rem"> /cwt vs '
            f'<b>${cog:,.2f}</b> cost &nbsp;→&nbsp; '
            f'<b style="color:{vk}">${vog - cog:+,.2f}</b> margin on gain</span></div>',
            unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">The Crush</div>', unsafe_allow_html=True)

    # EIGHT TILES, AND THERE IS DELIBERATELY NO DEATH LOSS TILE. A ninth tile
    # reading "Death Loss $23.80" in a row beside "Cost of Gain $302.50" and
    # "Total Cost" invites exactly one thing: adding it on. It is already
    # inside the cost of gain, so that reader would be double counting off a
    # label that never said otherwise -- the headline rule, where a tile has to
    # be unambiguous to someone who reads only that tile. The breakdown lives
    # in the Your Cattle column beside the two fields it is derived from, where
    # it cannot be read as another cost line.
    k = "pos" if profit >= 0 else "neg"
    m = st.columns(4)
    with m[0]:
        st.markdown(tile("Calf Cost", f"${calf_cost:,.2f}",
                         f"{start_wt:,.0f} lb @ ${bid:,.2f}"), unsafe_allow_html=True)
    with m[1]:
        st.markdown(tile("Cost of Gain", f"${cog_cost:,.2f}",
                         f"{gain:,.0f} lb @ ${cog:,.2f}/cwt"), unsafe_allow_html=True)
    with m[2]:
        st.markdown(tile("Total Cost", f"${total_cost:,.2f}",
                         f"breakeven ${breakeven:,.2f}/cwt"), unsafe_allow_html=True)
    with m[3]:
        st.markdown(tile("Profit / Loss", f"${profit:,.2f}",
                         f"per head, {days} days", k), unsafe_allow_html=True)

    n = st.columns(4)
    with n[0]:
        st.markdown(tile("Sale Price", f"${sale_price:,.2f}",
                         f"{pick} ${gf_price:,.2f} {basis:+.2f}"), unsafe_allow_html=True)
    with n[1]:
        st.markdown(tile("Revenue", f"${revenue:,.2f}",
                         f"{sell_wt:,.0f} lb @ ${sale_price:,.2f}"), unsafe_allow_html=True)
    with n[2]:
        st.markdown(tile("Value of Gain", f"${vog:,.2f}", "per cwt of gain",
                         "pos" if vog >= cog else "neg"), unsafe_allow_html=True)
    with n[3]:
        per_day = profit / days if days else 0.0
        st.markdown(tile("Per Head Per Day", f"${per_day:,.2f}",
                         f"over {days} days", k), unsafe_allow_html=True)

    # Every `$` escaped as `\\$`: two unescaped ones in a markdown block open an
    # inline LaTeX span, the dollar signs vanish and the `**` between them come
    # out as literal asterisks. This block has six.
    st.caption(
        f"**Value of gain \\${vog:,.2f}/cwt against a \\${cog:,.2f} cost** is the "
        f"backgrounding decision in one line — you are buying gain at \\${cog:,.2f} "
        f"and selling it at \\${vog:,.2f}. "
        + (f"That is **\\${vog - cog:,.2f}/cwt to the good**, "
           f"\\${(vog - cog) * gain / 100:,.2f} a head on {gain:,.0f} lb."
           if vog >= cog else
           f"That is **\\${cog - vog:,.2f}/cwt underwater** — the gain costs more "
           f"than it is worth at this bid.")
        # THE CAPTION NEEDS THE SAME BRANCH THE COLUMN ROW HAS. Without it, a
        # death rate too high for the entered cost of gain prints "death loss
        # is inside that $110.00 -- $129.80/cwt of it ... 118% of your cost of
        # gain", which contradicts itself inside one sentence. Found in the
        # browser at 15%, not by the tests, because both halves are true
        # statements about numbers that are individually right.
        + (f" Death loss is already inside that \\${cog:,.2f} — about "
           f"\\${death_c:,.2f}/cwt of it at a typical {DEATH_LOSS_PCT:,.0f}%, "
           f"{death_share:,.0f}% of your cost of gain."
           if death_c < cog else
           f" At {DEATH_LOSS_PCT:,.0f}% on a \\${calf_cost:,.2f} calf, death loss "
           f"alone is \\${death_c:,.2f}/cwt of gain — more than the whole "
           f"\\${cog:,.2f} above, so that cost of gain is too low for these cattle.")
    )

    with st.expander("How this is calculated"):
        st.markdown(f"""
    ```
    calf cost/hd  = in-weight/100 x bid
    cost of gain  = (sell - in)/100 x cost of gain
    sale price    = feeder futures ({pick}) + basis
    revenue/hd    = sell weight/100 x sale price
    value of gain = (revenue - calf cost) / (gain/100)
    profit/hd     = revenue - calf cost - cost of gain

    and, describing what is already inside the cost of gain rather than
    adding to it — none of these three reach the figures above:

    death loss/hd      = calf cost x {DEATH_LOSS_PCT:,.0f}%
    death loss/cwt     = death loss/hd / (gain/100)
    share of your COG  = death loss/cwt / cost of gain
    ```

    **The buy and sell legs come from different places, necessarily.** There is no
    futures contract for a 500 lb calf — CME's feeder index starts at 700 lb — so
    the calf price can only come from cash auction data. That is `calf_sales`,
    pulled from the same AMS barn reports behind the feeder cattle index, over the
    weight brackets the index discards. The sale leg *is* a listed contract, so it
    prices off **{label_contract(pick, 'GF')}** plus your basis.

    **The calf default follows your in-weight.** The cash slide from 400 to 650 lb
    is steep — roughly \\$475/cwt down to \\$350 — so a fixed default would be wrong
    the moment you changed the weight. It re-prices to the matching 50 lb bracket.

    **Value of gain is the number to watch**, not profit per head. It is directly
    comparable to what your forage or grower ration costs, and it is what tells you
    whether to buy lighter or heavier cattle. Profit per head follows from it but
    mixes in how many pounds you put on.

    **Death loss, interest, trucking, commission and any charge for risk are all
    inside your cost of gain. There is no separate death loss field, and that is
    deliberate.** Iowa State's \\$109-111/cwt is an all-in figure with death loss
    already carried in it, so a second line would charge it twice. Enter a cost of
    gain that is all-in and the page is right; enter one that is feed and yardage
    only and it is light.

    **The note under your inputs only describes that number — it changes nothing on
    this page.** Every figure above is identical whatever death loss turns out to
    be; what the note tells you is how much of the \\${cog:,.2f} you typed is going
    to it at today's calf money: \\${death_c:,.2f}/cwt, {death_share:,.0f}% of it,
    leaving \\${cog_other:,.2f} for feed, yardage, health and interest. If that
    remainder looks too thin to feed a calf on, the cost of gain is the number to
    raise.

    **Worth stating because it moves with the CALF, not with your ration.** Death
    loss is a percentage of the purchase price, so at \\$450/cwt calves the same 1%
    costs more than twice what it did at \\$180 — a cost of gain carried over from a
    cheaper year is understated for that reason alone.

    **It is valued at what you PAID for the calf**, not at what it would have sold
    for. A calf that dies has eaten something first, so this understates a little;
    valuing it at the sale price would overstate, by charging the dead calf for gain
    it never put on. Purchase value is the conservative middle, and the Fed Cattle
    Crush splits its own death loss the same way.

    **The lever is large.** On a \\$2,165 calf, going from 1% to 5% death loss is
    \\$31.50/cwt of gain. A full \\$1.00/bu move in corn is about \\$9. Death loss is
    roughly three times the lever corn is, and on high-risk sale-barn calves health
    and death loss together can run level with the feed bill — which is the case for
    raising the cost of gain on those cattle, not for adding a second line.
    """)


# ── Cash Feeder Prices ──────────────────────────────────────────────
# The same lookup appears on the CME Feeder Cattle Index page, so it lives in
# cash_calves.py rather than here. Different question, same data: a
# backgrounder asks what a calf is worth before bidding, an index reader asks
# what the cattle behind today's print actually brought.
with tab_cash:
    st.markdown('<div class="sec-header">Cash Feeder Prices</div>',
                unsafe_allow_html=True)
    cash_calves.render(tile, MUTED, key_prefix="bg")

st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
st.markdown(
    f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
    f'Feeder prices from USDA AMS barn reports · CME Feeder Cattle (GF) via '
    f'Massive &nbsp;·&nbsp; {date.today().strftime("%b %d, %Y")}</div>',
    unsafe_allow_html=True)
