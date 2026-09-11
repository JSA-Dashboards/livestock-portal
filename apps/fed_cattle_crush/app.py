"""
Fed Cattle Crush -- what a pen of cattle pencils out at, on today's board.

A CALCULATOR, not a chart. It opens pre-filled from the live CME futures curve
so a feeder sees a real number immediately, and then every field is theirs to
change: their weights, their gain, their cost of gain, their basis, their dates.
The market numbers are a starting point, not an answer.

THE TWO PRICES COME FROM DIFFERENT CONTRACTS, and that is the whole point of
tying this to dates. Cattle bought in September and marketed in April are a
September feeder purchase against an April live cattle sale, so the calculator
prices the feeder leg off the contract covering the START date and the fed leg
off the contract covering the FINISH date. Using one nearby price for both would
quietly erase the entire carry the trade is built on -- on the curve this was
written against, GFU6 is 335.80 while GFU7 a year out is 306.70.

THE INPUTS ARE OVER-DETERMINED, deliberately handled rather than ignored.
Start weight, finish weight, ADG, start date and finish date are five numbers
with three degrees of freedom:

    days = finish date - start date
    gain = finish weight - start weight
    ADG  = gain / days

Set all five and they will contradict each other most of the time. Rather than
silently honour some and ignore others -- which produces a confident, wrong
margin -- the page asks which one to SOLVE FOR and derives it from the other
four. The derived field is shown greyed with its computed value so it is always
obvious which number the page chose rather than the user.

CONTRACT MONTHS DO NOT LINE UP WITH CALENDAR MONTHS. Feeder Cattle trades eight
months (Jan Mar Apr May Aug Sep Oct Nov) and Live Cattle only six, all even
(Feb Apr Jun Aug Oct Dec). A September marketing date has no September live
cattle contract and has to price off October. The page always shows WHICH
contract each price came from and lets it be overridden, because a silent
month-shift is worth several dollars a hundredweight and would be invisible.

Data: Massive futures API, same source and key as the Seasonal Futures page.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from massive_api import MassiveApiError, get_futures_curve

# ── JSA Brand Colors (shared with the rest of the portal shell) ─────────────
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
NEU       = "#5f7267"
AMBER     = "#d97706"

JSA_LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"

MONTH_LETTERS = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                 "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
MONTH_NAME = {v: k for k, v in
              zip(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], range(1, 13))}

# Starting points only -- every one is editable, and they are labelled as
# assumptions on the page rather than presented as fact.
DEFAULTS = {
    "start_wt": 750.0,      # typical yearling placement
    "finish_wt": 1400.0,
    "adg": 3.25,
    "cog": 125.0,           # $/cwt of gain
    "basis": 2.00,          # $/cwt, cash over futures at sale
    "dof": 200,             # only used to seed the finish date
}

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
  .derived {{
    background:{SURFACE2}; border:1px dashed {BORDER}; border-radius:8px;
    padding:10px 14px; color:{MUTED}; font-size:0.82rem;
  }}
  .derived b {{ color:{TEXT}; font-size:1.05rem; }}

  /* Tight label/field rows. The label is right-aligned against its input so
     the values form one scannable column instead of drifting apart. */
  .fld-label {{
    text-align:right; color:{TEXT}; font-size:0.86rem; font-weight:600;
    padding-top:0.55rem; line-height:1.2;
  }}
  .fld-row {{
    display:flex; align-items:baseline; gap:12px; padding:5px 0 5px;
    border-top:1px solid {BORDER};
  }}
  .fld-row .fld-label {{ flex:0 0 46%; padding-top:0; }}
  .fld-derived {{ color:{TEXT}; font-size:1.0rem; font-weight:700; }}
  .fld-note {{
    display:block; color:{MUTED}; font-size:0.68rem; font-weight:400;
    margin-top:1px;
  }}

  /* Bid / profit hero. Deliberately the largest thing on the page -- it is
     the number a buyer is deciding. */
  .be-line {{
    color:{MUTED}; font-size:0.82rem; margin:0 0 4px 2px;
  }}
  .be-line b {{ color:{TEXT}; font-size:0.95rem; }}
  .profit-box {{
    border-radius:12px; padding:14px 18px; margin-top:10px; text-align:center;
  }}
  .profit-pos {{ background:{POS}; }}
  .profit-neg {{ background:{NEG}; }}
  .profit-label {{
    color:rgba(255,255,255,0.92); font-size:0.72rem; font-weight:700;
    text-transform:uppercase; letter-spacing:0.12em;
  }}
  .profit-value {{
    color:#ffffff; font-size:2.1rem; font-weight:800; line-height:1.15;
  }}
  .profit-unit {{ font-size:1.0rem; font-weight:600; opacity:0.9; }}
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
    try:
        k = st.secrets.get("MASSIVE_API_KEY", "")
    except Exception:
        k = ""
    import os
    return k or os.environ.get("MASSIVE_API_KEY", "")


def contract_month(ticker: str, code: str):
    """('GFU6', 'GF') -> (2026, 9). Year digit is the decade's last digit."""
    suffix = ticker[len(code):]
    if len(suffix) < 2 or suffix[0] not in MONTH_LETTERS:
        return None
    m = MONTH_LETTERS[suffix[0]]
    try:
        d = int(suffix[1:])
    except ValueError:
        return None
    # Single-digit year: resolve to the decade that keeps it near today.
    base = date.today().year
    y = (base // 10) * 10 + d if d < 10 else 2000 + d
    while y < base - 1:
        y += 10
    return y, m


def pick_contract(curve: pd.DataFrame, code: str, target: date):
    """
    The contract a feeder would actually price against for `target`.

    Chosen as the first contract EXPIRING ON OR AFTER the date, not the nearest
    by absolute distance. Cattle marketed in early October are sold against the
    October contract, not August, even though August may be fewer days away --
    you cannot deliver into a contract that has already expired.
    """
    if curve is None or curve.empty:
        return None
    fwd = curve[pd.to_datetime(curve["expiration"]).dt.date >= target]
    row = (fwd.iloc[0] if not fwd.empty else curve.iloc[-1])
    return {
        "ticker": row["ticker"],
        "price": float(row["price"]),
        "expiration": pd.to_datetime(row["expiration"]).date(),
        "beyond_curve": fwd.empty,
    }


def label_contract(ticker: str, code: str) -> str:
    cm = contract_month(ticker, code)
    return f"{ticker} ({MONTH_NAME[cm[1]]} {cm[0]})" if cm else ticker


@st.cache_data(ttl=3600, show_spinner=False)
def load_corn():
    """
    {state: {...}} DELIVERED corn cost per feeding state -- see corn_cost.py.

    Delivered, not the elevator bid. Almost every published corn price is what a
    farmer RECEIVES; a feedyard pays that plus the elevator's margin and freight
    to the bunk. Where AMS publishes both (Texas South Plains) the gap is 86c a
    bushel -- about $8/cwt of gain. Feeding a bid into cost of gain understates
    corn by that much.

    Returns empty rather than raising if the tables are absent: a missing corn
    feed should leave the user typing their own number, not break the page.
    """
    try:
        import snowflake_db as _db
        import corn_cost
        conn = _db.get_conn()
    except Exception:
        return {}, None
    try:
        return corn_cost.delivered_corn(conn), date.today().isoformat()
    except Exception:
        return {}, None
    finally:
        try:
            conn.close()
        except Exception:
            pass


@st.cache_data(ttl=900, show_spinner=False)
def load_curves(as_of: str):
    key = get_api_key()
    if not key:
        return None, None, "no key"
    out = {}
    for code in ("GF", "LE"):
        try:
            c = get_futures_curve(code, key, date.fromisoformat(as_of), n_contracts=12)
        except MassiveApiError as e:
            return None, None, f"Massive API error: {e}"
        except Exception as e:
            return None, None, f"{type(e).__name__}: {e}"
        # The contract list can lag a day right at the UTC rollover; fall back
        # rather than show a false "no contracts" to someone at 7am.
        if c is None or c.empty:
            try:
                c = get_futures_curve(code, key,
                                      date.fromisoformat(as_of) - timedelta(days=1),
                                      n_contracts=12)
            except Exception:
                pass
        out[code] = c
    return out.get("GF"), out.get("LE"), None


# ── Header ──────────────────────────────────────────────────────────────────
col_t, col_d = st.columns([6, 2])
with col_t:
    st.markdown("## JSA — Fed Cattle Crush")
    st.caption("Feeding margin on the board · CME Feeder Cattle and Live Cattle futures")

gf, le, err = load_curves(date.today().isoformat())

with col_d:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Futures as of<br><span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{date.today().strftime('%b %d, %Y')}</span></div>", unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

if err or gf is None or le is None or gf.empty or le.empty:
    st.error("Could not load the futures curve.")
    st.caption(
        "This page reads CME Feeder Cattle (GF) and Live Cattle (LE) settlements "
        "from the Massive futures API — the same source and key as the Seasonal "
        "Futures & Spreads page. "
        + (f"Detail: `{err}`" if err else "")
    )
    st.stop()

# ── Inputs ──────────────────────────────────────────────────────────────────
# Laid out as tight label/field ROWS rather than a grid of full-width widgets.
# The grid version put every caption above its box and left the numbers far
# apart, so the thing a feeder actually scans -- the column of values -- was
# broken up by whitespace and help text. Here the labels sit right-aligned
# against the fields, so the values line up and read as a single column.
in_col, out_col = st.columns([1.05, 1])

with in_col:
    st.markdown('<div class="sec-header">Your Cattle</div>', unsafe_allow_html=True)

    def field(label, widget_fn):
        lc, fc = st.columns([0.92, 1.08])
        with lc:
            st.markdown(f'<div class="fld-label">{label}</div>',
                        unsafe_allow_html=True)
        with fc:
            return widget_fn()

    start_wt = field("Avg start weight", lambda: st.number_input(
        "start_wt", 200.0, 1200.0, DEFAULTS["start_wt"], 25.0,
        label_visibility="collapsed"))
    finish_wt = field("Target finish", lambda: st.number_input(
        "finish_wt", 500.0, 1800.0, DEFAULTS["finish_wt"], 25.0,
        label_visibility="collapsed"))
    adg = field("Rate of gain", lambda: st.number_input(
        "adg", 0.5, 6.0, DEFAULTS["adg"], 0.05, label_visibility="collapsed",
        help="lb per head per day"))
    cog_mode = field("Cost of gain", lambda: st.selectbox(
        "cog_mode", ["Build from corn", "Enter directly"],
        label_visibility="collapsed"))
    if cog_mode == "Enter directly":
        cog = field(" ", lambda: st.number_input(
            "cog", 0.0, 400.0, DEFAULTS["cog"], 1.0, label_visibility="collapsed",
            help="$/cwt of gain — all-in: feed, yardage, health, interest, "
                 "death loss."))
    else:
        cog = None          # built below, once days and gain are known
    basis = field("Live basis", lambda: st.number_input(
        "basis", -30.0, 30.0, DEFAULTS["basis"], 0.25,
        label_visibility="collapsed",
        help="$/cwt, cash minus futures at sale. Positive = cash over the board."))
    start_date = field("Start date", lambda: st.date_input(
        "start_date", date.today(), label_visibility="collapsed"))

# ── Derive the dependent values ─────────────────────────────────────────────
# Finish date is ALWAYS derived, rather than offering a "solve for" choice.
# Start weight, target finish, rate of gain and start date are the four a
# feeder actually knows; the sale date falls out of them. The earlier version
# made the user pick which of five linked numbers to solve for, which was
# correct but asked them to think about the arithmetic before they could think
# about the cattle.
gain = finish_wt - start_wt
warn = None
if gain <= 0:
    warn = "Target finish weight must be greater than the starting weight."
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

gf_auto = pick_contract(gf, "GF", start_date)
le_auto = pick_contract(le, "LE", finish_date)

# Auto-selected by default so the common case needs no thought, but still
# overridable: a silent month-shift between the contract the page picked and
# the one a feeder is actually hedging against is worth several dollars a
# hundredweight, and would be invisible if it could not be changed or seen.
with st.expander("Override the contracts", expanded=False):
    o1, o2 = st.columns(2)
    with o1:
        gf_tickers = list(gf["ticker"])
        gf_pick = st.selectbox(
            "Feeder Cattle (buy)", gf_tickers,
            index=gf_tickers.index(gf_auto["ticker"]) if gf_auto else 0,
            format_func=lambda t: label_contract(t, "GF"))
    with o2:
        le_tickers = list(le["ticker"])
        le_pick = st.selectbox(
            "Live Cattle (sell)", le_tickers,
            index=le_tickers.index(le_auto["ticker"]) if le_auto else 0,
            format_func=lambda t: label_contract(t, "LE"))
    st.caption(
        "Feeder Cattle trades Jan, Mar, Apr, May, Aug, Sep, Oct, Nov; Live "
        "Cattle only the even months. The page picks the first contract "
        "expiring **on or after** your date — you cannot sell into an expired "
        "contract — which is why a September sale prices off October."
    )

gf_price = float(gf[gf["ticker"] == gf_pick]["price"].iloc[0])
le_price = float(le[le["ticker"] == le_pick]["price"].iloc[0])

if le_auto and le_auto.get("beyond_curve"):
    st.warning(
        f"Your sale date is past the last listed Live Cattle contract "
        f"({label_contract(le_auto['ticker'], 'LE')}), so that one is used. "
        f"The board does not trade that far out yet."
    )

with in_col:
    # %-m is glibc-only and raises ValueError on Windows; %b %d, %Y is portable
    # and this runs on both a Windows desktop and Streamlit Cloud's Linux.
    st.markdown(
        f'<div class="fld-row"><span class="fld-label">Finish date</span>'
        f'<span class="fld-derived">{finish_date.strftime("%b %d, %Y")}'
        f'<span class="fld-note">{days} days on feed · {gain:,.0f} lb gain</span>'
        f'</span></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="fld-row"><span class="fld-label">Live at finish</span>'
        f'<span class="fld-derived">${le_price:,.3f}'
        f'<span class="fld-note">{label_contract(le_pick, "LE")}</span>'
        f'</span></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="fld-row"><span class="fld-label">Feeder at start</span>'
        f'<span class="fld-derived">${gf_price:,.3f}'
        f'<span class="fld-note">{label_contract(gf_pick, "GF")}</span>'
        f'</span></div>', unsafe_allow_html=True)

# ── Cost of gain, built from corn ───────────────────────────────────────────
# Only reachable once days and gain are known, which is why it sits here rather
# than inline with the other inputs.
#
# There is no single "accurate" cost of gain. It is corn price x ration mix x
# feed conversion, plus yardage x days, plus interest on the money tied up in
# the feeder, plus death loss. A tighter number typed into a box is still a
# guess; showing the build-up makes it obvious which assumption is doing the
# work, and lets a feeder put their own yard's figures in.
if cog_mode == "Build from corn":
    corn_states, corn_asof = load_corn()
    with st.expander("Cost of gain build-up", expanded=True):
        g1, g2, g3, g4 = st.columns(4)
        with g1:
            state_opts = list(corn_states.keys()) or ["—"]
            default_state = "NE" if "NE" in state_opts else state_opts[0]
            cstate = st.selectbox("Feedyard state", state_opts,
                                  index=state_opts.index(default_state))
            cs = corn_states.get(cstate, {})
            seed = cs.get("price", 5.25)
            corn = st.number_input("Corn delivered ($/bu)", 0.0, 20.0,
                                   float(round(seed, 2)), 0.05,
                                   help="Delivered to the feedyard, not the "
                                        "elevator bid. See the note below for "
                                        "how this state's figure was derived.")
        with g2:
            corn_pct = st.number_input("Ration corn (%)", 0.0, 100.0, 80.0, 5.0)
            other_ton = st.number_input("Other feed ($/ton)", 0.0, 800.0, 250.0, 10.0)
        with g3:
            conv = st.number_input("Feed conversion", 3.0, 12.0, 6.5, 0.1,
                                   help="lb of feed (as-fed) per lb of gain")
            yardage = st.number_input("Yardage ($/hd/day)", 0.0, 3.0, 0.45, 0.01)
        with g4:
            health = st.number_input("Health/processing ($/hd)", 0.0, 200.0, 25.0, 5.0)
            interest = st.number_input("Interest (%)", 0.0, 30.0, 8.0, 0.25)
            death = st.number_input("Death loss (%)", 0.0, 10.0, 1.5, 0.1)

        corn_ton = corn * 2000.0 / 56.0          # 56 lb to the bushel
        ration_ton = (corn_pct / 100.0) * corn_ton + (1 - corn_pct / 100.0) * other_ton
        gain_cwt = gain / 100.0

        feed_c = conv * ration_ton / 2000.0 * 100.0      # $/cwt of gain
        yard_c = (yardage * days) / gain_cwt if gain_cwt else 0.0
        health_c = health / gain_cwt if gain_cwt else 0.0
        # Interest and death loss scale with the value of the animal. Based on
        # the FUTURES price, not the bid entered below -- the bid depends on the
        # break-even, which depends on cost of gain, which would depend on the
        # bid. Circular. The futures is the right order of magnitude and the
        # difference is a few cents a hundredweight.
        feeder_val = start_wt / 100.0 * gf_price
        int_c = (feeder_val * interest / 100.0 * days / 365.0) / gain_cwt if gain_cwt else 0.0
        death_c = (feeder_val * death / 100.0) / gain_cwt if gain_cwt else 0.0

        cog = feed_c + yard_c + health_c + int_c + death_c

        # NO backslash-escaped dollars in these HTML blocks. The LaTeX
        # escape is a MARKDOWN rule -- inside unsafe_allow_html the
        # backslash has no meaning and renders literally, which is exactly
        # what it did here. st.caption below still needs the escapes.
        # Say where the corn number came from and whether any of it is assumed.
        # "Corn is $5.47" means something different if 40c of it is a freight
        # estimate rather than a published delivered price.
        if cs.get("assumed"):
            prov = (f"{cstate} elevator bid <b>${cs['bid']:,.2f}</b> "
                    f"({cs['source']}, {cs['n']} quotes) + <b>${cs['adder']:,.2f}</b> "
                    f"assumed freight &amp; margin to the bunk")
        elif cs:
            prov = (f"{cstate} <b>delivered to feedyard</b>, published by "
                    f"{cs['source']} ({cs['n']} quotes) — measured, not assumed")
        else:
            prov = "no cash corn data for this state; the figure above is yours"
        st.markdown(
            f"<div style='color:{MUTED};font-size:0.8rem;margin-top:6px'>"
            f"{prov}<br>corn ${corn:,.2f}/bu → ${corn_ton:,.2f}/ton · ration "
            f"${ration_ton:,.2f}/ton"
            f"</div>", unsafe_allow_html=True)
        b = pd.DataFrame([
            {"Component": "Feed", "$/cwt gain": round(feed_c, 2),
             "$/head": round(feed_c * gain_cwt, 2)},
            {"Component": "Yardage", "$/cwt gain": round(yard_c, 2),
             "$/head": round(yard_c * gain_cwt, 2)},
            {"Component": "Health/processing", "$/cwt gain": round(health_c, 2),
             "$/head": round(health_c * gain_cwt, 2)},
            {"Component": "Interest", "$/cwt gain": round(int_c, 2),
             "$/head": round(int_c * gain_cwt, 2)},
            {"Component": "Death loss", "$/cwt gain": round(death_c, 2),
             "$/head": round(death_c * gain_cwt, 2)},
            {"Component": "TOTAL", "$/cwt gain": round(cog, 2),
             "$/head": round(cog * gain_cwt, 2)},
        ])
        st.dataframe(b, use_container_width=True, hide_index=True)

        sens = conv * (2000.0 / 56.0) * (corn_pct / 100.0) / 2000.0 * 100.0
        st.caption(
            f"Cost of gain **\\${cog:,.2f}/cwt** of gain, "
            f"**\\${cog * gain_cwt:,.2f}/head** over {gain:,.0f} lb. "
            f"At this ration and conversion, every **\\$1.00/bu** on corn moves "
            f"cost of gain **\\${sens:,.2f}/cwt**. "
            + (f"Corn seeded from {cstate} cash bids through {corn_asof}."
               if corn_asof else
               "Corn bids unavailable — the figure above is the value you typed.")
        )

    with in_col:
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Cost of gain</span>'
            f'<span class="fld-derived">${cog:,.2f}'
            f'<span class="fld-note">$/cwt gain · built from '
            f'${corn:,.2f} corn</span></span></div>', unsafe_allow_html=True)

