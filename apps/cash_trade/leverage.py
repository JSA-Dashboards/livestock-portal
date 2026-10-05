"""
How much of the kill packers have already bought, and how much they still need.

Packer leverage is not a mood — it is a published ratio. Every week AMS breaks
the slaughter it reports down by HOW each animal was bought, and the share that
arrived on a formula or a forward contract is supply the packer never has to
bid for. When that share is high the cash market is a rounding error on their
week and they can stand back; when it falls they have to come and get cattle.

    LM_CT153 §B  slaughter, split formula / forward / negotiated / neg grid
    LM_CT153 §A  packer-owned slaughter — cattle they fed themselves
    LM_CT153 §C  forward contract purchases, weekly and cumulative
    LM_CT142     committed and delivered head, the forward book and its drain

TWO CLOCKS, AND MIXING THEM IS THE TRAP THIS MODULE EXISTS TO AVOID.
LM_CT154's row dated 9/28 is 47,138 head PURCHASED in the week just ended.
LM_CT153's row dated 9/28 is 62,190 head SLAUGHTERED in that week, bought
whenever they were bought — often weeks earlier. They are different
populations on different timelines and their ratio wanders: measured across
2026-08-24..09-28 it ran 0.83, 1.04, 1.15, 1.14, 1.15, 1.32. Dividing one by
the other produces a number that looks like a share, moves like a share, and
means nothing.

So **every share here is computed inside LM_CT153 alone** — numerator and
denominator from the same row of the same report. LM_CT154 is the purchase
side and belongs in the page's other tabs, which is where it stays.

NEGOTIATED GRID IS REPORTED SEPARATELY AND IS NOT FOLDED IN. Its base price is
negotiated in the week, so for "did the packer have to transact this week" it
belongs with negotiated cash; for "what share of the kill discovered a cash
price" the convention is negotiated cash alone. Both readings are defensible
and they differ a lot — 19.7% against 29.1% for the week ending 2026-09-28 —
so the page prints the strict one as the headline, shows grid as its own band
in the mix, and never silently picks.
"""
from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

LMR_BASE = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"

CT142_ID = 2472   # Weekly Direct Slaughter Cattle - Committed and Delivered
CT153_ID = 2480   # National Weekly - Prior Week Slaughter and Contract Purchases

# Section names are a PATH SEGMENT, not a query parameter, and the bare slug
# answers 200 with a near-empty row rather than an error — the same shape
# CLAUDE.md documents for MARS 3208 and the direct/video slugs. The catalog
# endpoint lists them under `sectionNames`, which is the cheap way to check a
# name rather than guessing at it.
SEC_MIX = "B. Prior Week Formula & Contract Slaughter"
SEC_OWNED = "A. Packer Owned Slaughter"
SEC_FORWARD = "C. Forward Contract Purchases"

