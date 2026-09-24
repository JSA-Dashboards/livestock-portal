# JSA Livestock Portal

A single Streamlit process (`Home.py`) bundling twelve livestock dashboards
under `apps/`: CME Feeder Cattle Index, Seasonal Futures & Spreads, Cattle on
Feed, US Cow Herd, Mexican Feeder Imports, Fed Cattle Crush, Backgrounding
Crush, Cattle Weights, Beef Cutout, Beef Trimmings, Livestock Inventory, Cash
Cattle Trade.

`Cattle Weights` was renamed from `Beef Weight` on 2026-09-10. Only the visible
label changed — the folder is still `apps/beef_weight/` and the `url_path` is
still `beef-weight`, deliberately, so existing bookmarks keep working. Do not
"tidy" either one.

## Never set SNOWFLAKE_SCHEMA in this app's secrets

Five bundled modules read Snowflake and each defaults `SNOWFLAKE_SCHEMA` to
the schema **it** owns:

| module | its default |
|---|---|
| `apps/beef_weight/nass_cache_client.py` | `NASS_CACHE` |
| `apps/livestock_inventory/nass_cache_client.py` | `NASS_CACHE` |
| `apps/cme_feeder_cattle/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/us_cow_herd/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/mexican_feeder_imports/snowflake_db.py` | `CME_FEEDER_CATTLE` |

Setting it to any one value overrides all five and silently breaks the others.
Pages load, queries miss, charts come back empty, nothing raises. **Unset is the
only working configuration.** `SNOWFLAKE_DATABASE = "JSA"` is safe to set.

## Pushing to GitHub does not deploy

This repo moved from a personal account into the `JSA-Dashboards` org. Streamlit
has the app registered under the old owner path, so the webhook fires, returns
`200 OK`, and does nothing — no error anywhere.

To ship: push, then **Manage app → ⋮ → Reboot app** on the live URL. Allow 2–5
minutes; the "not found" page partway through provisioning is normal. The app
is in the `jsa-dashboards` workspace — see Deployment facts, which was wrong
about this until 2026-09-24.

A reboot does a full fresh clone, so it always takes current `master` — the
startup log says `Cloning repository... Pulling code changes from Github`.

**DO NOT TRUST THAT LOG'S TIMESTAMP TO TELL YOU WHETHER A REBOOT LANDED.**
Manage app → the log panel serves a CACHED view, and in a browser session left
open across several reboots it freezes: on 2026-09-24 it read `[14:20:35]`
through five further reboots that had all in fact succeeded. Reloading the app
URL, even cache-busted, does not refresh it. That stale reading nearly produced
a delete-and-redeploy of a perfectly healthy app.

The reliable check is to **look for a feature that only exists in the new code**
— a button, a caption, a label you just added. The page cannot fake that. Use
the log for what it is good at, which is seeing whether the dependency install
failed, not for which commit is live.

THE STATED CAUSE ABOVE IS NOW IN DOUBT. It was written when this app was
believed to live in the personal workspace, and that turned out to be false, so
"registered under the old owner path" may no longer be the reason — or may no
longer be true at all. Nobody has tested whether a bare push now auto-deploys.
The reboot step is still correct and still the safe habit; only the explanation
is unverified.

## Required secrets

Beyond the Snowflake block (`USE_SNOWFLAKE=1`, `SNOWFLAKE_ACCOUNT`/`USER`/
`PASSWORD`/`ROLE`/`WAREHOUSE`/`DATABASE`, **no** `SNOWFLAKE_SCHEMA`):

- `MARS_API_KEY` — Beef Trimmings. Reads USDA MARS `NW_LS421`. No fallback: the
  page fails on load without it.
- `NASS_API_KEY` — Cattle on Feed. Still calls USDA NASS live. No fallback.
- `MASSIVE_API_KEY` — Seasonal Futures & Spreads
- `ANTHROPIC_API_KEY` — the Ask AI tab
- `CHAT_PASSPHRASE`

**US Cow Herd and Mexican Feeder Imports need NO new secret.** They are
read-only over Snowflake; every USDA/Census credential they depend on
(`MARS_API_KEY`, `CENSUS_API_KEY`) belongs to the *ingest*, which runs in the
cme-feeder-cattle-index repo on Ross's desktop and pushes to
`JSA.CME_FEEDER_CATTLE`. Adding `CENSUS_API_KEY` to this app's secrets would be
dead config. Their analytics modules (`herd.py`, `border.py`) deliberately do
not import `requests` so the Streamlit process cannot acquire an HTTP path.