# ── Bid price: the question a buyer actually asks ───────────────────────────
# The board price for feeders is what the market says; the BID is what this
# buyer will pay, and it is the only number they control on the buy side. So it
# is the input, seeded from the futures, and the feeder break-even sits above it
# as the ceiling to stay under.
gain_cost = gain / 100.0 * cog
sale_price = le_price + basis
revenue = finish_wt / 100.0 * sale_price
feeder_be = (revenue - gain_cost) / (start_wt / 100.0) if start_wt else 0.0

with out_col:
    st.markdown('<div class="sec-header">Bid Price</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="be-line">Feeder break even '
        f'<b>${feeder_be:,.2f}</b> /cwt</div>', unsafe_allow_html=True)
    bid = st.number_input("Bid ($/cwt)", 0.0, 1000.0,
                          float(round(gf_price, 2)), 0.25,
                          label_visibility="collapsed",
                          help="What you would pay for the feeders, $/cwt. "
                               "Seeded from the futures; move it to your bid.")

feeder_cost = start_wt / 100.0 * bid
total_cost = feeder_cost + gain_cost
profit = revenue - total_cost
breakeven = total_cost / (finish_wt / 100.0) if finish_wt else 0.0

with out_col:
    pk = "pos" if profit >= 0 else "neg"
    st.markdown(
        f'<div class="profit-box profit-{pk}">'
        f'<div class="profit-label">Profit</div>'
        f'<div class="profit-value">{"+" if profit >= 0 else "−"}'
        f'${abs(profit):,.2f}<span class="profit-unit">/head</span></div>'
        f'</div>', unsafe_allow_html=True)
    st.caption(
        f"At a \\${bid:,.2f} bid. Break even on the feeders is "
        f"**\\${feeder_be:,.2f}** — bid under that and this pen makes money at "
        f"today's board."
    )

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">The Crush</div>', unsafe_allow_html=True)

