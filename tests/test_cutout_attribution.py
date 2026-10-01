"""
Why the cutout moved: the primal weights, recovered rather than quoted.

The cutout is a fixed weighted average of the seven primals, and USDA
publishes both sides of that equation daily. So the weights can be SOLVED
instead of typed in, and the residual says whether to believe the answer.

Solved over 260 real reports on 2026-10-01:

    Chuck 29.62%  Round 22.32%  Loin 21.26%  Rib 11.40%
    Plate  7.10%  Brisket 4.95%  Flank 3.35%        -> 100.000%

Summing to 100% was not imposed, and the max residual was 0.008 $/cwt.

The decomposition is the point of the panel, because the biggest MOVER is
routinely not the biggest CAUSE. On 2026-10-01 Choice loin fell 10.09 and
chuck fell 9.22 — but chuck is 29.62% of the carcass and loin 21.26%, so
chuck did -2.73 of the -6.00 and loin -2.15. Reading the primal column alone
puts those in the wrong order.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).parent))
from streamlit_source import load_from_app  # noqa: E402

APP = ROOT / "apps" / "beef_cutout" / "app.py"

# The real shares, as a regression anchor.
TRUE = {"Primal Chuck": 0.2962, "Primal Round": 0.2232, "Primal Loin": 0.2126,
        "Primal Rib": 0.1140, "Primal Plate": 0.0710, "Primal Brisket": 0.0495,
        "Primal Flank": 0.0335}


def _load():
    """Exec the attribution helpers out of the Streamlit script, via ast."""
    return load_from_app(APP, "_cut_numbers", "primal_weights",
                         "cutout_attribution",
                         consts=("CUT_NUM_COLS", "CUT_PRICE_COLS"),
                         globals_={"pd": pd, "np": np})


def _sections(n=120, weights=None, noise=0.0, seed=0):
    """A synthetic feed where the cutout IS the weighted primal average."""
    w = weights or TRUE
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-01-01", periods=n)
    prices = {k: 300 + rng.normal(0, 25, n).cumsum() / 5 for k in w}
    cut = sum(prices[k] * v for k, v in w.items())
    if noise:
        cut = cut + rng.normal(0, noise, n)
    primal = pd.DataFrame([
        {"report_date": d, "primal_desc": k,
         "choice_600_900": f"{prices[k][i]:,.2f}",
         "select_600_900": f"{prices[k][i]:,.2f}"}
        for i, d in enumerate(dates) for k in w
    ])
    cutout = pd.DataFrame({
        "report_date": dates,
        "choice_600_900_current": [f"{v:,.2f}" for v in cut],
        "select_600_900_current": [f"{v:,.2f}" for v in cut],
    })
    return {"Composite Primal Values": primal, "Current Cutout Values": cutout}


def test_the_weights_are_recovered_from_the_data():
    ns = _load()
    names, w, rms = ns["primal_weights"](_sections(), "choice")
    assert names is not None
    got = dict(zip(names, w))
    for k, v in TRUE.items():
        assert got[k] == pytest.approx(v, abs=1e-3), f"{k}: {got[k]:.4f} vs {v}"
    assert rms < 0.02


def test_the_recovered_weights_sum_to_one():
    """Not imposed by the solver — it is what the real data does."""
    ns = _load()
    _, w, _ = ns["primal_weights"](_sections(), "choice")
    assert w.sum() == pytest.approx(1.0, abs=1e-3)


def test_the_effects_sum_to_the_cutout_move():
    """
    The decomposition has to reconcile, or it is decoration. On the live
    page the seven effects summed to -6.00 against a published -6.00.
    """
    ns = _load()
    sections = _sections()
    tbl, _ = ns["cutout_attribution"](sections, "choice")
    cut = ns["_cut_numbers"](sections["Current Cutout Values"])
    c = cut["choice_600_900_current"]
    assert tbl["Effect"].sum() == pytest.approx(c.iloc[-1] - c.iloc[-2], abs=0.01)


def test_the_biggest_mover_need_not_be_the_biggest_cause():
    """
    The reason the Effect column exists. A small primal with a huge move
    must rank BELOW a large primal with a modest one.
    """
    ns = _load()
    sections = _sections()
    primal = sections["Composite Primal Values"]
    last = primal["report_date"].max()
    # Flank (3.35%) jumps 20; Chuck (29.62%) moves 5. Flank is the bigger
    # mover, Chuck is by far the bigger cause.
    def bump(desc, amt):
        m = (primal["report_date"] == last) & (primal["primal_desc"] == desc)
        primal.loc[m, "choice_600_900"] = (
            float(primal.loc[m, "choice_600_900"].iloc[0].replace(",", "")) + amt)
    bump("Primal Flank", 20.0)
    bump("Primal Chuck", 5.0)
    tbl, _ = ns["cutout_attribution"](sections, "choice")
    eff = dict(zip(tbl["Primal"], tbl["Effect"]))
    assert abs(eff["Primal Chuck"]) > abs(eff["Primal Flank"]), (
        "a 20-point flank move is outranking a 5-point chuck move -- the "
        "weighting is not being applied"
    )


def test_a_fit_that_has_gone_bad_shows_nothing():
    """
    A decomposition nobody can stand behind must not be presented as an
    explanation. If USDA re-bases the cutout and the identity stops holding,
    the panel disappears rather than inventing causes.
    """
    ns = _load()
    sections = _sections(noise=40.0, seed=3)
    assert ns["cutout_attribution"](sections, "choice") is None


def test_too_little_history_is_refused():
    ns = _load()
    assert ns["primal_weights"](_sections(n=5), "choice") == (None, None, None)


def test_missing_sections_are_refused():
    ns = _load()
    assert ns["primal_weights"]({}, "choice") == (None, None, None)
    assert ns["cutout_attribution"]({}, "choice") is None