Both API keys previously had hardcoded fallbacks committed to this public repo.
Those were removed 2026-09-06 — a missing key now fails loudly, which is the
intent. Do not reintroduce a literal.

## Apps sharing code do not share secrets

Cattle Weights, Beef Trimmings, Livestock Inventory, Cattle on Feed, CME
Feeder Cattle Index and Livestock Seasonal all also exist as standalone repos
running the same files. Each deployment has its own secrets. Removing a secret
here does nothing to the standalone app — and vice versa. Check both.

US Cow Herd and Mexican Feeder Imports have no standalone twin, so they are the
two you can change here without checking elsewhere.

A related trap, and the worst one here: `snowflake_db.py` now exists **five
times** — under `apps/cme_feeder_cattle/`, `apps/us_cow_herd/`,
`apps/mexican_feeder_imports/`, `apps/fed_cattle_crush/` and
`apps/backgrounding_crush/` — plus a sixth copy in the cme-feeder-cattle-index
repo. `cash_calves.py` exists twice here and once there.

Each page does `sys.path.insert(0, <its own dir>)`, but Python caches modules by
NAME in `sys.modules`, so whichever page loads first wins and every other page
gets ITS copy. All six are byte-identical today, which is the only reason this
works. A page running against another page's connection logic raises nothing and
gives no clue which copy it got.

`tests/test_no_drift.py` in the cme-feeder-cattle-index repo now compares EVERY
copy, not just one pair — run it after touching any shared module:

    cd ../cme-feeder-cattle-index && .venv/Scripts/python.exe -m pytest tests/ -q

The same applies to `app.py` for CME Feeder Cattle Index, which also lives in
the cme-feeder-cattle-index repo. The two are deliberately NOT identical (the
standalone calls `set_page_config`, loads `.env`, and uses its own palette), so
diff before copying — but a layout or logic fix belongs in both.

## Deployment facts

- Branch `master`, main file `Home.py`, Python 3.14
- Live at `jsa-livestock.streamlit.app`
- Hosted in the **`jsa-dashboards` org workspace** on Streamlit Community
  Cloud, listed as `livestock-portal ∙ master ∙ Home.py`, alongside
  basis-tracker, beef-weight-dashboard, ethanol-margin-matrix,
  jsa-risk-analyzer and soy-crush-calculator. The personal `baldwinrv`
  workspace is **empty** — nothing to find there.

  This entry read "personal workspace, not the org one" until 2026-09-24,
  recording a move attempt on 2026-09-05 that "failed and was reverted". The
  move did land at some point after that; verified 2026-09-24 by signing in
  and rebooting from the org workspace. Nothing needs retrying, and looking in
  the personal workspace finds an empty page rather than an error.

## The crush pages

Two margin calculators added 2026-09-13/14: **Fed Cattle Crush** (buy a feeder,
sell a fat) and **Backgrounding Crush** (buy a calf, sell a feeder). Both seed
from live data — CME futures via Massive, cash calf prices and delivered corn
from Snowflake — and let the user override everything.

Domain decisions in these that look like oversights and are not:

