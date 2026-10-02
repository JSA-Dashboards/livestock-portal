"""
How the Monday Print Forecast has actually been doing.

Replays the forecast at the SAME POINT IN THE WEEK it is standing at right
now, for each recent week, and compares it with the figure USDA went on to
print. Two columns, because the tab's two steps fail differently and a single
accuracy number would hide that: the 5-Area call and the national one are
scored separately.

THE FORECAST FUNCTIONS ARE PASSED IN RATHER THAN IMPORTED, and that is the
whole point of this module existing. A scorecard that reimplements the thing
it scores grades a copy: the copy drifts, the page keeps its own behaviour,
and the scorecard reports on code nobody runs. `apps/cash_trade/app.py` is a
Streamlit script and cannot be imported, so the page hands its own
forecast_5area and forecast_national in and this replays those exact objects.

WHY THE CHECKPOINT MATCHES THE LIVE ONE instead of always scoring Friday's
1:30 pm cut. Accuracy is overwhelmingly a function of how far into the week
you are standing -- measured over 52 Friday checkpoints, the busiest quarter
of weeks land within a median 3% while the quietest are a median 36% out. A
scorecard fixed on Friday would therefore flatter a Wednesday reading of the
page by a factor of ten. Scoring past weeks at the same weekday and cut makes
the number underneath the forecast describe the forecast above it.

RECONSTRUCTION IS HONEST HERE, which is not something to assume -- the sibling
FCI scorecard exists precisely because reconstructing ITS estimate flatters it,
the input table growing as late auctions land until a replayed call has seen
data the real one never did. Checked 2026-10-02 rather than argued by analogy:

  - LM_CT150 History, the figure this scores AGAINST, carried **0** rows
    flagged `is_correction` over twelve months. The target never moves.
  - The daily /Summary files this replays FROM carried 44 corrections in
    8,160 rows, 0.54%. Rare and discrete, not the systematic upward drift the
    FCI case has.

So a replayed call is the call we would have made, to within half a percent of
input rows. The remaining exposure is real but small, and the fix for it is to
freeze each call when it is made rather than to stop replaying -- see
`capture_snapshots` in the cme-feeder-cattle-index repo for that shape.

Every week is replayed STRICTLY OUT OF SAMPLE: the analogue pool, the maturity
baseline and the 5-Area-to-national gap are all cut to weeks that had already
printed. Letting any of them see the week being scored would be marking our own
homework with the answers in front of us.
"""
from __future__ import annotations

import pandas as pd


def _truncate(vol: pd.DataFrame, week: pd.Timestamp, weekday: int, order: int,
              cut_order: dict) -> pd.DataFrame:
    """
    `vol` as it stood at one checkpoint: every earlier week in full, plus the
    scored week up to and including that publication and no further.

    The exclusion is what makes the replay out of sample. For a Friday 1:30 pm
    checkpoint the row that must not survive is Friday's MORNING file, which is
    published the following Monday and carries the finished week -- i.e. the
    answer.
    """
    if vol.empty:
        return vol
    v = vol.copy()
    v_week = v["trade_date"] - pd.to_timedelta(v["trade_date"].dt.weekday, unit="D")
    v_day = v["trade_date"].dt.weekday
    v_ord = v["cut"].map(cut_order)
    keep = (v_week < week) | (
        (v_week == week) & ((v_day < weekday) | ((v_day == weekday) & (v_ord <= order))))
    return v[keep]


def _checkpoints_before(vol: pd.DataFrame, week: pd.Timestamp, weekday: int,
                        order: int, cut_order: dict):
    """The publication immediately preceding one checkpoint, within its week."""
    if vol.empty:
        return None
    v = vol[vol["period"] == "wtd"].copy()
    if v.empty:
        return None
    v_week = v["trade_date"] - pd.to_timedelta(v["trade_date"].dt.weekday, unit="D")
    v = v[v_week == week]
    if v.empty:
        return None
    pairs = sorted({(int(d.weekday()), int(cut_order.get(c, 0)))
                    for d, c in zip(v["trade_date"], v["cut"])})
    before = [p for p in pairs if p < (weekday, order)]
    return before[-1] if before else None


