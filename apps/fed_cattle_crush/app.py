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
st.markdown('<div class="sec-header">Your Cattle</div>', unsafe_allow_html=True)

solve_for = st.radio(
    "Solve for",
    ["Finish weight", "Average daily gain", "Finish date"],
    horizontal=True, key="solve_for",
    help="Weights, gain and dates are linked — days = finish − start, gain = "
         "finish weight − start weight, ADG = gain ÷ days. Pick the one to "
         "calculate and enter the rest.",
)

c1, c2, c3, c4 = st.columns(4)
with c1:
    start_wt = st.number_input("Starting weight (lb)", 200.0, 1200.0,
                               DEFAULTS["start_wt"], 25.0)
with c2:
    finish_wt = st.number_input("Target finish weight (lb)", 800.0, 1800.0,
                                DEFAULTS["finish_wt"], 25.0,
                                disabled=(solve_for == "Finish weight"))
with c3:
    adg = st.number_input("Average daily gain (lb/day)", 0.5, 6.0,
                          DEFAULTS["adg"], 0.05,
                          disabled=(solve_for == "Average daily gain"))
with c4:
    cog = st.number_input("Cost of gain ($/cwt)", 0.0, 400.0,
                          DEFAULTS["cog"], 1.0,
                          help="All-in cost per hundredweight of gain: feed, "
                               "yardage, health, interest, death loss.")

d1, d2, d3 = st.columns(3)
with d1:
    start_date = st.date_input("Feeding start date", date.today())
with d2:
    seed_finish = date.today() + timedelta(days=DEFAULTS["dof"])
    finish_date = st.date_input("Planned sale date", seed_finish,
                                disabled=(solve_for == "Finish date"))
with d3:
    basis = st.number_input("Live basis ($/cwt)", -30.0, 30.0,
                            DEFAULTS["basis"], 0.25,
                            help="Cash minus futures at the time of sale. "
                                 "Positive means cash trades OVER the board.")

# ── Reconcile the over-determined inputs ────────────────────────────────────
warn = None
if solve_for == "Finish weight":
    days = (finish_date - start_date).days
    if days <= 0:
        warn = "The sale date must be after the start date."
        days = 0
    finish_wt = start_wt + adg * days
elif solve_for == "Average daily gain":
    days = (finish_date - start_date).days
    if days <= 0:
        warn = "The sale date must be after the start date."
        adg = 0.0
    else:
        adg = (finish_wt - start_wt) / days
        if adg <= 0:
            warn = "Finish weight must be greater than starting weight."
else:  # Finish date
    gain_needed = finish_wt - start_wt
    if gain_needed <= 0 or adg <= 0:
        warn = "Finish weight must exceed starting weight, with a positive gain."
        days = 0
    else:
        days = int(round(gain_needed / adg))
    finish_date = start_date + timedelta(days=days)

gain = finish_wt - start_wt

if warn:
    st.warning(warn)
    st.stop()

st.markdown(
    f'<div class="derived">Solved for <b>{solve_for.lower()}</b> — '
    f'<b>{days}</b> days on feed &nbsp;·&nbsp; <b>{gain:,.0f} lb</b> of gain '
    f'&nbsp;·&nbsp; finish <b>{finish_wt:,.0f} lb</b> on '
    f'<b>{finish_date.strftime("%b %d, %Y")}</b> at <b>{adg:.2f}</b> lb/day'
    f'</div>', unsafe_allow_html=True)

# ── Contracts ───────────────────────────────────────────────────────────────
st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Contracts Priced Against</div>',
            unsafe_allow_html=True)

gf_auto = pick_contract(gf, "GF", start_date)
le_auto = pick_contract(le, "LE", finish_date)

e1, e2 = st.columns(2)
with e1:
    gf_tickers = list(gf["ticker"])
    gf_idx = gf_tickers.index(gf_auto["ticker"]) if gf_auto else 0
    gf_pick = st.selectbox("Feeder Cattle (buy)", gf_tickers, index=gf_idx,
                           format_func=lambda t: label_contract(t, "GF"))
    gf_price = float(gf[gf["ticker"] == gf_pick]["price"].iloc[0])
    st.caption(f"\\${gf_price:,.3f}/cwt · auto-selected for a "
               f"{start_date.strftime('%b %d')} start")
with e2:
    le_tickers = list(le["ticker"])
    le_idx = le_tickers.index(le_auto["ticker"]) if le_auto else 0
    le_pick = st.selectbox("Live Cattle (sell)", le_tickers, index=le_idx,
                           format_func=lambda t: label_contract(t, "LE"))
    le_price = float(le[le["ticker"] == le_pick]["price"].iloc[0])
    st.caption(f"\\${le_price:,.3f}/cwt · auto-selected for a "
               f"{finish_date.strftime('%b %d')} sale")

if le_auto and le_auto.get("beyond_curve"):
    st.warning(
        f"Your sale date is past the last listed Live Cattle contract "
        f"({label_contract(le_auto['ticker'], 'LE')}), so that one is being used. "
        f"The board does not trade that far out yet."
    )

# ── The crush ───────────────────────────────────────────────────────────────
feeder_cost = start_wt / 100.0 * gf_price
gain_cost = gain / 100.0 * cog
total_cost = feeder_cost + gain_cost
sale_price = le_price + basis
revenue = finish_wt / 100.0 * sale_price
profit = revenue - total_cost
breakeven = total_cost / (finish_wt / 100.0) if finish_wt else 0.0

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
