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

Six bundled modules read Snowflake and each defaults `SNOWFLAKE_SCHEMA` to
the schema **it** owns:

| module | its default |
|---|---|
| `apps/beef_weight/nass_cache_client.py` | `NASS_CACHE` |
| `apps/livestock_inventory/nass_cache_client.py` | `NASS_CACHE` |
| `apps/cme_feeder_cattle/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/us_cow_herd/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/mexican_feeder_imports/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/beef_trimmings/app.py` (`_sf_connect`) | `BEEF_TRIMMINGS` |

Added 2026-10-04: `marsapi.ams.usda.gov` rejects requests from Streamlit
Community Cloud's IPs, so the import side of Beef Trimmings (South America /
Australia-NZ Frozen 90s) moved to a droplet cron job writing
`JSA.BEEF_TRIMMINGS.IMPORT_COW90`, read via a dedicated `LIVESTOCK_PORTAL_SVC`
grant on that schema (same identity already used for `NASS_CACHE` +
`CME_FEEDER_CATTLE`). US Fresh 90s still calls `mpr.datamart.ams.usda.gov`
live — that domain isn't blocked, only `marsapi.ams.usda.gov` is.

Setting it to any one value overrides all six and silently breaks the others.
Pages load, queries miss, charts come back empty, nothing raises. **Unset is the
only working configuration.** `SNOWFLAKE_DATABASE = "JSA"` is safe to set.

## Pushing DOES deploy — but reboot anyway

**This section said the opposite until 2026-09-28, and it was wrong.** It read
"Pushing to GitHub does not deploy", explaining that the app was registered
under the old owner path so the webhook fired, returned `200 OK` and did
nothing. A note added 09-24 said the stated cause was in doubt. It is now
settled, in the other direction.

Four separate pushes on 2026-09-28 each auto-deployed within about two minutes,
with no reboot involved. The Manage app log for every one of them:

    [16:15:06] Pulling code changes from Github...
    [16:15:08] Processing dependencies...
    [16:15:09] Updated app!

against pushes at 14:40, 15:05, 15:23 and 16:13 UTC. The webhook works.
Two more that evening behaved identically — `bf4f92c` at 22:02 and
`71f7e96` at 22:06, neither rebooted, both live within minutes.

**Reboot after pushing regardless, and the reason is concrete rather than
superstitious.** Auto-deploy lands the code by HOT RELOAD, and hot reload is
what produces the `KeyError: 'letter.archive'` documented below — Streamlit's
watcher evicting a module from `sys.modules` while another session's thread is
mid-import. The first of those four auto-deploys threw exactly that, at
14:48:27. A reboot restarts the process and cannot hit it. Rebooting also
gives a clean cache and a fresh `letter/data/`, which is when `settle_log.sync()`
pulls the banked settles back down.

To ship: push, then **Manage app → ⋮ → Reboot app** on the live URL. Allow 2–5
minutes; the "not found" page partway through provisioning is normal. The app
is in the `jsa-dashboards` workspace — see Deployment facts, which was wrong
about this until 2026-09-24.

A reboot does a full fresh clone, so it always takes current `master` — the
startup log says `Cloning repository... Pulling code changes from Github`.

**CLAUDE CAN DO THE REBOOT** as of 2026-09-28, through the Claude in Chrome
extension driving Ross's signed-in Streamlit session. **"Delete app" sits
directly below "Reboot app" in that menu** — click by element reference, never
by coordinate. The confirm dialog says "This will disrupt all current users".
Ask before rebooting: Ross writes the letter on that app.

### Checking whether a reboot landed

**The log timestamp froze once and nearly cost a healthy app.** In a browser
session left open across several reboots the panel serves a cached view: on
2026-09-24 it read `[14:20:35]` through five further reboots that had all
succeeded, and reloading the app URL did not refresh it. That nearly produced
a delete-and-redeploy.

Refined 2026-09-28: the log advanced correctly all day — 14:48, 15:07, 15:25,
15:33, 16:15, 16:20, 17:0x — across four auto-deploys and four reboots, every
reading taken in a **freshly opened tab**. So the freeze is a stale *browser
session*, not a stale server. Open a new tab and the log is current and
trustworthy, which makes it genuinely useful for watching `Cloning
repository... / Cloned repository! / Processed dependencies!` go by.

The check that cannot lie either way is still to **look for a feature that only
exists in the new code** — a caption, a label, a figure you just changed. The
page cannot fake that.

A worked example, 2026-09-28: the US Cow Herd benchmark tile had to move from
38.3% to 42.9% (see the `feeder_receipts` section below for why). Reading 42.9%
on the live page settled it in one glance, with no reliance on the log at all.
**Prefer a figure you can predict exactly beforehand** — it beats a caption,
because a wrong value is as informative as a missing one.

### A bare `KeyError: '<module>'` in the app log is not a bug — diagnosed

Seen twice, on different modules and different pages, always with the same
shape: an `import` line, three frozen frames (`_find_and_load` →
`_find_and_load_unlocked` → `_load_unlocked`), a bare `KeyError` naming a
module, and **nothing of ours in the trace**.

    2026-09-28 14:48:27  KeyError: 'letter.archive'
                         letter/build.py:38, `from . import (archive, chart, ...)`
    2026-09-29 13:55     KeyError: 'snowflake_db'
                         apps/us_cow_herd/app.py:33, `import snowflake_db as db`

**It is transient and self-healing; do not go looking for a circular import.**
It was chased once already. Both fired during an auto-deploy, not a reboot.

The mechanism, reproduced 40 times out of 40 locally:

- `streamlit/watcher/local_sources_watcher.py` → `flush_pending_evictions()`
  calls `sys.modules.pop(name, None)` for every watched module whose file
  changed, **plus everything under its prefix** — so a touched `letter`
  evicts `letter.archive`, `letter.build` and the rest.
- Its docstring says it runs "at the start of each script run on the script
  thread so that `sys.modules` is not mutated from the file watcher thread
  while user code is executing". That holds for ONE script thread. Every
  browser session gets its own ScriptRunner thread, so session A's flush can
  pop a module while session B's thread is still executing its import.
- CPython's `_load_unlocked` ends with `module = sys.modules.pop(spec.name)`.
  If the entry has vanished mid-execution, that line raises `KeyError` naming
  the module. Hence the bare KeyError with no application frame.

**THE MODULE NAMED IS INCIDENTAL — it is simply whichever import was in flight
when the eviction landed.** `archive` is the FIRST name in `build.py`'s import
tuple; `snowflake_db` is the first import in the US Cow Herd page. Neither has
anything wrong with it. That was predicted after the first sighting and the
second one confirmed it, which is the main reason to record both: a future
reader seeing a third module name should recognise the shape and stop, not
start again on whatever that module happens to be.

Ruled out, and worth not re-deriving: the `letter` package's import graph is a
clean DAG (`sources → settle_log → draft_store`, `render → chart → config`,
`technicals → sources`); `archive.py` imports only stdlib; nothing in the repo
deletes from `sys.modules` or calls `importlib.reload`; and 480 concurrent
first-imports of `letter.build` across 8 threads raise nothing.