- **Plant shrink is on the fed page and deliberately NOT on backgrounding.**
  A packer pays on a shrunk scale weight, so the fed page computes a pay weight
  (4% default, USDA's basis for cattle sold off feed). The backgrounding page
  prices against the CME feeder index, which is *already* quoted "FOB, 3%
  standing shrink" — applying shrink again would double-count and understate the
  calf bid. There is a comment saying so where someone would add it.
- **Shrink applies to the WEIGHT, and the basis must be an unshrunk quote.**
  USDA publishes negotiated live prices "based on net weights FOB the feedyard
  after a 3-4% shrink" — the headline $/cwt is not discounted, the weight is. A
  user who derives basis from their own closeout has shrink inside it already
  and should set the shrink field to 0.
- **Both freight fields default to zero.** Feeders are often quoted delivered
  and fats often sold FOB the yard, so a non-zero default would silently
  double-charge. There is no typical value worth guessing.
- **Cost of gain is NOT reduced by shrink.** Those are real pounds, really fed.
  Shrink is a term of sale.
- **Backgrounding cost of gain defaults to $110, not something cheaper.** Iowa
  State's 2026 budgets put backgrounding at $109-111/cwt against $107-111 for
  finishing — it is not the cheaper gain it looks like, because every per-day
  cost spreads over half as many pounds.

## Tabs, and the hidden-tab rule

The index, fed crush and backgrounding pages use `st.tabs`. A hidden Streamlit
tab is hidden, not skipped: its widgets still execute every rerun, so a value
computed in one tab is available in another. What decides correctness is SCRIPT
order, not tab order — the fed crush's cost-of-gain build-up must still be
written after the widgets it divides by, even though it displays elsewhere.

## The index page's headline date

`apps/cme_feeder_cattle/app.py` does NOT headline the newest row. It leads with
the index date CME will print next — the first business day after CME's last
published file — because the newest row is always the least complete, and on a
Monday it can hold one Saturday auction and nothing else. The rule lives in
`index_dates.py` with tests in the other repo. Do not "simplify" it back to
`MAX(report_date)`.

One consequence worth knowing: the headline follows CME's publication clock, so
if the CME feed breaks the headline freezes while the rest of the page keeps
moving. That happened 2026-09-14 through 09-17. If the headline stops advancing
while the Daily line does not, suspect the CME ingest, not this page.

## The COF Recap tab

The client one-pager, added 2026-09-22. It does not read QuickStats like the
rest of that page — `cof_recap.py` parses USDA's released report text at
`nass.usda.gov/.../cofd{MM}{YY}.txt`, which needs no API key and is the only
source that carries the placement weight-class breakdown, USDA's own rounded
state percentages, and the year-ago basis as USDA restated it, in one fetch.
The Year-Ago column is those same three ratios recomputed from last year's file
for the same month.

Two things in it look wrong and are not:

- **The US percentages round to the nearest tenth and will not match the old
  Excel sheet.** For September 2026 the sheet read On-Feed 100.8 and 99 against
  a computed 100.7 and 98.9 (11,163/11,080 and 11,080/11,198). Placed and
  Marketed agree to the decimal, so only those two cells ever differed, and the
  computed figure is the one to show — confirmed 2026-09-22. The state block is
  separate: it is USDA's published whole-number column, read as-is.
- **The marketing windows are a fixed per-class offset from the placement
  month**, not USDA data — Under 600# is +10/+11 months out through 1,000+# at
  +4/+5, with a deliberate two-month step between the first two classes. Those
  offsets were derived from one example sheet, so a wrong window is a wrong
  offset in `WEIGHT_CLASSES`, not a parsing bug.

The tab sits behind the page's `st.stop()` guard, so a QuickStats outage takes
it down even though it needs no API key. Known, not yet changed.

## The daily letter generator (`letter/`)

`python -m letter.build [--session am|pm] [--day monday..friday]`, or the
**JSA Daily Cattle Reports** page. Two reports a day, five weekdays; AM is one
format all week, PM switches to the week-in-review on Friday. Read the module
docstrings before changing a source — every one records the way that feed
fails *quietly*, which is the only failure mode that matters here.

Validated against the letters actually sent on 9/15, 9/18 and 9/22: every
automated figure reproduces exactly.

**All three formats now open on headlines.** The standard PM letter gained a
Headlines section on 2026-09-23, ahead of Market Action, the way Friday leads
with Key Headlines and the morning brief leads with Headlines. It shares the
`headlines` key with the AM brief deliberately — same meaning, separate draft
files. Friday stays either/or: Key Headlines replaced Market Action there and
did not join it.

The candidate panel is derived from the format's own section list, not from
`kind`, so adding a headline section to a fourth format needs no change in
`apps/weekly_reports/app.py`. Its sources are the AMS and border narratives,
Beef Magazine, two Google News searches for the packers and for plant
disruption, one more scoped to Reuters/Politico/WSJ/NYT, and — when the mailbox
is connected — four paid digests. Nothing auto-inserts, on any format.

The AM brief has **no intro line**: `config.INTRO_AM` is empty because the
masthead already says "JSA AM Daily Cattle Report 9/24/26". The evening intros
stay — they name the period the letter covers, which a masthead does not.

### Numbers that are right in a way that looks wrong

Three places where the obvious simplification is the bug that was just fixed.

- **The AM report reads the last COMPLETED session, not the newest bar.**
  `sources.fetch_futures(completed_only=True)`, passed by `gather()` for
  `kind == "am"` only. The history's row for today exists from the moment the
  session opens, so a brief rebuilt at 09:00 was taking a live price as a
  settle and dating it today — `am_cattle_rows` promises yesterday's settle and
  its move and was getting neither. Invisible for as long as the brief went out
  at 07:30, when there is no bar for today and both readings agree. The evening
  letter is written after the close and genuinely does want today's, so the two
  formats differ on purpose. Do not unify them.
- **Outside-market changes come from the settlement history, not the snapshot.**
  Massive's `session.previous_settlement` was a whole session stale for crude on
  2026-09-24: it reported 90.52 (Tuesday 09-22) when Wednesday settled 92.16, so
  the brief printed Nov Crude +3.26 against a real +1.41. Corn and the S&P
  agreed with the history that same morning, which is exactly why one instrument
  in three was wrong with nothing on screen. `_prior_settle` takes the last
  settle **strictly before** today — strictly, because the newest bar is today's
  own in-progress session — and marks it rather than bridging a gap older than
  `MAX_PRIOR_SETTLE_AGE_DAYS`. The snapshot's figure is still recorded so a
  disagreement is visible after the fact.
- **Two headline filters, and collapsing them re-breaks the panel.**
  `_RELEVANT` is for ag feeds; `_NEWSROOM` is for Reuters/Politico/WSJ/NYT,
  where "squash **beef** after Cold War video" and "China's clean tech
  **exports**" both pass the looser one. A test pins the difference.

### The `[[?]]` on the deployed app is not a bug

The hand-entered prior-Friday settles live in `out/weekbase_<friday>.json`, and
`out/` is gitignored **and** wiped by every Streamlit Cloud reboot. So the
deployed authoring page shows "No prior-Friday settle for 6 contract(s)" and
`[[?]]` in the futures block, always, and retyping them there lasts until the
next reboot. On Ross's desktop the file is present and the block renders
normally (`Oct: +4.60 at 220.525`). Same for `letter/data/settle_log.json`.

This is only cosmetic because **the letter is built locally** — confirmed
2026-09-24. If that ever stops being true, this becomes real and the fix is a
tracked path, not a bigger warning.

### Published letters are archived, and only when you say so

`JSA-Dashboards/jsa-letter-archive` — **private**, cloned as a sibling of this
checkout, written by `letter/archive.py`. Separate repo because this one is
public and those are the letters clients pay for.

    python -m letter.build --no-fetch --archive     # or "Archive as sent" on the page

Never automatic: "published" means Ross emailed it, which no code can detect.
Local-only — the deployed app has no clone and no push credentials and says so.
Re-publishing a corrected letter overwrites the file and commits, so git history
holds every version; nothing invents `-v2` names.

**It starts at 2026-09-24 and earlier letters are not recoverable from disk.**
Nothing kept them before that. The 9/15 and 9/22 renders are gone, and the 9/18
file in `out/` was rebuilt on 9/23 — five days after it was sent — so it is not
the published artifact either. Re-rendering is not archiving: rebuild the 9/23
brief today and you get different futures, a settlement-date line that did not
exist that morning, and no intro paragraph. Only Sent Items has the real ones.

### In flight as of 2026-09-24

- **Massive's futures history has no bars for 2026-09-14..09-18.** Not a fetch
  bug — the week is absent upstream. It leaves the PM moving averages marked
  `[[?]]`, because an average over a gapped series is wrong rather than
  approximate. `letter/settle_log.py` now records the front-month settles on
  every build, so the weekly change stops depending on their history once a
  letter has been built on a Friday. Delete `letter/data/` and that restarts.
- **Azure admin consent is pending** for the app registration "JSA Letter -
  email read" (delegated `Mail.Read`). Until it is granted, the headline
  candidate panel runs without the four subscription digests, which show one
  line saying the mailbox is not connected. It now also blocks the one thing
  that would back-fill the letters published before 2026-09-24 — Sent Items is
  the only record of those. No code change is needed when it lands.
- **The Sterling Profit Tracker carries the packer margin** the evening letter
  quotes by hand ("Sterling packer margins ... +138.80/hd versus +177.16/hd week
  before"). It arrives from `jnalivka@fmtc.com` and is already fetched for
  headlines — worth parsing as a FIGURE once a real one can be seen.

### Two things not to undo

- **The morning brief is one page and under three minutes.** That budget is the
  product. `render.build_html` returns early for AM rather than opting out
  section by section, so a section added to the evening letter cannot leak into
  the morning one; keep it that way.
- **Nothing fetched writes itself into a letter.** Headlines are a pick list on
  the authoring page; `render.py` has no import path to the fetchers and a test
  asserts it. Every other figure is a USDA or CME number that is either right or
  marked `[[?]]` — a headline has no `[[?]]`, so it gets a human instead.