k = "pos" if profit >= 0 else "neg"
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(tile("Feeder Cost", f"${feeder_cost:,.2f}",
                     f"{start_wt:,.0f} lb @ ${gf_price:,.2f}"), unsafe_allow_html=True)
with m2:
    st.markdown(tile("Cost of Gain", f"${gain_cost:,.2f}",
                     f"{gain:,.0f} lb @ ${cog:,.2f}/cwt"), unsafe_allow_html=True)
with m3:
    st.markdown(tile("Total Cost", f"${total_cost:,.2f}",
                     f"breakeven ${breakeven:,.2f}/cwt"), unsafe_allow_html=True)
with m4:
    st.markdown(tile("Profit / Loss", f"${profit:,.2f}",
                     f"per head, {days} days", k), unsafe_allow_html=True)

n1, n2, n3, n4 = st.columns(4)
with n1:
    st.markdown(tile("Sale Price", f"${sale_price:,.2f}",
                     f"{le_pick} ${le_price:,.2f} {basis:+.2f} basis"),
                unsafe_allow_html=True)
with n2:
    st.markdown(tile("Revenue", f"${revenue:,.2f}",
                     f"{finish_wt:,.0f} lb @ ${sale_price:,.2f}"), unsafe_allow_html=True)
with n3:
    margin_cwt = profit / (finish_wt / 100.0) if finish_wt else 0.0
    st.markdown(tile("Margin", f"${margin_cwt:,.2f}", "per cwt sold", k),
                unsafe_allow_html=True)