**It is an argument for the reboot habit above.** A reboot restarts the process
and never goes down the hot-reload path, so it cannot hit this. The race needs
a code change to land while a session is mid-rerun — which is exactly what an
auto-deploy is, and both sightings were during one.

**One interaction to keep in mind, currently harmless.** `snowflake_db` is the
module that exists FIVE times and is imported by bare name, so whichever page
loads first wins (see "Apps sharing code do not share secrets"). Eviction plus
bare-name import means a re-import could in principle bind a DIFFERENT copy
than the process started with. All five are byte-identical today, which is the
only reason that is a curiosity rather than a bug — and one more reason to keep
them that way.

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

`daily_slaughter.py` and `tests/test_daily_slaughter.py` exist **twice** — here
and at the root of `beef-weight-dashboard` — and nowhere in
cme-feeder-cattle-index. Both are byte-identical and listed in that repo's
`test_no_drift.py` SHARED list, which now walks beef-weight-dashboard too.
**The standalone needs `MARS_API_KEY` added to its own Streamlit secrets**: the
portal already held it for the report 3658 tiles, but that repo had no MARS
consumer at all before the Saturday view, so there was nothing to inherit.
Without it the Saturday view shows one error naming the secret and the rest of
that dashboard is unaffected.

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

## `feeder_receipts` is all three channels now

`JSA.CME_FEEDER_CATTLE.FEEDER_RECEIPTS` carries `auction`, `direct` and
`video`, and `herd.py` reads **all three** as of 2026-09-29. It was auction-only
until then, because USDA had retired the legacy archives that carried direct and
video and those channels stopped in 2020/21. They no longer do: MARS serves them
through a per-section endpoint the repo had not used —
`/reports/{slug}/Report Details`, where the bare `/reports/{slug}` returns
narrative rows and no head count at all. See `direct_reports.py`'s docstring.

**Why it was worth changing.** The auction-vs-all-channel gap is not a constant
offset: 4.57 points in 2015, 2.25 now, because direct's heifer share climbed
about twelve points over that span while auction's moved half a point. The
page's headline is the DISTANCE from the 2015 rebuild, so that drift lands on
it — auction alone says **+0.64**, all three say **+2.96**, and 2026 goes from
2nd-lowest of 21 years to 8th.

Three rules hold it together, all in `herd.py`:

- **One source per channel per week.** Legacy and MARS overlap on 26 auction
  weeks and 19 video weeks; direct's halves abut with none. `CHANNEL_LEGACY_THROUGH`
  says which archive owns a week. Summing them double-counts, and that was
  written wrong twice in one session with nothing raising either time.
- **All channels or the week is skipped.** They sit ~10 points apart, so two of
  three is a different mix, not a smaller sample.
- **2020 is dropped.** MARS direct starts at week 39, past the week-37 basis, so
  a 2020 point would be legacy-only and legacy is a decaying remnant by then.

The coverage guard (`MIN_PANEL_STATES`) still counts **auction** states only: it
exists for the auction archive's thin early years, which is a property of that
archive. `tests/test_heifer_share_channel.py` pins all of it.

## `@st.cache_data` does not notice that an imported module changed

It keys on the DECORATED function's own code and its arguments. The modules that
function calls are not part of the key. So a change confined to `herd.py`,
`on_feed.py` or any other analytics module leaves the cached value in place, the
auto-deploy hot-reloads the code, and the page keeps serving the old numbers
with no error and no stale marker.

Seen twice on 2026-09-29, both times looking like a data problem rather than a
cache one: the second time `herd.py` had been changed to admit 2002-2004 into
the caveated segment, Snowflake held all five years, a local run returned all
five — and the deployed chart still drew two. The caption, which lives in
`app.py` and is not cached, updated in the same deploy and told the reader about
weeks the chart was not showing. That split is the tell: **text changes, numbers
don't.**

**A change to a module the page imports needs a reboot, not just a push.** A
reboot restarts the process, so the cache starts empty. The push alone is enough
only when the edit is inside the cached function itself, or in uncached page code.

### ...and the last sentence of that is not reliable either -- 2026-09-30

**The same symptom occurred on a path with NO CACHE ANYWHERE, so do not reach
for `cache_data` to explain every stale reading.**

The USDA report calendar was changed to convert ESMIS's tz-aware Eastern stamp
to Central (`sources.fetch_report_calendar`, commit `7920931`). After the push
the deployed page went on printing `Grain Stocks: Wed 9/30, 12:00pm` -- the
Eastern hour -- **across repeated presses of "Fetch latest data"**. A reboot
fixed it; the page then read `11:00am CT`.

There was nothing for a cache to hold onto:

- `grep -rn "cache_data\|cache_resource\|lru_cache" letter/` returns exactly
  one hit, `render._asset_uri` (the logo data URI). The calendar is not cached.
- The Fetch button calls `letter_build.gather()` directly and rewrites
  `out/data_<slug>_<date>.json`. There is no memoised layer between the click
  and the HTTP request.
- Run locally against the live feed at the same time, the pushed code returned
  `Wed 9/30, 11:00am CT`. The code was right; the deployment was not running it.

**The mechanism was never established, and guessing at one is how this entry
would go wrong.** It was first written up as "the running process's imported
`letter.sources` was stale", which is a hypothesis and was stated as a finding.
Streamlit's watcher does evict changed modules from `sys.modules` (see the
`KeyError` section above, which depends on it doing exactly that), so "the
module was simply never re-imported" is not free -- it needs evidence nobody
collected. A plain race between the click and the auto-deploy completing fits
the observations just as well.

What is actually load-bearing, and all that should be relied on:

- **The reboot habit is right, and the cache is only one of its reasons.**
  Treat "pushed, but the page disagrees with a local run" as a reboot, not as a
  diagnosis.
- **A local run against the live source is the cheap discriminator.** It
  separates "the code is wrong" from "the deployment is not running the code"
  in one command, before any theory. Here it took under a minute and pointed
  straight at the deployment.

## The video "seam" was not one, and the mistake is worth keeping

For most of 2026-09-29 this file, `herd.py` and several answers to Ross cited a
**+1.62-point video seam** at the 2020/21 archive handover as the weakest join in
the receipts series. It does not exist. Investigated with four independent
probes and adversarial verification; every one came back at zero points
explained by any artefact.

**The error was mine and it was simple.** I measured legacy **2019** against MARS
**2021** — two years apart, with 2020 skipped between them — and called the
difference a join. The adjacent-year join is legacy 2019 36.40% against MARS
2020 36.27%: **−0.13 pt**. The +1.62 is two years of market movement.

Four things establish it, and they are worth not re-deriving:

- **Norwood NC is a paired-week calibration.** Legacy video decays through 2020
  (1.58M head in 2019, 218k in 2020), so the overlap looked like a dying
  remnant — but Norwood kept reporting normally. On the 12 weeks both archives
  carry it: legacy 17,953 head / 39.26%, MARS 17,857 / 39.48%. **+0.22 pt, head
  ratio 0.9947, eight weeks identical to the head.** They are transcriptions of
  the same AMS report. Recorded in `feeder_sex_mix.py` and pinned by a test.