# The four ways a reported animal was bought. Domestic and imported are
# separate columns throughout and are summed: an imported formula steer is
# still supply the packer did not bid for this week.
MIX = {
    "formula": ("B_dom_formula_head_count", "B_imp_formula_head_count"),
    "forward": ("B_dom_forward_head_count", "B_imp_forward_head_count"),
    "negotiated": ("B_dom_neg_head_count", "B_imp_neg_head_count"),
    "neg_grid": ("B_dom_neg_grid_head_count", "B_imp_neg_grid_head_count"),
}
MIX_LABEL = {"formula": "Formula", "forward": "Forward contract",
             "negotiated": "Negotiated cash", "neg_grid": "Negotiated grid"}


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def _rows(payload) -> list:
    """AMS answers 200 with a bare string when a window holds no report."""
    if isinstance(payload, dict):
        r = payload.get("results")
        return r if isinstance(r, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


def fetch(session_factory, jobs: list, timeout: int = 180) -> dict:
    """Run the independent section GETs concurrently; a failure yields []."""
    def run(job):
        key, slug, section = job
        url = f"{LMR_BASE}/{slug}"
        if section:
            url += "/" + urllib.parse.quote(section)
        try:
            resp = session_factory().get(url, timeout=timeout)
            if resp.status_code in (204, 404):
                return key, []
            resp.raise_for_status()
            return key, _rows(resp.json())
        except Exception:
            return key, []

    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
        return dict(ex.map(run, jobs))


def load(session_factory) -> dict:
    """
    Every series this tab needs, as {name: DataFrame}, keyed on week.

    Full history on each — about 3 s and 6 MB across the four concurrently,
    which is the same order as the weekly price and volume fetches this page
    already makes on every load. The hidden-tab rule therefore costs roughly
    what the existing tabs do rather than multiplying it.
    """
    got = fetch(session_factory, [
        ("mix", CT153_ID, SEC_MIX),
        ("owned", CT153_ID, SEC_OWNED),
        ("forward", CT153_ID, SEC_FORWARD),
        ("committed", CT142_ID, None),
    ])
    return {
        "mix": _mix_frame(got.get("mix", [])),
        "owned": _owned_frame(got.get("owned", [])),
        "forward": _forward_frame(got.get("forward", [])),
        "committed": _committed_frame(got.get("committed", [])),
    }


def _mix_frame(rows: list) -> pd.DataFrame:
    """One row per week: head by purchase type, the total, and the shares."""
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date"], format="%m/%d/%Y", errors="coerce")
    d = d.dropna(subset=["week"]).drop_duplicates("week", keep="last").sort_values("week")
    out = pd.DataFrame({"week": d["week"].values})
    for name, (dom, imp) in MIX.items():
        dv = _num(d[dom]) if dom in d else 0
        iv = _num(d[imp]) if imp in d else 0
        out[name] = (dv.fillna(0).values if hasattr(dv, "fillna") else dv) + \
                    (iv.fillna(0).values if hasattr(iv, "fillna") else iv)

    # USDA publishes its own total. Use it rather than the sum of the four:
    # if a fifth category is ever added, a derived total would quietly keep
    # the shares adding to 100% while describing less than the whole kill.
    out["total"] = _num(d["B_total_head_count"]).values if "B_total_head_count" in d \
        else out[list(MIX)].sum(axis=1)
    for name in MIX:
        out[f"{name}_pct"] = out[name] / out["total"]
    # Committed = everything the packer did not have to transact for this week.
    out["committed_pct"] = 1 - out["negotiated_pct"] - out["neg_grid_pct"]
    # ...and the looser reading, which counts a negotiated grid base as a
    # weekly transaction. Shown, never substituted for the headline.
    out["must_buy_pct"] = out["negotiated_pct"] + out["neg_grid_pct"]
    return out.dropna(subset=["total"])


def _owned_frame(rows: list) -> pd.DataFrame:
    """Packer-owned slaughter — the purest captive supply, domestic + imported."""
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date"], format="%m/%d/%Y", errors="coerce")
    d["head"] = _num(d["head_count"])
    d = d.dropna(subset=["week"])
    g = d.groupby("week", as_index=False)["head"].sum(min_count=1)
    return g.rename(columns={"head": "packer_owned"}).sort_values("week")


def _forward_frame(rows: list) -> pd.DataFrame:
    """Forward contract purchases: the week's buying and the standing book."""
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date"], format="%m/%d/%Y", errors="coerce")
    d = d.dropna(subset=["week"]).drop_duplicates("week", keep="last").sort_values("week")
    return pd.DataFrame({
        "week": d["week"].values,
        "fwd_week": _num(d["C_weekly_head_count"]).values,
        "fwd_book": _num(d["C_cumulative_head_count"]).values,
    })


def _committed_frame(rows: list) -> pd.DataFrame:
    """
    LM_CT142's committed book and what actually shipped against it.

    Two rows per week — `purchasing_basis` is Committed or Delivered — so this
    pivots rather than filters. Coverage is the book divided by the delivery
    pace: how many weeks of kill the packer has already secured.
    """
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date_end"], format="%m/%d/%Y", errors="coerce")
    d["vol"] = _num(d["current_volume"])
    d = d.dropna(subset=["week"])
    p = (d.pivot_table(index="week", columns="purchasing_basis", values="vol",
                       aggfunc="last").reset_index())
    p.columns.name = None
    p = p.rename(columns={"Committed": "committed", "Delivered": "delivered"})
    for c in ("committed", "delivered"):
        if c not in p:
            p[c] = float("nan")
    # Delivery pace over four weeks, not one: a holiday week halves the
    # denominator and would print a coverage spike that is the calendar.
    pace = p["delivered"].rolling(4, min_periods=2).mean()
    p["coverage_weeks"] = p["committed"] / pace
    return p.sort_values("week")


def latest(frames: dict) -> dict:
    """The newest complete reading of each series, for the headline tiles."""
    out = {}
    mix = frames.get("mix")
    if mix is not None and not mix.empty:
        r = mix.iloc[-1]
        prior = mix.iloc[-2] if len(mix) > 1 else None
        yr = mix[mix["week"] <= r["week"] - pd.Timedelta(weeks=52)]
        out["mix"] = r
        out["mix_prior"] = prior
        out["mix_year"] = yr.iloc[-1] if not yr.empty else None
    for key in ("owned", "forward", "committed"):
        f = frames.get(key)
        if f is not None and not f.empty:
            out[key] = f.iloc[-1]
            out[f"{key}_prior"] = f.iloc[-2] if len(f) > 1 else None
    return out


# Weeks averaged for the cash-need figure. FOUR, because the quantity is noisy
# and the alternative to averaging is quoting last week as though it were next
# week. Measured over the last 56 weeks (2026-10-05), a four-week mean lands
# within a median 8.8% of the following week's negotiated head, 21.8% at the
# 90th percentile; including negotiated grid it is tighter at 7.3% / 18.9%,
# because grid and cash partly offset each other week to week.
NEED_WEEKS = 4


def cash_need(mix: pd.DataFrame, weeks: int = NEED_WEEKS) -> dict:
    """
    How many head packers have to transact for in a week, at the recent rate.

    THIS IS A RUN RATE, NOT A FORECAST, and the page says so. There is no
    published figure for "cattle still to buy this week" — the week's purchases
    and the week's slaughter are different populations on different clocks (see
    the module docstring), so subtracting one from the other would manufacture
    a number rather than measure one. What can honestly be said is how many
    head the recent weeks have each required, and how much that has varied.

    Both readings, for the same reason the headline shows both: `cash` is
    negotiated cash alone, `must_buy` adds negotiated grid, whose base is
    struck in the week and which therefore is a transaction the packer has to
    make even though it does not set a cash quote.

    The band is the actual high and low of those weeks, not a standard
    deviation — with four observations a spread is something you can point at
    and a sigma is a decoration.
    """
    if mix.empty or len(mix) < 2:
        return {}
    d = mix.tail(weeks)
    cash = d["negotiated"]
    must = d["negotiated"] + d["neg_grid"]
    return {
        "weeks": int(len(d)),
        "cash": float(cash.mean()), "cash_lo": float(cash.min()), "cash_hi": float(cash.max()),
        "must": float(must.mean()), "must_lo": float(must.min()), "must_hi": float(must.max()),
        "kill": float(d["total"].mean()),
        "from": pd.Timestamp(d["week"].min()), "to": pd.Timestamp(d["week"].max()),
    }


def need_accuracy(mix: pd.DataFrame, weeks: int = NEED_WEEKS,
                  lookback: int = 52) -> dict:
    """
    How close that run rate has actually landed to the week that followed.

    Computed live rather than hard-coded, so the claim on the page keeps
    describing the market rather than the market of the day it was written.
    Median absolute error, because the misses are skewed by holiday weeks and
    a mean would describe none of the ordinary ones.
    """
    if mix.empty or len(mix) < weeks + 8:
        return {}
    d = mix.tail(lookback + weeks)
    out = {}
    for key, series in (("cash", d["negotiated"]),
                        ("must", d["negotiated"] + d["neg_grid"])):
        errs = []
        vals = series.to_numpy(dtype=float)
        for i in range(weeks, len(vals)):
            pred = vals[i - weeks:i].mean()
            if vals[i]:
                errs.append(abs(pred - vals[i]) / vals[i])
        if errs:
            e = pd.Series(errs)
            out[key] = {"median": float(e.median()), "p90": float(e.quantile(0.90)),
                        "n": int(len(e))}
    return out


def percentile(mix: pd.DataFrame, column: str, value: float, years: int = 3) -> float:
    """
    Where this week's share sits against its own recent history.

    A share means little in isolation — 19.7% negotiated is loose or tight only
    against what this market has been doing. Three years rather than the full
    run because the formula share has trended for two decades, and a percentile
    against 2005 would say more about that trend than about this week.
    """
    if mix.empty or column not in mix:
        return float("nan")
    cutoff = mix["week"].max() - pd.Timedelta(weeks=52 * years)
    s = mix[mix["week"] >= cutoff][column].dropna()
    if len(s) < 20:
        return float("nan")
    return float((s < value).mean())