with n4:
    need = breakeven - basis
    st.markdown(tile("Futures to Break Even", f"${need:,.2f}",
                     f"{le_pick} is ${le_price:,.2f}",
                     "pos" if le_price >= need else "neg"), unsafe_allow_html=True)

st.caption(
    f"**Breakeven of \\${breakeven:,.2f}/cwt** is total cost spread over the "
    f"{finish_wt:,.0f} lb sale weight. With basis at \\${basis:+,.2f}, "
    f"{le_pick} needs to be **\\${need:,.2f}** for this pen to pay its way — it is "
    f"**\\${le_price:,.2f}** now, "
    + ("**above** that." if le_price >= need else "**below** that.")
)

# ── Method ──────────────────────────────────────────────────────────────────
with st.expander("How this is calculated, and what it does not include"):
    st.markdown(f"""
```
feeder cost/hd = start weight/100 x feeder futures ({gf_pick})
cost of gain   = (finish - start)/100 x cost of gain
total cost     = feeder cost + cost of gain
sale price     = live futures ({le_pick}) + basis
revenue/hd     = finish weight/100 x sale price
profit/hd      = revenue - total cost
breakeven      = total cost / (finish weight/100)
```

**The two legs are priced off different contracts on purpose.** Cattle bought
now and marketed next spring are a *{label_contract(gf_pick, 'GF')}* purchase
against a *{label_contract(le_pick, 'LE')}* sale. Pricing both off the nearby
month would erase the carry the trade is built on.

**Contract months do not match calendar months.** Feeder Cattle trades Jan, Mar,
Apr, May, Aug, Sep, Oct and Nov; Live Cattle only the even months — Feb, Apr,
Jun, Aug, Oct, Dec. A September sale date has no September live cattle contract
and prices off October. The page picks the first contract expiring **on or
after** your date, rather than the nearest one, because you cannot sell into a
contract that has already expired. Both are overridable above.

**Cost of gain is taken as one all-in number**, not built up from a ration. That
is what a feeder usually knows for their own yard, and it keeps feed, yardage,
health, interest and death loss in a single figure you control rather than
buried in assumptions this page invented.

**Not included:** commission and trucking, hedging costs or margin, and any
price for the risk itself. This is the gross feeding margin on the board, not a
net return after execution.

**Every number above is a starting point.** The futures come from the live
curve; the weights, gain, cost of gain and basis are typical values, not
advice — replace them with your own.
""")

st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
st.markdown(
    f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
    f'CME Feeder Cattle (GF) and Live Cattle (LE) settlements via Massive '
    f'&nbsp;·&nbsp; curve as of {date.today().strftime("%b %d, %Y")}</div>',
    unsafe_allow_html=True)