- **The move is within-location, not mix.** Decomposing 2019→2021: +1.62
  within-location, −0.10 roster. Nine of eleven comparable auctions rose, and
  the five carrying 92% of head rose together (Superior +1.61, Western +1.84,
  Cattle Country +1.57, Joplin +2.78, Norwood +2.06). Coverage artefacts move a
  few locations, not every large one by the same amount.
- **Within MARS alone it keeps climbing**: 2020 36.27% → 2021 37.19% → 2022
  37.91%, about +0.9/yr, no archive change involved.
- **Every quantifiable artefact runs the other way**, hiding ~0.6 pt of real
  movement: unmatched locations −0.07, legacy 2019's Northern hole −0.31 to
  −0.41, week-mix −0.21.

**The control channels were never controls**, which is why this looked anomalous
for so long. Direct's tidy −0.12 over the same span is two large offsetting
moves (44.09 → 38.75 → 43.97), not stability. And auction holds both sources in
the same year: 2019 legacy 46.28% vs MARS 45.84%, a −0.44 pt cross-source
difference.

Two real defects surfaced on the way, neither closing any gap:

- **Legacy 2019 video is not a clean benchmark year.** Northern Livestock appears
  for one week, 60,688 head, against 144,670–236,818 over 5–8 sales in 2013–18.
  The year is short ~145k head (~9%), and Northern runs below the video mean, so
  the hole *inflates* the 2019 share by 0.3–0.4 pt. Do not benchmark against it.
- **`CHANNEL_LEGACY_THROUGH["video"]` was 18 and is now 19.** In week 2020W19
  legacy carries 28,687 head and MARS 1,967 — MARS is starting up, not legacy
  finishing — so the old boundary discarded 26,720 head. No published figure
  moved (2020 is in `SKIP_YEARS`), which is precisely why it needed a test.

## TWO BACKENDS, AND "IT WORKS LOCALLY" PROVES NOTHING

`snowflake_db.get_conn()` returns SQLite or Snowflake depending on
`USE_SNOWFLAKE`. **The deployed page reads Snowflake. A local ingest writes
SQLite.** Verifying the one you just wrote tells you nothing about the one the
page uses.

This shipped a live error on 2026-09-29: the MARS direct/video rows were loaded
locally, `herd.py` was switched to all-channel and pushed, and because Snowflake
had no direct/video after 2020 every later week was missing a channel and got
skipped. The deployed chart **terminated in 2019 and labelled it "today"**, with
a plausible-looking 43.5% and a 5.17-point distance. Nothing raised; the page
rendered perfectly.

- The canonical sync is `python snowflake/02_migrate_data.py --tables feeder_receipts`
  (`feeder_receipts` is in `OPTIONAL_TABLES`), which the nightly job already runs
  as `--optional-only`.
- `scripts/check_run.py` sets `USE_SNOWFLAKE=1` with the comment "check what the
  dashboard sees". That is the habit. Use it before believing a local verify.

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

### The letter and the dashboard must agree on the FCI, and twice they did not

Both read the same two tables and both are "right in isolation", which is why
each disagreement went unnoticed until Ross put the two side by side.

- **2026-09-29, rounding.** The brief printed `-0.17 at 337.63` where the
  dashboard showed the same 337.63 down 0.16. The raw move was -0.169151; the
  letter rounded the DIFFERENCE, the dashboard rounds the VALUES first. The
  dashboard's convention won, and it is the better one: the letter prints
  337.63 today and printed 337.79 yesterday, so a reader holding both
  subtracts them and must get 0.16.
- **2026-10-01, source precedence.** The brief printed `+0.37 at 339.05`
  where the dashboard showed `+1.02`. `fci_daily` is JSA's MARS
  reconstruction; `cme_ftp_daily` is CME's published file. **CME's value wins
  for any date it covers** — the reconstruction's job is the trailing day or
  two CME has not printed yet, and `load_data()` in the dashboard says so in
  its priority order. `fetch_feeder_index` read `cme_ftp_daily` for its DATE
  and threw the value away, so our superseded 338.68 estimate for 09-29 stayed
  in the subtraction against CME's published 338.03.

The headline date itself is by definition the first business day AFTER CME's
last file, so its value is always ours. It is the PRIOR date that CME has
usually printed by the time the letter goes out, and that is the one to take
from them. `tests/test_feeder_index.py` pins it with the real 09-29/09-30
numbers and runs the REAL `index_dates` rule rather than a fake.

The general lesson, since it has now cost two mornings: **when the letter and
a dashboard quote the same figure, a disagreement is a bug even when both
numbers are defensible.** Neither will raise.

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

## The Cold Storage view

Added 2026-09-25. The Cattle on Feed page carries a **second USDA report**
behind an `st.segmented_control` at the top — `Cattle on Feed | Cold Storage` —
in the same spirit as the Beef Trimmings page's view switch. Fetching and the
MoM/YoY arithmetic are in `apps/cattle_on_feed/cold_storage.py`; the layout is
in `app.py` next to the brand helpers it needs, the same split as `cof_recap`.

**A switch, not a thirteenth tab.** A hidden Streamlit tab is hidden, not
skipped, so as a tab Cold Storage would run its fetches on every Cattle on Feed
load and vice versa. It also sits **above** the page's `st.stop()` guard, which
is the other half of the point: an outage on the six Cattle on Feed series no
longer takes Cold Storage down with it.

**It reads QuickStats, not the monthly PDF, and it goes back to 1917.** The
release at `esmis.nal.usda.gov/.../cost{MM}{YY}.pdf` is one month with two
comparison columns. QuickStats carries the same series from **1917** for beef,
pork, lamb, turkey and cheese (1915 for butter, 1972 for the boneless/bone-in
beef split), which is the only reason a real history exists here. No new
secret — it is the `NASS_API_KEY` this page already requires.

Four things that look wrong and are not:

- **`freq_desc` is `POINT IN TIME`, not `MONTHLY`, and the period reads
  `END OF AUG`.** Filtering on MONTHLY returns nothing, as a 400 that says
  "bad request - invalid query" and means "no rows".
- **USDA restates the prior month and QuickStats carries the restatement, so a
  figure already on this page can move.** Total beef for 31 Jul 2026 was
  published at 382,714 thousand lb in the August report and restated to
  398,285 in the September one — +4.1%, essentially all of it in boneless.
  That one revision moves July's YoY from -3.8% to +0.1%, across zero. A page
  built on one archived PDF would go on showing a number USDA has withdrawn.
- **The streak panel counts months above YEAR-AGO, never month-over-month.**
  Beef stocks fill from September into December and draw down through summer
  every year, so an MoM rise in October is the calendar, not the market.
- **`Total red meat (computed)` is computed and labelled so.** QuickStats has no
  aggregate; it is beef + pork + veal + lamb & mutton, which is an identity —
  for 31 Aug 2026 those four sum to 862,128 against USDA's printed 862,128,
  and the report has no fifth bucket. It starts 1944 (veal) rather than 1917.
  `combine()` inner-joins deliberately: zero-filling veal's missing years would
  print a "total" that is really beef+pork+lamb with a step change in 1944.

