"""
JSA Daily Cattle Reports — build the client letter from live data.

The authoring surface for the daily letter. Everything it does is a thin
shell over the letter/ package, which is also driven from the command line by
`python -m letter.build`; the two share the data cache and the commentary file
in out/, so a letter started here can be finished there and the other way round.

PASSWORD. This page is gated on its own REPORTS_PASSPHRASE and the rest of the
portal is not. That is deliberate: the dashboards show published USDA data, but a
draft here is Ross's unsent market read, hours before clients pay to receive it.
See portal_auth.py -- the gate fails closed, so set the secret before deploying.

WHAT THIS PAGE CANNOT DO WHEN DEPLOYED. Streamlit Community Cloud runs Linux
containers with no browser, so letter.topdf finds nothing to drive and the
one-click PDF is unavailable there -- the page offers the HTML instead and you
print it with Ctrl+P, which uses the same print CSS and gives the same result.
The container filesystem is also ephemeral, so a draft written on the deployed
app does not survive a reboot. Run this locally for the full path.
"""
import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import portal_auth  # noqa: E402

# Same question the portal asks everywhere else. Signing in on the home page
# opens this too; arriving here directly offers the same box.
portal_auth.require_admin("JSA Daily Cattle Reports")

# -- Secrets -> environment ---------------------------------------------------
# The letter package is a plain library and reads os.environ; st.secrets does
# not exist for it. Copy across an EXPLICIT ALLOWLIST.
#
# SNOWFLAKE_SCHEMA IS DELIBERATELY NOT IN THIS LIST AND MUST NEVER BE. CLAUDE.md
# records that five bundled modules each default it to the schema they own, so
# setting it to any one value silently empties the other four -- pages load,
# queries miss, nothing raises.
_ALLOWED_SECRETS = (
    "MARS_API_KEY", "MASSIVE_API_KEY",
    "USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_PRIVATE_KEY", "SNOWFLAKE_PRIVATE_KEY_PWD",
)
for _name in _ALLOWED_SECRETS:
    try:
        _value = st.secrets.get(_name, "")
    except Exception:
        _value = ""
    if _value and not os.environ.get(_name):
        os.environ[_name] = str(_value)

from letter import build as letter_build  # noqa: E402
from letter import (archive, commentary, config, headlines, mailbox, render,  # noqa: E402
                    settle_log, topdf)

# ...then .env, for anything the secrets did not supply.
#
# WITHOUT THIS THE PAGE QUIETLY READS THE WRONG DATABASE. st.secrets is the only
# source above, and .streamlit/secrets.toml carries just the passphrase -- so
# USE_SNOWFLAKE was never set, snowflake_db fell back to the committed SQLite
# file, and the feeder index rendered 327.60 from 2026-09-04: a real-looking
# number nearly three weeks old, in a client letter, with no error anywhere.
# load_env() uses setdefault, so anything already set above still wins.
letter_build.load_env()

OUT = REPO / "out"