def build_scorecard(vol: pd.DataFrame, published5: pd.Series, national: pd.Series,
                    forecast_5area, forecast_national, cut_order: dict,
                    weeks: int = 10) -> pd.DataFrame:
    """
    One row per scored week, newest first.

    Returns empty when the live forecast cannot be formed or no past week
    published at the same checkpoint -- an empty frame is the page's cue to say
    so rather than to print an accuracy built on one or two weeks.
    """
    live = forecast_5area(vol, published5)
    if not live or published5.empty:
        return pd.DataFrame()

    cp = live["checkpoint"]
    weekday, order = int(cp["weekday"]), int(cp["order"])
    cur_week = pd.Timestamp(live["week"])

    # ONCE FRIDAY'S FINAL HAS LANDED THE LIVE CHECKPOINT IS THE ANSWER, not a
    # forecast of it -- forecast_5area reports done=True and returns the
    # week-to-date unchanged. Scoring past weeks at that same checkpoint would
    # compare each answer with itself: a perfect record, truthfully computed,
    # describing nothing. Step back to the last checkpoint that still had
    # something to predict, which is also the most useful reading there is on a
    # Monday -- it is the call we actually made before the print.
    if live.get("done"):
        earlier = _checkpoints_before(vol, cur_week, weekday, order, cut_order)
        if earlier is None:
            return pd.DataFrame()
        weekday, order = earlier

    # Only weeks USDA has printed can be scored, and published5 holds exactly
    # those -- so the live week belongs in the list once its figure lands,
    # which is the week anyone opening this on a Monday wants to see.
    candidates = [w for w in published5.index if w <= cur_week]
    candidates.sort(reverse=True)

    rows = []
    for w in candidates:
        if len(rows) >= weeks:
            break
        sub_vol = _truncate(vol, w, weekday, order, cut_order)
        sub_p5 = published5[published5.index < w]
        sub_nat = national[national.index < w]
        if sub_p5.empty or sub_nat.empty:
            continue
        f5 = forecast_5area(sub_vol, sub_p5)
        if not f5:
            continue
        # The week must have published at the SAME checkpoint, or we would be
        # comparing a Thursday call against a Friday one and calling it a week.
        c = f5["checkpoint"]
        if int(c["weekday"]) != weekday or int(c["order"]) != order:
            continue
        if pd.Timestamp(f5["week"]) != pd.Timestamp(w):
            continue

        fn = forecast_national(f5, sub_p5, sub_nat)
        actual5 = float(published5.get(w, float("nan")))
        actualn = float(national.get(w, float("nan")))
        rows.append({
            "week": pd.Timestamp(w),
            "wtd": f5["wtd"],
            "grade": f5.get("grade"),
            "f5": f5["central"], "f5_lo": f5["low"], "f5_hi": f5["high"],
            "a5": actual5,
            "fn": fn.get("central") if fn else float("nan"),
            "fn_lo": fn.get("low") if fn else float("nan"),
            "fn_hi": fn.get("high") if fn else float("nan"),
            "an": actualn,
        })

    sc = pd.DataFrame(rows)
    if sc.empty:
        return sc
    for side, f, a, lo, hi in (("5", "f5", "a5", "f5_lo", "f5_hi"),
                               ("n", "fn", "an", "fn_lo", "fn_hi")):
        sc[f"miss{side}"] = sc[f] - sc[a]
        sc[f"pct{side}"] = sc[f"miss{side}"] / sc[a]
        sc[f"in{side}"] = (sc[a] >= sc[lo]) & (sc[a] <= sc[hi])
    return sc


def summarise(sc: pd.DataFrame) -> dict:
    """
    Headline accuracy over the scored weeks.

    Median absolute percentage rather than mean: the misses are right-skewed
    (late trade can surprise upward and cannot go below zero), so a mean is
    dragged by the one back-loaded week in ten and describes none of them.
    """
    if sc.empty:
        return {}
    out = {"n": int(len(sc))}
    for side, label in (("5", "five"), ("n", "nat")):
        pct, inb = sc[f"pct{side}"].abs(), sc[f"in{side}"]
        out[label] = {
            "median_abs_pct": float(pct.median()),
            "median_abs_head": float(sc[f"miss{side}"].abs().median()),
            "in_band": float(inb.mean()),
            "within_10": float((pct <= 0.10).mean()),
            "bias": float(sc[f"pct{side}"].median()),
        }
    return out