The series has six missing months in 110 years, so `monthly_frame` reindexes
onto a full monthly grid and blanks any change whose base month is absent. A
plain `pct_change` bridges those gaps and prints a 13-month move as a "MoM".
`tests/test_cold_storage.py` pins that, the run-splitting, and the red-meat
identity.

## The Monday Print Forecast tab

Added 2026-10-02: a third tab on the Cash Cattle Trade page, beside the weekly
and daily views. It turns a part-finished trading week into the two figures
USDA publishes the following Monday — the 5-Area weekly negotiated head
(LM_CT150) and the national confirmed count (LM_CT154). The two steps are kept
visibly separate on the page on purpose: they fail differently, and a reader
needs to know which half is shaky.

**Step 1 is close to arithmetic, and that is not a figure of speech.** The four
daily regions' Friday-FINAL week-to-date, summed with nulls as zero, **IS** the
5-Area weekly negotiated head USDA prints — verified on all 55 weeks the daily
history covers, zero mismatches, including the weeks where two of the four
regions published nothing at all. So the only unknown in Monday's 5-Area print
is trade reported after USDA's last published cut. If that identity ever
drifts, the tab is estimating a different number from the one USDA prints and
everything downstream of it is wrong. `tests/test_cash_forecast.py` pins it
against real published figures rather than a fixture anyone could edit to
agree.

**Step 2 is the weak half** and the page says so. The gap between the 5-Area
and national counts is negotiated trade in states with no daily report at all,
and it is the part with no observable running total.

### Four things in it that look wrong and are not

- **It asks for a FULL YEAR of daily history outright, with no window
  control.** That looks like it ignores the hidden-tab rule, and it does not:
  the cost of a `/Summary` request is flat in the window length — 4.8 s for 30
  days against 5.6 s for 365, measured 2026-10-02. It is `fetch_daily_cash`'s
  `/Detail` section that is expensive (11 MB for one region-year), and that is
  what `DAILY_WINDOW_DEFAULT`'s 1M is protecting against. **Do not shrink this
  to match the Daily tab**: a year buys ~50 calibration weeks for under a
  second, a month buys four.
- **The 5-Area-to-national gap is added, not scaled, over only FOUR weeks.**
  Backtested on 175 weekly pairs since 2023, every window from 4 to 26 weeks
  and all three methods (additive, ratio, OLS) land inside 2.4–3.4% median
  absolute error — so the choice looks arbitrary until the relationship steps,
  when it is the only thing that matters. Since Kansas and TX/OK/NM stopped
  publishing daily volumes the gap roughly doubled, and the bias is −3.5% at
  four weeks against −16.0% at thirteen. The short window is the one that
  notices.
- **Analogues are picked on FRONT-LOADING, not week maturity.** Narrowing on
  maturity — week-to-date against a typical recent week — is the obvious
  alternative and is worse: 12.2% median absolute error against 7.8% over the
  same 52 weeks, band coverage 65% → 50%. Tried and rejected 2026-10-02; the
  comment in `forecast_5area` says so. A low maturity says the week is quiet
  but not whether it has *finished* being quiet, and those are different
  questions.
- **The tab grades its own reliability** instead of printing one number with
  one error bar. Split into quartiles by how much had already traded, the
  busiest quarter of weeks land within a median 3% with 92% band coverage and
  the quietest are a median 36% out with 38% — same method, same band. Maturity
  earns its keep here, where it beats front-loading outright, which is why it
  is computed but never used to select.

### The suppression interaction is what moves it most

When USDA withholds a region's daily volume for confidentiality it publishes
the report skeleton with every volume null, grid rows included. That region
then drops out of the 5-Area figure — USDA's own published total included,
which is why the identity above still holds — but **stays in the national
count**, so the gap widens and Step 2 is the half that suffers.

TX/OK/NM has been withheld since the week of 2026-06-22 and Kansas since
2026-08-10. Measured over that break, the gap went from a median 11,567 head/wk
to 23,172 — about 11,600 head/wk of real trade that is in the national number
and absent from the 5-Area. A region sitting at zero across a whole week on the
Daily tab's week-to-date tiles is the signal.

### The prediction on the record

The tab's first live run, for the week of 9/28–10/2 and standing at Friday's
1:30 pm cut, called **5-Area 61,167** (range 59,428–68,363) and **national
81,723** (range 74,476–94,063). USDA settles both on Monday 2026-10-05.

Worth recording the outcome here when it lands, because the two halves fail
independently: a 5-Area miss means the identity or the late-trade estimate is
wrong and deserves real investigation, while a national-only miss is the gap
model — which rests on six post-blackout weeks and is the half expected to need
work first.


## The Saturday Slaughter view

Added 2026-10-02 as the **fifth tab**, between AMS Weekly Slaughter and Beef
Production. Fetching and the week arithmetic are in
`apps/beef_weight/daily_slaughter.py`; the layout is in `app.py` next to the
brand helpers it needs.

**It shipped that morning as a top-level `st.segmented_control`, the Cold
Storage shape, and was moved to a tab the same day** — it is a secondary view
of slaughter, not a peer of the whole dashboard, and the switch gave it more
billing than it earns.

**Nothing else on the portal can answer a day-of-week question.** The NASS tab
and the SJ_LS712 feed behind the AMS tab are both WEEKLY (week-ending
Saturday) totals, so a Saturday kill is not a slice of them — it is a
different report, AMS **3208**, *Daily Livestock and Poultry Slaughter*. No new
secret: it reuses the `MARS_API_KEY` the carcass-weight tiles already hold.

**The switch existed for two reasons. One was accepted, the other was kept —
and the way it was kept is the thing not to delete.**

- *A hidden tab is hidden, not skipped*, so the MARS fetch now runs on every
  Cattle Weights load. Accepted: `_sat_load` is `@st.cache_data(ttl=3600)`, so
  that is one request per hour per container, the same deal `_fetch_fis_weights`
  already takes.
- *A NASS outage must not take it down*, because it reads neither NASS nor the
  cache. As a tab it sits BELOW the page's `st.stop()` guard and would have
  died with it. So `if raw.empty:` now renders the Saturday tab on its own
  **before** calling `st.stop()`. **That four-line block is not redundant** —
  delete it and an unrelated Snowflake hiccup blanks a view that never needed
  Snowflake. Verified locally with no credentials at all: NASS errors, the page
  stops, and the Saturday tab still draws in full.

**Its controls live in the tab body, not the sidebar**, for the first reason
above: a hidden tab still executes, so `st.sidebar.multiselect` there would
park a "Years" box in the weights sidebar on every tab. Same trap as the
hidden-tab rule further up this file.

**3208 is a SECTIONED slug**, the trap `direct_reports.py` documents for the
direct/video slugs. `GET /reports/3208` answers HTTP 200 with narrative rows
and **no head counts**, which reads exactly like a report that has stopped
publishing. The data is one path segment away at
`/reports/3208/Report Livestock Commodity` (and
`/Report Livestock Class` for Steers/Heifers vs Cows/Bulls). The section is a
path segment, not a query param.

Four things that look wrong and are not:

- **History starts 2024-01-01 and that is all MARS keeps.** One unfiltered
  call returns the whole series. Any question about 2023 or earlier is
  unanswerable here, so `FIRST_YEAR` is printed on the page rather than left
  to be inferred from an axis.
- **One `slaughter_date` appears in several reports.** Friday carries Saturday
  as a PROJECTION and Monday restates it, so the dedupe takes the latest
  `report_date`. **Saturdays revise UP far more often than down** — 14 of the
  first 145 were revised, 2024-11-30 going 39,000 → 47,000 — so keeping the
  forecast leaves a series that looks entirely reasonable and reads low.
- **A Saturday without its week is close to meaningless.** Every Saturday at
  or above 38,000 head on file sat in a week that had lost a weekday to a
  holiday — New Year's, Memorial Day, July 4th, Labor Day, Thanksgiving. The
  2026-09-12 Saturday of 70,000, the largest on file, sat in a Labor Day week
  whose Monday killed 2,000, and that week still totalled only 505,000 against
  a 2026 median full week of 527,500 — the sixth day recovered most of the
  lost Monday, not all of it. So `saturday_frame` never returns a Saturday
  alone and the chart colours short weeks apart rather than hiding them.
- **`lost_day` is a RATIO, not a head count** (`LOST_DAY_FRAC`, half the
  week's own weekday median). A fixed threshold would stop working as the herd
  contracts and the whole level drifts down: a 2024 holiday Monday and a 2026
  one are both ~2,000 head against very different normal weeks.

`week_to_date` is the report's own running total and is the free audit — Mon–Sat
summed must equal it. `reconcile()` checks it and all 144 weeks on file
balance. A dedupe mistake does not raise and does not look wrong on a chart; it
looks like a slightly different market. `tests/test_daily_slaughter.py` pins
all of it.


## The daily letter generator (`letter/`)

`python -m letter.build [--session am|pm] [--day monday..friday] [--kind ...]
[--chart ...] [--archive]`, or the **JSA Daily Cattle Reports** page. Read the
module docstrings before changing a source — every one records the way that feed
fails *quietly*, which is the only failure mode that matters here.

Validated against the letters actually sent on 9/15, 9/18 and 9/22: every
automated figure reproduced exactly **as the letter stood on 2026-09-23**. The
evening letters were substantially reshaped on 09-24 (below), so that check no
longer describes what goes out on a Monday.

### The week, as of 2026-09-24

Two reports a day. One morning format all week; **three** evening formats.

| | Format id | Pages | Change quoted | Cash block |
|---|---|---|---|---|
| AM, every day | `am` | 1 | prior session | week-to-date by state, + cutout + slaughter |
| Monday PM | `tuesday` | 3 | prior session | last week's weighted average |
| Tue/Wed/Thu PM | `recap` | 2 | prior session | week-to-date by state |
| Friday PM | `friday` | 3 | **week over week** | week-to-date by state |

**THE FORMAT ID `tuesday` RUNS ONLY ON MONDAY.** The ids are historical layout
names, not days — they are what `render.py`, `commentary.py`, the tests and the
stored drafts switch on, and renaming one touches thirty-odd places for no
behaviour change. They never reach a filename or the page: drafts are named by
the DAY (`commentary_pm_monday_<date>.md`). Read `tuesday` as "the full letter".

Written sections, in render order:

- **AM** — Headlines
- **Monday** — Headlines, Market Action, Technicals LC, Technicals FC,
  Fundamental Rundown, Comments
- **Tue/Wed/Thu** — Headlines, Market Action, Technicals *(one block, both
  products)*, Comments
- **Friday** — Key Headlines, Technicals LC, Technicals FC, Cash Trade Recap,
  Cattle on Feed Commentary, Comments

`Comments` is the catch-all and sits last on every evening letter, above the
sign-off — **not** literally under the rundown, because the three formats end
differently and Friday's rundown is mid-letter. It is deliberately absent from
the morning brief.

The recap's single `technicals` key is NOT `technicals_lc`/`technicals_fc`. The
computed moving averages for both products print above it; the written read is
passed to **neither** sub-block, because handing the same bullets to both prints
it twice, once under each product.

### Only Friday quotes the week, and that was a decision

`config.CHANGE_BASIS_BY_KIND`. Monday through Thursday quote the prior session;
Friday quotes week over week.

**This departs from verified behaviour and is not a bug fix.** `config.py`
records that the 9/22 letter — a **Monday** — quoted week-over-week on all six
contracts, exact to the thousandth. Ross was shown that evidence and asked for
the change twice. Do not "restore" it.

It also retired a daily nuisance: `change_week` needs the prior **Friday's**
settle, which Massive has not had since 2026-09-14, so Mon–Thu printed `[[?]]`
whenever the hand-typed substitute was unavailable. `change_day` needs only the
previous bar — **but "only the previous bar" is not "always available"**, and a
Monday brief marked all six contracts on 2026-09-28. See the `[[?]]` section
below for the two conditions that mark it.

**The basis comes from the format, never the cache.** Every
`data_<slug>_<date>.json` written before 09-24 stores `"week"`; a `--no-fetch`
re-render would otherwise quote week-over-week on a Monday and mark it `[[?]]`.
Both `build.main` and the page re-derive it.

### The letter prints itself now

Letterhead, the 50-year watermark and a hairline sage frame are generated, not
pasted in afterwards — `assets/logo-full.png` and `assets/jsa-50-years.png`,
both embedded as data URIs so they survive the PDF being emailed.

**Two print paths, and they are not equivalent.** `Build PDF` drives headless
Edge on the host and only works locally. The **Print / Save as PDF** button
prints the preview iframe from the reader's own browser and works anywhere,
including the deployed app. A frame drawn with negative `position: fixed`
offsets renders in the first and is clipped in the second — that shipped once.
Verify layout on the path Ross actually uses.

### The preview must stay a WELL-FORMED document — 2026-09-30

The button was added as `_print_ui + html`. `render.build_html` returns a
complete page starting `<!DOCTYPE html>`, so putting anything in front of the
doctype means it is no longer first, the parser **discards it**, and the whole
letter renders in **quirks mode** — `document.compatMode == "BackCompat"`,
`document.doctype == null`, and the letter's `<meta>`, `<title>` and entire
stylesheet hoisted into `<body>`.

Not cosmetic. Diffing the PDF content streams, the first divergence is a
drawing operator — `388 519 297 1 re` against `388 513 297 1 re`, the same
rule **six points lower**. The two print paths documented above as producing
the identical letter were not, and the one that diverged is the one Ross uses.
The page count stayed at one, which is why it survived unnoticed.

The style now goes in `<head>` and the button just inside `<body>`
(`_with_print_button`), and the preview's content stream is byte-identical to
the bare letter's. `tests/test_print_preview.py` pins it.

**The first attempt at that fix failed silently**, in this repo's signature
way: `doc.find("<body")` matched render.py's own stylesheet comment — "put a
background on `<body>` and this disappears underneath it" — so the button went
**inside a CSS comment**, inert. The preview rendered perfectly and simply had
no print button. The search is anchored after `</head>` now, and a test feeds
in a letter whose CSS mentions `<body>`.

### Why the print dialog opens on Landscape — and what does NOT fix it

Ross's dialog came up **Layout: Landscape**, so the letter sat below the fold
of the preview pane and had to be scrolled to read.

**`@page { size: letter portrait }` DOES NOT FIX IT AND WAS REVERTED.** Blink
discards an orientation keyword that is redundant with an already-portrait
named size (`Size::ParseSingleValue`), so it parses to exactly
`size: letter`. Confirmed by reading the rule back through a live CSSOM, where
it serialises without the keyword, and by the PDF content stream being
byte-identical. The commit that added it changed nothing. Do not re-apply it;
a test now pins its absence.

The real mechanism: `GetPageSizeAndOrientationInfo` marks every page `kFixed`
when `@page` names a size, which sets `all_pages_have_custom_orientation`, and
the preview **removes** the Layout control rather than pre-selecting Portrait
— the ticket falls back to the setting's `unavailableValue`, which is
portrait. `size: letter` alone already does this. `size: auto` would hand the
control back.

**But it only holds for Chromium's own "Save as PDF" destination.** Choose a
system printer — **"Microsoft Print to PDF" is the trap**, it reads as the
same thing — and the Layout control returns, carrying the orientation that
reader last used. Chromium persists `layout` as a sticky setting per profile
(`printing.print_preview_sticky_settings`), and both of Ross's Edge profiles
held `"isLandscapeEnabled": true`. The page box stays portrait because the CSS
still wins, so a tall sheet sits in a pane sized for a wide one.

So the fix is in the dialog, not the letter: pick **Save as PDF** rather than
Microsoft Print to PDF, or set Layout to Portrait once and let it stick.
Nothing in the letter can do either for a client.

One hypothesis was investigated and **refuted**: that the button prints the
Streamlit page rather than the letter iframe. Chromium's scripted print prints
the frame that called `print()`, the button is injected inside the letter
document, and that document is the component iframe. Do not rebuild the letter
as a Blob in a new tab to "fix" this — it addresses a problem that does not
exist.

The **chart of the day** is AM only, bottom right, floated into the empty band
beside the signature so it costs no vertical space. Which market it shows is
picked from the letter's own text, then the day's candidate headlines, then the
biggest mover, then a rotation — deterministic per date, never random, because
the letter is built twice and the PDF must match the preview.

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

### The `[[?]]` on the deployed app — FIXED 2026-09-26/28

**Both halves of this are now in Snowflake and the section is kept for the
history rather than as a live warning.**

It read: the hand-entered prior-Friday settles live in
`out/weekbase_<friday>.json`, `out/` is gitignored and wiped by every Streamlit
Cloud reboot, so the deployed page showed "No prior-Friday settle for 6
contract(s)" and `[[?]]`, and retyping them lasted until the next reboot. The
same was true of `letter/data/settle_log.json` — gitignored beside the code,
which turned out to be no safer, because a reboot is a fresh clone and a
gitignored directory arrives empty.

The week base moved to `JSA.LETTER.DRAFTS` under `KIND = "weekbase"` on
2026-09-26, and the settle log on 2026-09-28 under `KIND = "settlelog"`. See
**Drafts survive a reboot now** above and `letter/settle_log.py`.

**IT DID NOT NARROW TO FRIDAY, AND THAT CLAIM WAS WRONG.** This section read
"had already narrowed from every evening letter to Friday only, because Mon–Thu
stopped quoting week-over-week on 2026-09-24 and `change_day` needs nothing but
the previous bar". The second half is false. `change_day` is not a number that
is always there — `sources.fetch_futures` yields None for it, which prints
`[[?]]`, on **either** of two conditions:

- the previous bar is more than `MAX_SETTLE_AGE_DAYS` (4) older than the settle,
  so the move would be measured across a hole; or
- the two ends are different KINDS of number — an hourly close against a
  settlement. Mixed basis is marked rather than computed, because Friday's last
  trade against Thursday's settle gives +3.25 where settle-to-settle is +3.175.

**Observed on the deployed app on Monday 2026-09-28**, which is what settles it:
the AM brief printed `[[?]]` on every cattle contract, under both warnings at
once — six contracts recovered from hourly close, and no daily change for six.
A Monday morning, on `change_day`, with the week base irrelevant.

So the `[[?]]` risk is not Friday's alone. It belongs to any letter whose two
settle dates are far apart or unlike in kind, which is a property of the feed on
the day, not of the weekday. The 09-24 basis change removed one *cause* of it
Mon–Thu; it did not make the mark impossible there.

A related imprecision worth knowing: `build.py` prints only the gap explanation
("The previous session is absent from the feed") for every marked contract,
including the ones marked for mixed basis instead. The message can therefore
name a cause that is not the one that fired.

One consequence of the history: the settles for **Friday 2026-09-25** were
recorded only on the deployed container, before the mirror existed, so they went
with it. The first build on any machine after that Friday re-records them from
Massive, since a Monday morning build's last completed session IS that Friday —
but if Friday 2026-10-02 asks for a week base and does not have one, that is
why, and it is the last time it can happen.

The underlying cause is upstream and unresolved: Massive has had no bar for
2026-09-14..09-18 since it happened. Once a Friday letter has been built on a
Friday with an intact prior Friday, this should stop arising at all.

### Drafts survive a reboot now — `JSA.LETTER.DRAFTS`

Added 2026-09-25, after a reboot destroyed a nearly finished Friday letter.
Until then a draft lived in exactly one place: `out/`, which is gitignored and
which every Streamlit Cloud reboot rebuilds from a fresh clone. **The page's
own docstring said so accurately and it was lost anyway** — a warning in a
docstring is not a backup, and that is the lesson worth keeping.

`letter/draft_store.py` writes every edit to `JSA.LETTER.DRAFTS` as well as to
the file. No new secret: the page already forwards the Snowflake block.

- **The table is APPEND-ONLY.** Every save INSERTs; the current draft is the
  newest row for its `(issue_date, kind)`. There is no UPDATE and no DELETE, so
  no save can bury an earlier version and the page's **Version history**
  expander can always hand one back. Durability alone would still have let a
  bad paste destroy an hour's writing.
- **It writes BOTH places, every time.** Snowflake survives the reboot; the
  file keeps `python -m letter.build` working when Snowflake is unreachable.
- **Newest wins on read, and that is not "the database is the source of
  truth".** Hand-editing the `.md` and re-running the build is a supported
  workflow that `commentary.py` promises, so `restore()` compares the file's
  mtime against `SAVED_AT` (UTC on both sides) rather than always preferring
  the row. A database-always-wins rule would silently eat those edits — the
  same class of quiet loss this exists to stop.
- **A Snowflake outage must never stop the letter.** Every call returns a
  status string instead of raising, and the page says loudly when autosave is
  failing rather than looking fine.
- **The schema is owned by SYSADMIN**, unlike `JSA.CME_FEEDER_CATTLE` whose
  tables ACCOUNTADMIN owns and on which SYSADMIN has no MODIFY. A table put
  there could never have a column added without an admin.
- **It never reads `SNOWFLAKE_SCHEMA`** — every statement names the table in
  full, so it takes no part in the five-module collision at the top of this
  file. A test pins that, and that it never imports `snowflake_db` by bare
  name; it loads that file under a private name the way `sources.py` does.

Two placement traps, both already paid for:

- **The Version history panel sits ABOVE the text areas**, because restoring
  writes `wcr_<section>` into session_state and Streamlit refuses that once the
  widget with that key exists. Below the boxes it raised instead of restoring —
  a poor thing to discover while trying to recover a letter. Same reason the
  headline candidate panel is where it is.
- **`draft_store.restore()` runs BEFORE `commentary.write_template()`**, which
  creates the file when missing. Afterwards, a freshly created template looks
  like a legitimately empty local draft and the comparison picks it.

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

### The cattle futures feed, and why the letter no longer trusts it

On 2026-09-28 the Monday AM brief printed **"Settlement on 9/11/26"** and meant
it: Oct feeders at 332.50 when Friday had settled 335.00, a "+4.95 daily move"
on a session that moved 0.075, and a JSA basis of +5.29 where the real figure
was +2.79. `gather()` returned an **empty error list** the whole time.

**Nothing caught it because every check asked whether data came back, and it
had.** The newest bar of a stale series is a perfectly good bar. Staleness is
not an exception, so nothing raised, so nothing was said. That is the lesson;
the rest is detail.

What is actually wrong upstream, verified by direct probe that morning:

| what | state |
|---|---|
| `/aggs` LE, GF at `1session` and `1day` | **ends 2026-09-11** (343 bars, nothing after) |
| `/aggs` LE, GF at `1hour` | has 09-11, then **09-25** — nothing for 09-14..09-24 |
| `/aggs` CL, ZC, ES at every resolution | current, same morning |
| `/snapshot` LE, GF | current |

So the trades exist and only the daily roll-up stopped, the hole is
cattle-only, and the documented 09-14..09-18 gap had grown to **09-14..09-24**.
Worse, **bars already served were retracted**: `settle_log.json` still held
09-23 and 09-24 values the API no longer returns, which is why "the newest bar"
can never be read as "the last session".

`sources.fetch_futures` now does three things, and each one has a test:

- **Detects.** It asks whether the series is behind the last weekday it could
  have a bar for, not whether it parsed. **The recovery trigger is tighter than
  the staleness alarm on purpose** — trying the hourly bars costs one request,
  while a warning nobody believes is the state this began in. A day count loose
  enough for the nine exchange holidays a year is also loose enough to hide a
  feed one session behind, which on a Monday quotes Thursday as Friday. The
  trigger therefore fires harmlessly on holidays; `MAX_SETTLE_AGE_DAYS` stays
  loose and drives only the loud "do not send" message.
- **Recovers**, from the hourly bars, and **only sessions the real history
  lacks**. An hourly close is a last trade and a settlement is a closing range:
  on 09-11 they differed by up to 0.30. The snapshot upgrades a recovered close
  to the official settlement only when its own close proves it describes that
  same session, and is refused once the next session opens — otherwise a live
  price enters a morning brief, the bug `completed_only` exists to prevent.
- **Never subtracts across the hole.** The bar before 09-25 is 09-11 and that
  difference is a fortnight dressed as a day. A missing change marks itself
  `[[?]]`; a wrong one looks exactly like a right one.

Three things that look like oversights and are not:

- **The snapshot's `change` and `previous_settlement` are never read.** They
  are derived from the same broken daily series. At 08:52 that morning, Friday
  having settled 335.00, GFV6's snapshot reported `previous_settlement 332.50`
  and `change +2.25` — the 09-11 bar and a seventeen-day move, under the
  exchange's own field names. Taking `change` because it looked authoritative
  would have restored the bug wearing a different hat.
- **`settle_log.record()` skips a contract whose `settle_source` is
  `"hourly close"`.** That file is the authority for the prior-Friday base once
  a value lands in it, so a last trade written there makes a later
  week-over-week change quietly wrong by a few ticks. A snapshot settlement is
  a settlement and is kept.
- **Recovery is judged on the freshest contract, not on every one.** A back
  month that did not trade yesterday has no bar for ordinary reasons, and
  "is any contract behind" would fetch hourly bars every day of the year on a
  January feeder nobody quoted.

**THE GAP IS UNRECOVERABLE, AND THAT IS SETTLED.** `/trades/LEV6` and
`/trades/GFV6` return **zero ticks** for every one of 09-14..09-24, so the hole
is in the raw trade table and no aggregate can rebuild it. Ten `/aggs`
resolutions were probed, plus every date-range grammar the cursor reveals
(`window_start.gte/gt/lte/lt`; `from`/`to`/`start`/`end`/`date.gte` are
accepted and silently ignored, returning the full unfiltered series). The
weekly and monthly bars are aggregates of the surviving dailies, not
independent data, so they do not even bound it. Do not go looking again.

Two independent corroborations that it is cattle-only, neither of which uses
`/aggs`: `JSA.BASIS_TRACKER.FUTURES_PRICES` took 59-72 rows of grain from the
same provider on every business day straight through the hole, and
`JSA.RISK_ANALYZER.EXTERNAL_FETCH_LOG` shows `/futures/v1/snapshot` returning
200 throughout. So it is not a credential, a quota or a fetch-path problem.

**Snowflake holds no CME cattle futures at all** — checked exhaustively on
2026-09-28 across every schema. `CME_FEEDER_CATTLE` is the cash index plus
auction data; `CME_FTP_DAILY` is CME's published *index* file and has no
contract column. The futures that do exist (`BASIS_TRACKER`, `COST_OF_CARRY`,
`RISK_ANALYZER`) are grain and oilseed only. It is not a fallback for this.

### A settlement is not a close, and the snapshot knows neither reliably

The first fix read the snapshot's `settlement_price` and shipped for about an
hour. It was wrong in the most expensive way.

| 2026-09-25 | Oct LC | Dec LC | Oct FC | Nov FC |
|---|---|---|---|---|
| official **settlement** | 218.875 | 222.150 | **334.925** | 331.975 |
| last trade (hourly close, snapshot `session`) | 218.85 | 222.10 | 335.00 | 332.00 |

CME settles live and feeder cattle on a weighted average of the **closing
range**, so the last trade and the settlement differ routinely — here by 0.025
to 0.075 on all four. The snapshot's `settlement_price` carries the *last
trade*, so reading it as a settlement produces a wrong number wearing the word
"settlement".

**`previous_settlement` is right before the open and wrong after it.** At 07:30
it read 334.925 for GFV6, which is Friday's settle; by 08:52, once the Monday
session went active, the same field read 332.50 — the 09-11 bar — because
Massive recomputes it off the broken daily series. The morning brief is built
inside that window, which is exactly what makes it a trap. Nothing in
`fetch_futures` reads `change` or `previous_settlement` any more.

How Friday's settles were established, since it is worth being able to redo:
`previous_settlement` pre-open cannot be Thursday's, because the settle log has
Thursday at 331.75 and they disagree; the only settled session between Thursday
and Monday pre-open is Friday. Public market reports (Brownfield's 09-24 and
09-25 closes, the WLJ wrap-ups) agree to the half cent. **USDA's own
`lsddcbs.pdf` does NOT confirm it** — its CME table prints `APR/JUN/AUG — N/A`
and never carries the front months, so do not send anyone there.

**The settle log was right and Massive was wrong.** Its 09-23 and 09-24 values
were recorded from bars the API has since retracted, and public reports confirm
them. The retraction is Massive's fault, not evidence against our record. So
the log is now a recovery TIER in `fetch_futures`, ranked above an hourly close
because it holds real settlements.

**Mixed basis yields no change at all.** Once the log fills 09-24 the two ends
are adjacent again, but Friday's last trade against Thursday's settlement gives
+3.25 where the true settle-to-settle move is +3.175 — adjacent, plausible and
wrong. `settle_basis` exists to refuse that.

### Typing a settle in by hand

Where the feed cannot supply a number and no arithmetic can invent one, the
letter's standing answer is to put a human on it — the same answer it gives for
the prior-Friday week base and for headlines. `settle_log.bank()` is that entry
point, reachable three ways:

- **the authoring page** — "Enter the official settles", under the week-base
  form, shown only when a contract's settle did not come from the real
  settlement history;
- **the CLI** — `--settle GFV6=334.925,LEV6=218.875`, or
  `GFV6=334.925@2026-09-25` to name the session; defaults to the last weekday
  before the issue date;
- **`settle_log.bank({...}, when)`** directly.

**It writes to the settle log rather than a file of its own**, and that is the
whole design. `fetch_futures` already reads the log as a recovery tier ranked
above an hourly close, so a banked value is picked up on the next fetch with no
new plumbing to apply it — which is also why the CLI banks BEFORE `gather()`
and why the page sets `wcr_force_fetch` and re-runs the fetch instead of
patching the ctx. The arithmetic lives in one place.

**It restores the daily change, not just the settle.** An hourly close against
a banked settlement is a mixed basis and yields nothing; two settlements give a
move. On 2026-09-25 that is the difference between a marked `[[?]]` and Oct
feeders +3.175.

**It cannot overwrite real data.** `fetch_futures` fills only sessions the
settlement history lacks, so a typed figure loses to a real bar the moment
Massive serves one — the same rule the week base follows, for the same reason.
If Massive ever serves a settlement that is simply *wrong*, this will not
override it, and that is a known limit rather than an oversight.

The `source` lands in `SAVED_BY` on the Snowflake row (`page`, `cli`,
`manual-verified`), so a hand-entered settle stays distinguishable from a
fetched one without changing the row format.

**Banked on 2026-09-28 for session 2026-09-25**, since the provenance matters
if anyone re-derives them: Oct LC 218.875, Dec LC 222.150, Oct FC 334.925, Nov
FC 331.975. Feb LC and Jan FC were deliberately left on the marked hourly
close — they were never independently verified, and banking an unverified
number is the error this whole section is about.

### Three quieter things the same morning turned up

- **The chart of the day was drawing the stale series.** `fetch_front_history`
  had no staleness test at all, so it returned GFV6's 60 sessions ending 09-11
  at 332.50 — to be printed beside "Oct feeders: 334.925". It now returns `{}`
  for a series that is stale or has a weekday run missing, and `build_chart`
  falls through to corn, crude or the S&P, all current throughout. Not
  recovered, because a filled series would join 09-11 to 09-25 with a straight
  line through a fortnight that does not exist.
- **`hints()` discarded every figure for the AM format, and always had.** The
  morning brief's only section key is `headlines`, which was missing from the
  `lead` tuple, so `add()` dropped all six settles, the slaughter, the cash and
  the YTD. The guard that stopped a `KeyError` turned the crash into silence,
  and no test called `hints()` with `kind="am"` until 2026-09-28. `headlines`
  is now last in that tuple so the evening formats keep their figures under
  Market Action.
- **The staleness warning did not reach the page or the PDF.** It lived only in
  `st.session_state`, so any reload showed a clean bill of health over stale
  numbers, and `build.main --no-fetch` — the run that makes the emailed PDF —
  starts a fresh error list and never calls `gather()`. `report_futures_health`
  only reads the ctx, so both now re-derive it.

### In flight as of 2026-09-24

- **Massive's futures history has no bars for 2026-09-14..09-24** (widened from
  09-18 on 2026-09-28, and bars already served were retracted — see "The cattle
  futures feed" above, which supersedes this bullet for everything but the
  moving averages). Not a fetch
  bug — the weeks are absent upstream. It leaves the PM moving averages marked
  `[[?]]`, because an average over a gapped series is wrong rather than
  approximate. `letter/settle_log.py` now records the front-month settles on
  every build, so the weekly change stops depending on their history once a
  letter has been built on a Friday. Deleting `letter/data/` no longer restarts
  it — the log is mirrored to Snowflake and `settle_log.sync()` pulls it back.