st.markdown("""
<style>
  .wcr-head { font-family:'EB Garamond',Georgia,serif; color:#32373c;
              font-size:1.8rem; margin:0 0 2px; }
  .wcr-sub  { color:#64748b; font-size:0.9rem; margin-bottom:18px; }
  .wcr-fig  { font-size:0.84rem; color:#32373c; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="wcr-head">JSA Daily Cattle Reports</div>'
            '<div class="wcr-sub">Pull the numbers, write the read, print the letter.</div>',
            unsafe_allow_html=True)

# Say so loudly rather than letting a stale number look current. The SQLite
# fallback is a committed file that stopped moving weeks ago.
if not os.environ.get("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on"):
    st.error(
        "**Not connected to Snowflake.** The feeder cattle index and Douglas imports "
        "will come from the committed SQLite file, which is weeks out of date. "
        "Set `USE_SNOWFLAKE=1` and the Snowflake settings in `.env` before using "
        "anything from this page in a client letter."
    )


# -- Controls -----------------------------------------------------------------

c0, c1, c2 = st.columns([1.4, 1.8, 4])
with c0:
    # Two reports a day, each with its own five weekdays. Independent of the
    # day: AM Monday and PM Monday are different letters.
    # Opens on the report you are most likely writing: AM before noon Central,
    # PM after. Only the DEFAULT moves -- Streamlit keeps a widget's value
    # across reruns, so picking the other one sticks, including across noon.
    session = st.radio("Report", config.SESSIONS,
                       index=config.SESSIONS.index(config.session_for_now()),
                       horizontal=True,
                       help="Defaults to the morning brief before noon Central "
                            "and the evening letter after it.").lower()
with c1:
    issue = st.date_input("Issue date", value=date.today(), format="YYYY-MM-DD")
with c2:
    # `day` is what you pick; `kind` is which of the THREE evening layouts it
    # produces -- Tuesday the full letter, Friday the week-in-review, and
    # Mon/Wed/Thu the recap. The AM ignores the day entirely.
    # See config.FORMAT_FOR_DAY.
    default_day = config.day_for_date(issue)
    day = st.radio(
        "Letter", config.DAYS, horizontal=True,
        index=config.DAYS.index(default_day.title()),
        help="Defaults to the weekday of the issue date. Tuesday is the full "
             "evening letter, Friday the week-in-review, and Mon/Wed/Thu the "
             "shorter recap. The morning brief is the same every day.",
    ).lower()
kind = config.format_for(day, session)

if kind == "friday":
    st.caption("**Week-in-review format** — adds regional cash, CFTC, and a Cattle on "
               "Feed block on release weeks. CFTC lands 3:30pm ET, boxed beef about "
               "3pm Central; build after both.")
elif kind == "recap":
    # THREE PM FORMATS, THREE CAPTIONS. This branch was missing when the recap
    # landed, so Mon/Wed/Thu fell through to "Standard format" -- the page
    # naming a letter you are not writing, while the boxes below it showed the
    # recap's sections. Wrong labels on an authoring page are worse than none.
    st.caption("**Recap format** — the session in brief: one technicals read "
               "covering both products, and no Fundamental Rundown. Boxed beef "
               "publishes about 3pm Central; build after that.")
else:
    st.caption("**Standard format** — leads with last week's cash trade. Boxed beef "
               "publishes about 3pm Central; build after that or the cutout is "
               "yesterday's (the letter labels it honestly either way).")

# Analyst pre-report estimates. USDA does not publish these and nothing derives
# them, so the column is blank unless they are typed in.
cof_guesses = {}
if kind == "friday":
    with st.expander("Cattle on Feed guesses (only used on release weeks)"):
        g1, g2, g3 = st.columns(3)
        for col, key, label in ((g1, "on_feed", "On-Feed"), (g2, "placed", "Placed"),
                                (g3, "marketed", "Marketed")):
            with col:
                v = st.number_input(label, min_value=0.0, max_value=200.0,
                                    value=0.0, step=0.1, format="%.1f", key=f"cof_{key}")
                if v:
                    cof_guesses[key] = v

slug = f"{session}_{day}"
data_path = OUT / f"data_{slug}_{issue}.json"
cpath = commentary.path_for(OUT, issue, slug)

b1, b2 = st.columns([1, 3])
with b1:
    fetch = st.button("Fetch latest data", type="primary", use_container_width=True)
with b2:
    if data_path.exists():
        st.caption(f"Using saved data from `{data_path.name}`. Fetch again to refresh.")
    else:
        st.caption("No data pulled for this date yet.")


# -- Data ---------------------------------------------------------------------

def _load_ctx():
    """Fetched context for this issue, from the cache unless asked to refresh."""
    import json
    if data_path.exists():
        ctx = json.loads(data_path.read_text(encoding="utf-8"))
        ctx["issue_date"] = issue
        ctx["kind"] = kind
        ctx["session"] = session
        return ctx, []
    return None, []


if fetch:
    with st.spinner("Fetching USDA, futures and Snowflake…"):
        import json
        errors = []
        ctx = letter_build.gather(issue, errors, kind, cof_guesses)
        ctx["session"] = session
        # Log today's settles and chain the weekly change, same as the CLI.
        settle_log.record(ctx)
        letter_build.backfill_week_base(ctx, OUT, issue)
        OUT.mkdir(parents=True, exist_ok=True)
        data_path.write_text(json.dumps(ctx, indent=2, default=letter_build._jsonable),
                             encoding="utf-8")
        st.session_state["wcr_errors"] = errors
    st.rerun()

ctx, _ = _load_ctx()
errors = st.session_state.get("wcr_errors", [])

if ctx is None:
    st.info("Press **Fetch latest data** to pull this issue's numbers.")
    st.stop()

if errors:
    with st.expander(f"{len(errors)} source(s) reported a problem", expanded=True):
        for e in errors:
            st.warning(e)

# -- Prior-Friday settles -----------------------------------------------------
# Only appears when the futures history has no bar for the prior Friday, which
# is when the week-over-week change cannot be computed. The numbers are on your
# own last letter. Saved to out/weekbase_<kind>_<date>.json so the CLI and a
# later re-render use the same ones.

wb_path = letter_build.week_base_path(OUT, issue, day)
saved_bases = letter_build.load_week_base(wb_path)
letter_build.apply_week_base(ctx, saved_bases)

still_missing = letter_build.missing_week_bases(ctx)
if still_missing:
    st.warning(
        f"**No prior-Friday settle for {len(still_missing)} contract(s).** The futures "
        "history has a hole, so the week-over-week change cannot be computed. Enter "
        "the settles from your previous letter below and they will be used."
    )
    with st.form("week_base"):
        entered = {}
        cols = st.columns(min(3, len(still_missing)))
        for i, (ticker, label) in enumerate(still_missing):
            with cols[i % len(cols)]:
                v = st.number_input(label, min_value=0.0, max_value=1000.0,
                                    value=float(saved_bases.get(ticker, 0.0)),
                                    step=0.025, format="%.3f", key=f"wb_{ticker}")
                if v:
                    entered[ticker] = v
        if st.form_submit_button("Use these settles", use_container_width=True):
            merged = dict(saved_bases)
            merged.update(entered)
            letter_build.save_week_base(wb_path, merged)
            st.rerun()


# -- What came back -----------------------------------------------------------

with st.expander("Figures pulled", expanded=False):
    fig_cols = st.columns(3)
    cash = ctx.get("cash") or {}
    cut = ctx.get("cutout") or {}
    dsl = ctx.get("daily_slaughter") or {}
    cw = ctx.get("carcass_weights") or {}
    fci = ctx.get("fci") or {}

    with fig_cols[0]:
        st.markdown("**Cash trade**")
        st.markdown(
            f"<div class='wcr-fig'>Live {cash.get('live', {}).get('this_week')} "
            f"(was {cash.get('live', {}).get('last_week')})<br>"
            f"Dressed {cash.get('dressed', {}).get('this_week')} "
            f"(was {cash.get('dressed', {}).get('last_week')})</div>",
            unsafe_allow_html=True)
    with fig_cols[1]:
        st.markdown("**Slaughter & weights**")
        st.markdown(
            f"<div class='wcr-fig'>Daily {dsl.get('current_day')}<br>"
            f"WTD {dsl.get('wtd')}<br>"
            f"Carcass {cw.get('value')}# (w/e {cw.get('week_ending')})</div>",
            unsafe_allow_html=True)
    with fig_cols[2]:
        st.markdown("**Cutout & index**")
        st.markdown(
            f"<div class='wcr-fig'>Choice {cut.get('choice', {}).get('value')}<br>"
            f"Select {cut.get('select', {}).get('value')}<br>"
            f"Feeder index {fci.get('value')}</div>",
            unsafe_allow_html=True)

# -- Commentary ---------------------------------------------------------------

# -- Headline candidates (AM only) --------------------------------------------
# Rendered BEFORE the text areas below, because adding a headline writes into
# the Headlines box's session_state -- and Streamlit refuses that once the
# widget has been instantiated.
#
# NOTHING HERE IS AUTO-INSERTED. It is a pick list. Every other figure in the
# brief is a USDA or CME number that is either right or marked [[?]]; a headline
# is editorial, and there is no [[?]] for a feed surfacing something misleading
# under JSA's name.
#
# WHICH FORMATS GET IT IS DERIVED, NOT HARDCODED. This was `kind == "am"` until
# 2026-09-23, when the evening letter gained a Headlines section and the pick
# list silently did not follow -- a box to type headlines into and no list to
# pick them from. Asking the format which section it has means adding one to a
# third format is a one-line change in commentary.py and nothing here.
#
# Friday picks up the panel for its Key Headlines as a side effect, which it
# should have had all along: same editorial job, same pick-then-rewrite rule.
_head_key, _head_title = next(
    ((k, t) for k, t in commentary.sections_for(kind)
     if k in ("headlines", "key_headlines")), (None, None))

if _head_key:
    with st.expander("Headline candidates", expanded=False):
        if st.button("Fetch headlines", use_container_width=False):
            with st.spinner("Reading Beef Magazine, the USDA narratives and packer news…"):
                st.session_state["wcr_heads"] = headlines.candidates(issue)

        # Mailbox sign-in, only when it is actually needed. Device-code flow:
        # no password is typed here or stored anywhere by this app.
        if not mailbox.configured():
            st.caption("To include the Meatingplace and eMeat digests, set "
                       "`GRAPH_CLIENT_ID` and `GRAPH_TENANT_ID` in `.env`.")
        elif (st.session_state.get("wcr_heads") or {}).get("needs_sign_in"):
            flow = st.session_state.get("wcr_graph_flow")
            if not flow:
                if st.button("Connect mailbox"):
                    _, f = mailbox.token(interactive=True)
                    st.session_state["wcr_graph_flow"] = f
                    st.rerun()
            elif flow.get("error"):
                st.warning(flow["error"])
            else:
                st.info(flow.get("message", "Sign in with the code shown."))
                if st.button("I've signed in"):
                    with st.spinner("Completing sign-in…"):
                        ok = mailbox.complete_sign_in(flow)
                    st.session_state.pop("wcr_graph_flow", None)
                    if ok:
                        st.session_state["wcr_heads"] = headlines.candidates(issue)
                    st.rerun()

        found = st.session_state.get("wcr_heads")
        if not found:
            st.caption("Beef Magazine, USDA's own cash-trade and border narratives, and a "
                       "news search for Tyson/JBS/Cargill/National Beef and plant "
                       "disruption — last 48 hours. Pick what matters and rewrite it in "
                       "your words — nothing here goes into the letter on its own.")
        else:
            for err in found.get("errors", []):
                st.caption(f"⚠ {err}")
            # A GENERATION NUMBER IN THE CHECKBOX KEY, so clearing the ticks
            # never writes to a widget that already exists. Assigning
            # st.session_state["head_<n>"] = False after the loop is the obvious
            # way to reset them and it raises StreamlitWidgetAlreadyInstantiated-
            # Error every time -- the checkboxes were built moments earlier in
            # this same run, and Streamlit refuses to have their state written
            # behind their back. It crashed the page on the first real use of
            # the Add button, 2026-09-24, mid-letter.
            #
            # Bumping the generation asks for a DIFFERENT set of widgets on the
            # next run instead. They have never been instantiated, so they start
            # unchecked with nothing assigned to them.
            gen = st.session_state.get("wcr_head_gen", 0)
            picked = []
            for n, item in enumerate(found.get("items", [])):
                age = (f"{item['age_h']}h ago" if item.get("age_h") is not None
                       else str(item.get("when") or "")[:16])
                label = item["title"]
                if len(label) > 150:
                    label = label[:150] + "…"
                if st.checkbox(label, key=f"head_{gen}_{n}"):
                    picked.append(item["title"])
                st.caption(f"{item['source']} · {age}"
                           + (f" · [open]({item['link']})" if item.get("link") else ""))
            if picked and st.button(f"Add {len(picked)} to {_head_title}", type="primary"):
                # The target box is the one THIS format calls its headline
                # section -- wcr_headlines on AM and PM, wcr_key_headlines on
                # Friday. Hardcoding it wrote Friday's picks into a widget that
                # does not exist on Friday.
                _box = f"wcr_{_head_key}"
                existing = st.session_state.get(_box, "")
                lines = [ln for ln in existing.splitlines() if ln.strip()]
                lines.extend(picked)
                # Writing to the TEXT AREA's key is fine and is why this whole
                # panel is rendered above them: wcr_<section> has not been
                # instantiated yet at this point in the script. The checkboxes
                # have been, which is why they get a new generation instead.
                st.session_state[_box] = "\n".join(lines)
                st.session_state["wcr_head_gen"] = gen + 1
                st.rerun()

st.subheader("Your read")
st.caption("One bullet per line. Blank sections are left out of the letter entirely.")

# Seed the boxes with whatever is on disk so the CLI and this page stay in sync.
commentary.write_template(cpath, letter_build.hints(ctx, kind), kind)
saved = commentary.read(cpath, kind)

hints = letter_build.hints(ctx, kind)
edited = {}
for key, title in commentary.sections_for(kind):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        if hints.get(key):
            with st.expander("Figures for reference", expanded=False):
                for line in hints[key]:
                    st.caption(line)
        edited[key] = st.text_area(
            title, value="\n".join(saved.get(key, [])), height=140,
            label_visibility="collapsed", key=f"wcr_{key}",
            placeholder="One bullet per line…",
        )

sections = {k: [ln.strip() for ln in v.splitlines() if ln.strip()]
            for k, v in edited.items()}

s1, s2 = st.columns([1, 3])
with s1:
    if st.button("Save draft", use_container_width=True):
        commentary.write_sections(cpath, sections, kind)
        st.success("Saved.")
with s2:
    st.caption(f"Draft file: `{cpath.name}` — shared with `python -m letter.build`.")

# -- Build --------------------------------------------------------------------

st.subheader("Letter")

ctx_for_render = dict(ctx)
ctx_for_render["issue_date"] = issue
ctx_for_render["kind"] = kind
ctx_for_render["session"] = session
ctx_for_render["commentary"] = sections

# -- Chart of the day (morning brief only) ------------------------------------
# Picked from what you just typed, then from what moved, then a rotation. Chosen
# HERE rather than in the fetch, because `sections` is the live text in the
# boxes -- edit a headline and the chart re-aims on the next rerun.
if kind == "am":
    _choices = ["Auto"] + [e["key"] for e in config.CHART_POOL]
    k1, k2 = st.columns([1, 3])
    with k1:
        _forced = st.selectbox("Chart of the day", _choices, index=0,
                               help="Auto reads your headlines first, then the "
                                    "biggest mover, then a rotation.")
    # Whatever "Fetch headlines" already pulled, if anything. Never fetched for
    # the chart's sake -- press the button and the chart aims itself at the
    # day's news; do not and it falls through to the biggest mover.
    _cands = (st.session_state.get("wcr_heads") or {}).get("items") or None
    ctx_for_render["chart"] = letter_build.build_chart(
        ctx_for_render, issue, os.environ.get("MASSIVE_API_KEY", "").strip(), [],
        forced="" if _forced == "Auto" else _forced, candidates=_cands)
    with k2:
        _c = ctx_for_render.get("chart") or {}
        st.caption(f"**{_c.get('title', 'no chart')}** — {_c.get('reason', 'unavailable')}"
                   if _c else "No chart: no series came back for any market in the pool.")

html = render.build_html(ctx_for_render)

missing = html.count(render.MISSING)
if missing:
    st.warning(f"{missing} value(s) could not be filled. They are marked in the letter "
               "so they cannot be missed — fill them in or fix the source before sending.")

# PRINT FROM THE READER'S OWN BROWSER, which is the one machine in this picture
# that definitely has one. letter.topdf drives headless Edge on the HOST, so on
# Streamlit Cloud -- a bare Linux container -- there is nothing to drive and the
# Build PDF button is disabled. This sidesteps that entirely: the preview below
# is already an iframe holding the complete letter with its own @page rules, so
# window.print() inside it prints exactly that document. Same print CSS, same
# result as Build PDF, and it works on the deployed app.
#
# The button hides itself in the print output -- it is chrome, not letter.
_print_ui = """
<style>
  #jsa-print { position: sticky; top: 0; z-index: 99; display: block; width: 100%;
    padding: 7px 0; font: 600 14px/1.2 "Segoe UI", system-ui, sans-serif;
    color: #fff; background: #5e7164; border: 0; border-radius: 4px;
    cursor: pointer; margin: 0 0 10px; }
  #jsa-print:hover { background: #4d5d52; }
  @media print { #jsa-print { display: none !important; } }
</style>
<button id="jsa-print" onclick="window.focus();window.print();">
  Print / Save as PDF &nbsp;·&nbsp; uses this browser
</button>
"""
st.components.v1.html(_print_ui + html, height=720, scrolling=True)
st.caption("**Print / Save as PDF** prints the preview above from your own browser — "
           "same print CSS as Build PDF, and it works on the deployed app where "
           "Build PDF cannot. Choose *Save as PDF* as the destination.")

d1, d2 = st.columns(2)
with d1:
    st.download_button("Download HTML", data=html.encode("utf-8"),
                       file_name=f"{config.title_for(session)} {day.title()} {issue}.html",
                       mime="text/html", use_container_width=True)
with d2:
    browser = topdf.find_browser()
    if browser:
        if st.button("Build PDF", type="primary", use_container_width=True):
            OUT.mkdir(parents=True, exist_ok=True)
            html_path = OUT / f"{config.title_for(session)} {day.title()} {issue}.html"
            pdf_path = OUT / f"{config.title_for(session)} {day.title()} {issue}.pdf"
            html_path.write_text(html, encoding="utf-8")
            ok, msg = topdf.html_to_pdf(html_path, pdf_path)
            if ok:
                st.session_state["wcr_pdf"] = pdf_path.read_bytes()
                st.success(f"Built {pdf_path.name}")
            else:
                st.error(f"PDF failed — {msg}")
    else:
        # THE REASON IS VISIBLE, NOT A TOOLTIP. This was help= only, and a greyed
        # button with a hover explanation reads as broken -- it got reported as a
        # bug on 2026-09-24 by the person who wrote the docstring explaining it.
        # Someone looking at a disabled control is asking why, and a hover they
        # have to guess at is not an answer.
        st.button("Build PDF", disabled=True, use_container_width=True)
        st.caption("No browser on this host — download the HTML and print with "
                   "Ctrl+P. Same layout, same result.")

if st.session_state.get("wcr_pdf"):
    st.download_button("Download PDF", data=st.session_state["wcr_pdf"],
                       file_name=f"{config.title_for(session)} {day.title()} {issue}.pdf",
                       mime="application/pdf", use_container_width=True)

# -- Archive ------------------------------------------------------------------
# AFTER SENDING, NOT INSTEAD OF IT. This copies the rendered letter into the
# private jsa-letter-archive repo and pushes. It is a separate button on purpose:
# "published" means Ross emailed it, which nothing here can detect, and archiving
# every build would bury the one that went out under a day of drafts.
#
# Unavailable on the deployed app -- no clone, no push credentials -- so it says
# so rather than offering a button that cannot work.
_arch_ok, _arch_why = archive.available()
st.divider()
if not _arch_ok:
    st.caption(f"Archive unavailable — {_arch_why}. Run locally to archive a sent letter.")
else:
    a1, a2 = st.columns([1, 3])
    with a1:
        if st.button("Archive as sent", use_container_width=True):
            OUT.mkdir(parents=True, exist_ok=True)
            _hp = OUT / f"{config.title_for(session)} {day.title()} {issue}.html"
            _hp.write_text(html, encoding="utf-8")
            _pp = OUT / f"{config.title_for(session)} {day.title()} {issue}.pdf"
            res = archive.publish(issue, session, _hp, _pp if _pp.exists() else None,
                                  kind=kind, title=config.title_for(session))
            if not res["ok"]:
                st.error(f"Not archived — {res['reason']}")
            elif not res["changed"]:
                st.info("Already archived, unchanged.")
            else:
                st.success("Archived and pushed." if res["pushed"]
                           else f"Committed locally. {res['reason']}")
    with a2:
        st.caption("Press this for the letter you actually sent. It copies the HTML "
                   "and PDF into the private archive repo and pushes — re-sending a "
                   "corrected letter keeps the earlier one in git history.")