- **Azure admin consent is pending** for the app registration "JSA Letter -
  email read" (delegated `Mail.Read`). Until it is granted, the headline
  candidate panel runs without the four subscription digests, which show one
  line saying the mailbox is not connected. It now also blocks the one thing
  that would back-fill the letters published before 2026-09-24 — Sent Items is
  the only record of those. No code change is needed when it lands.
- **One open call left with Ross.** Whether Friday should print a region that
  never established a test all week — the shared cash block omits it, where
  Friday's old block said "South: Undefined", and on a weekly letter that
  absence is arguably news. (The second call, making the week base durable, was
  decided and done: see the `[[?]]` section above.)
- **`render.cash_cattle_block()` and `sources.fetch_regional_cash()` are dead.**
  No caller since Friday moved to the shared cash block. Kept only because they
  are the basis for the "Undefined" option above — if that is declined, delete
  both, or they will read as live code to whoever looks next.
- **The Sterling Profit Tracker carries the packer margin** the evening letter
  quotes by hand ("Sterling packer margins ... +138.80/hd versus +177.16/hd week
  before"). It arrives from `jnalivka@fmtc.com` and is already fetched for
  headlines — worth parsing as a FIGURE once a real one can be seen.

### Two things not to undo

- **The morning brief is one page and under three minutes.** That budget is the
  product. `render.build_html` returns early for AM rather than opting out
  section by section, so a section added to the evening letter cannot leak into
  the morning one; keep it that way.
- **No fetched EDITORIAL text writes itself into a letter.** Headlines are a
  pick list on the authoring page; `render.py` has no import path to the
  fetchers and a test asserts it. Every other figure is a USDA or CME number
  that is either right or marked `[[?]]` — a headline has no `[[?]]`, so it gets
  a human instead.

  Stated as "nothing fetched writes itself into a letter" until 2026-09-24,
  which the chart of the day made literally false: it is fetched, and it renders
  without anyone picking it. The distinction that actually matters is
  editorial-vs-arithmetic. A price series is the same kind of thing as the
  cutout — right, or marked. Prose written by someone else is not, and that is
  what the rule is protecting. `letter/chart.py` still cannot fetch; the series
  comes from `build.gather` like every other number.
