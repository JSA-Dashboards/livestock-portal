# JSA Livestock Portal

A single Streamlit process (`Home.py`) bundling thirteen livestock dashboards
under `apps/`: CME Feeder Cattle Index, Seasonal Futures & Spreads, Cattle on
Feed, US Cow Herd, Mexican Feeder Imports, Fed Cattle Crush, Backgrounding
Crush, Cattle Weights, Beef Cutout, Beef Trimmings, Livestock Inventory, Cash
Cattle Trade, US Beef Trade.

`Cattle Weights` was renamed from `Beef Weight` on 2026-09-10. Only the visible
label changed — the folder is still `apps/beef_weight/` and the `url_path` is
still `beef-weight`, deliberately, so existing bookmarks keep working. Do not
"tidy" either one.

## Every headline must read on its own — a standing rule

Asked for directly on 2026-10-07, and it governs every page, not the one it
came up on: **a tile label, a section header or a delta line must be
unambiguous to someone who reads only that line.** If a reader has to look up
at the section header, do arithmetic between two tiles, or decide which of
two numbers a percentage belongs to, the headline has failed.

What that rules out, each of which was live on this portal at some point the
same day:

- **A label that does not name its own figure.** "WASDE 2026 forecast" over
  `6,262` does not say imports, exports, pounds or dollars. It is
  "USDA 2026 import forecast" now. The section header above it is not an
  excuse — headers scroll away and tiles get screenshotted.
- **A delta the reader has to orient.** "3.3% — recent pace against this"
  made you work out which number was above the other. It says
  "running 12.3% above this" now. A delta that needs a sentence gets one.
- **A number whose comparison is implied.** "Forecast vs 2025" became
  "USDA 2026 forecast vs 2025" at Ross's request, because the first one left
  you to infer whose forecast and for which year.
- **Jargon where a plain word exists.** Tile labels say **USDA**; the report
  is named **WASDE** only in the section header and the caption, where it is
  provenance rather than the point.
- **A bare `0`.** "0 vs Aug" reads as a missing figure; USDA leaving a
  forecast alone is an answer, so it prints "unchanged".
- **Parentheses around a number.** In USDA's reports they mean NEGATIVE.

The two further up this file are the same rule arriving from other
directions: the Mexican feeder caveat that must stay above the figure it
qualifies, and the letter-versus-dashboard FCI disagreements, where both
numbers were defensible and the pairing was the bug.

## Never set SNOWFLAKE_SCHEMA in this app's secrets

**NINE** bundled modules read Snowflake and each defaults `SNOWFLAKE_SCHEMA` to
the schema **it** owns:

| module | its default |
|---|---|
| `apps/beef_weight/nass_cache_client.py` | `NASS_CACHE` |
| `apps/livestock_inventory/nass_cache_client.py` | `NASS_CACHE` |
| `apps/us_cow_herd/nass_cache_client.py` | `NASS_CACHE` |
| `apps/cme_feeder_cattle/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/us_cow_herd/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/mexican_feeder_imports/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/fed_cattle_crush/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/backgrounding_crush/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/beef_trimmings/app.py` (`_sf_connect`) | `BEEF_TRIMMINGS` |

**This table said SIX until 2026-10-07 and it had been wrong since the crush
pages landed**, which is worse than it sounds: the whole point of the section is
how much breaks at once, and it was understating that by a third. The three it
missed are the two crush pages' `snowflake_db.py` copies and US Cow Herd's
*second* reader — that page has both a `snowflake_db.py` and a
`nass_cache_client.py`, so it appears twice and a reader scanning page names
rather than file paths will count it once. `letter/draft_store.py`'s docstring
said "five", a third number, and is corrected too.

Re-derive it rather than trusting the count; nothing keeps the table honest:

    grep -rn "SNOWFLAKE_SCHEMA" apps letter --include="*.py" | grep schema=

Added 2026-10-04: `marsapi.ams.usda.gov` rejects requests from Streamlit
Community Cloud's IPs, so the import side of Beef Trimmings (South America /
Australia-NZ Frozen 90s) moved to a droplet cron job writing
`JSA.BEEF_TRIMMINGS.IMPORT_COW90`, read via a dedicated `LIVESTOCK_PORTAL_SVC`
grant on that schema (same identity already used for `NASS_CACHE` +
`CME_FEEDER_CATTLE`). US Fresh 90s still calls `mpr.datamart.ams.usda.gov`
live — that domain isn't blocked, only `marsapi.ams.usda.gov` is.

**That cron's code is NOT in this repo and it is not unversioned.** It lives in
`JSA-Dashboards/beef-trimmings-dashboard` at `deploy/fetch_import_cow90.py`,
with `deploy/run_fetch.sh` beside it, deployed to
`/opt/beef-trimmings-dashboard/` on the droplet. It MERGEs on
`(report_date, origin)` rather than rewriting the series, so re-running it is
free.

Worth stating because the obvious search finds nothing: that repo is not
cloned on Ross's machine, so grepping the local checkouts turns up a reader
with no writer and reads exactly like an ingest nobody ever versioned. On
2026-10-07 I concluded precisely that and built a second one — module, cron
installer, tests — before `crontab -l` on the droplet showed the real job. It
was reverted in `a3ae41e`. **Two writers doing a full-series replace on one
table, on different schedules, against a source the page has no other copy of**
was the outcome one merge away. Check GitHub's org listing before concluding a
droplet job is unversioned; `gh repo list JSA-Dashboards` costs one call.

The schedule is Friday plus a Monday catch-up, which was the other thing I got
wrong — it is not a single weekly run with no slack:

    30 16 * * 5   "Beef trimmings import fetch"
    0  7 * * 1    "Beef trimmings import fetch (Monday catchup)"

So a late USDA publication is already covered by Monday. The 2026-10-02 report
landing after the 10-05 run left the page on 09-25 data for a few days, which
argues for a daily sweep, but it argues about the CADENCE of a job that exists.

Setting it to any one value overrides all nine and silently breaks the others.
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

**Beef Cutout is a third case and the list above used to omit it.**
`JSA-Dashboards/jsa-beef-cutout-dashboard` exists, but it is not a vendored
copy — it is an ancestor. 682 lines against this page's 1,397, and it carries
none of `_cut_numbers`, `primal_weights` or `cutout_attribution`, so the whole
attribution panel is portal-only. Check it before porting a fix in the shared
*fetch* code; do not assume a change here has a counterpart there, and do not
copy this page over it (verified 2026-10-02).

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

The index, fed crush, backgrounding and daily letter pages use `st.tabs`. A
hidden Streamlit tab is hidden, not skipped: its widgets still execute every
rerun, so a value computed in one tab is available in another. What decides
correctness is SCRIPT order, not tab order — the fed crush's cost-of-gain
build-up must still be written after the widgets it divides by, even though it
displays elsewhere.

The corollary on the letter page is cost rather than ordering: the Cattle
Market Rundown tab would write a PowerPoint file on every rerun, so the write
is memoised. See that section for the rule — a tab is the right shape when the
hidden body is cheap, and `st.segmented_control` is the answer when it is not
(Cold Storage).

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

### The scorecard's checkpoint must follow the page, not the clock

**Broken twice in two days, from opposite directions, and both times the tell
was the tiles and the table disagreeing about the same week.**

The scorecard replays each past week at the SAME point in the week the page is
standing at, so the accuracy figure describes the number above it. On a
Wednesday that is right. On a Tuesday it is not: the live week has opened, the
only publication is a Monday cut with a week-to-date of **0**, and replaying
ten weeks from an empty base collapses every estimate to one figure — the
median late trade added to nothing — grades every row "weak", and reports a
23% median miss for calls that were really 1.5% out.

Seen live 2026-10-06. The tiles showed the settled Sep 28 week, called 60,897
against USDA's 60,063. The table underneath showed **49,062** for that same
week. Both were honestly computed; together they were nonsense.

`_previous_week_checkpoint` now steps back to the last week that actually
traded whenever the live week is still empty, which is also the checkpoint the
settled tiles are using — so the two cannot drift apart. **A checkpoint nobody
would ever forecast from is not a checkpoint worth scoring at.**

The pair of failures is worth keeping together: 10-05 had the tiles overwrite
the call with the actual, 10-06 had the table rescore it at a point the call
never stood at. Same invariant, opposite ends. Two tests pin it.

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

### The prediction on the record — SETTLED 2026-10-05

The tab's first live run, for the week of 9/28–10/2 and standing at Friday's
1:30 pm cut, called **5-Area 61,167** (range 59,428–68,363) and **national
81,723** (range 74,476–94,063). USDA printed **60,063** and **88,019** on
Monday 2026-10-05.

| | called | printed | miss | in range |
|---|---|---|---|---|
| 5-Area | 61,167 | 60,063 | +1,104 (+1.8%) | yes |
| National | 81,723 | 88,019 | −6,296 (−7.2%) | yes |

Both landed inside the stated ranges, and both missed in the direction and by
roughly the amount the method advertises — the 5-Area's 1.8% against a
backtested median of 1.5%, the national's 7.2% against 7.7%. **The national
under-predicted, exactly as the post-blackout bias warned it would**: the gap
came in at 27,956 head against the 20,556 four-week median used, above the
15,048–25,700 the previous six weeks had run. That is the whole error — step 1
was nearly exact and step 2 carried it.

### A replayed call is NOT the call we made, until you pin the pool

**Found 2026-10-05, and it had already corrupted the scorecard.** The page
fetches a rolling 365 days ending *today*, so the analogue pool loses its
oldest week about every seven days. Replaying the same 9/28 call from windows
three weeks apart gave **61,167 / 60,897 / 60,627** — a 540-head spread on a
call whose median miss is about 1.5%. The number we are judged on was quietly
decaying after the fact.

This is the failure the sibling FCI `snapshots.py` exists to prevent, arriving
by a different route. There it is USDA's data that grows under the estimate;
here it was *our own pool* moving under it. `scorecard.py`'s docstring checked
the first and missed the second — corrections really are rare (0 in LM_CT150
over twelve months, 0.54% of daily rows), and that reasoning was sound as far
as it went.

`FORECAST_MAX_ANALOGUES = 20` fixes it by anchoring the pool to the 20 most
recent qualifying weeks *before the week being forecast*, so any window
reaching back far enough gives the identical answer. Measured over 47 Friday
checkpoints the cap is **free** — 6.31% median absolute error and 57% within
10%, the same to two decimals as no cap — while 16 costs 0.5 points and 12
costs 2.3. `tests/test_cash_forecast.py` pins the stability, not just the
accuracy.

One consequence worth knowing: under the cap the 9/28 call replays as
**60,897**, not the 61,167 actually printed on the night, because the live
call that evening used 27 analogues. 60,897 is the better of the two against
USDA's 60,063 (−1.4% against +1.8%), but **the figures in the table above are
the ones that were really made** and the page will not reproduce them.

### Once the week prints, the tiles must stop forecasting

`forecast_5area` returns `done=True` once Friday's final lands and hands back
the week-to-date unchanged. A headline tile reading `central` in that state
therefore prints **the actual, twice**, and the call we made disappears. On
2026-10-05 the tiles read "5-Area week to date 60,063 / 5-Area forecast print
60,063" while the scorecard six inches below reported a call of 61,167. Both
were true; together they were a bug — the same shape as the letter-vs-dashboard
FCI disagreement above, and caught the same way, by putting the two numbers
side by side.

The tiles now switch to a scoreboard — *we called* against *USDA printed*, for
both figures — as soon as the week is in `published5`, reading the scorecard's
own newest row so the two cannot drift apart. Step 2 also prints the
**realised gap**, since when the national call misses that is always why.

## The Packer Leverage tab

Added 2026-10-05 as the **fourth tab** on Cash Cattle Trade. It answers how
much of the week's kill packers never had to bid for, from USDA's own split of
slaughter by purchase type. Fetching and the arithmetic are in
`apps/cash_trade/leverage.py`; the layout is in `app.py`, the same split as
`scorecard.py`.

    LM_CT153 §B  slaughter split formula / forward / negotiated / neg grid
    LM_CT153 §A  packer-owned slaughter
    LM_CT153 §C  forward contract purchases, weekly and cumulative
    LM_CT142     committed and delivered head

**TWO CLOCKS, AND MIXING THEM IS THE TRAP.** LM_CT154's row dated 9/28 is
47,138 head **purchased** in the week just ended. LM_CT153's row dated 9/28 is
62,190 head **slaughtered** that week, bought whenever they were bought. They
are different populations on different timelines and their ratio wanders —
0.83, 1.04, 1.15, 1.14, 1.15, 1.32 across 2026-08-24..09-28. A "share" built
from one over the other looks like a share, moves like a share and measures
nothing. **Every share on the tab is computed inside LM_CT153 alone**, and a
test asserts the module never reads slug 2481.

**Section names are a PATH SEGMENT**, the trap `direct_reports.py` documents
for MARS. The bare slug answers 200 with a near-empty row rather than an error.
The datamart catalog lists them under **`sectionNames`** — `GET /reports` and
read that key, rather than guessing at a name.

### Currentness, and why there is no days-on-feed number

Added 2026-10-06, the third leg of the tab. **There is no published
days-on-feed series.** NASS carries on-feed inventory, placements and
marketings and nothing by days fed — the "120+ days" figure analysts quote is
derived from the placement flow, not reported. Nor does AMS publish a
showlist: zero of its 151 reports is showlist-adjacent, because a showlist is
a private communication between a feedyard and the buyers it invites and never
enters mandatory reporting.

So the weekly stand-in is **carcass weight**, which arrives every Monday
rather than once a month. Cattle held past their window put on weight, so
weights above trend mean feedyards are behind and the showlist is bigger than
a head count suggests.

**It costs no new request.** `price_df` is already pulled for the Weekly tab
and `weight_range_avg` rides along on LM_CT150 back to 2004.

**AGAINST TREND, NOT AGAINST LAST YEAR, and that is the whole correctness of
it.** Fed cattle have got heavier for two decades — genetics, feeding
efficiency, cheap corn — so a raw year-ago delta counts ordinary drift as
market signal. On 2026-10-05 live weight was +67 lb on the year, of which
about +7 is drift; against a trend fitted on the SAME ISO WEEK of the prior
eight years it is **+86 lb**, which is the number worth acting on. Fitting on
the same week also removes the season without a separate adjustment.

Eight years, because the drift is secular and slow and a short fit mistakes a
run of heavy years for the baseline — exactly the error the measure exists to
avoid. Too little history and `weight_context` returns no trend at all rather
than a fitted line through four points.

**It currently disagrees with the forward book, and that is the market, not a
bug.** Weights +86 lb above trend say cattle are backing up and the packer can
wait; the book down 31% on the year says he is short of committed supply and
cannot. Both are true. The tab shows both rather than averaging them into a
score that would hide the tension.

### Cash need is a RUN RATE and the page has to keep saying so

Added 2026-10-05 under the headline: how many head packers have to transact
for in a week — about **71,700** negotiated cash, **103,900** including grid,
on the four weeks to 2026-09-28.

**There is no published "still to buy this week" figure and one cannot be
derived.** The week's purchases and the week's slaughter are the two clocks
above; subtracting one from the other invents a number rather than measuring
one. So the tab reports what recent weeks each *required*, with the real high
and low of those weeks rather than a standard deviation — with four
observations a spread can be pointed at and a sigma is decoration.

The honesty check is printed beside it and **computed live rather than
hard-coded**, so the claim keeps describing the market rather than the market
of the day it was written: over the last 52 weeks a four-week average landed
within a median **8.3%** of the week that followed, 23% at the 90th
percentile. Including grid it is **7.3%** — grid and cash partly offset each
other week to week, so the wider measure is the steadier one, which is not the
intuitive result.

### "Weeks of coverage" shipped WRONG, and the tell was read as a virtue

**Corrected 2026-10-05, after a few hours live.** The tab carried a tile
reading "Weeks of coverage · book ÷ 4-wk ship pace", at 1.21. It was not weeks
of anything.

`Committed` in LM_CT142 is head committed **during** that week — a weekly
FLOW, not a standing stock. The daily sibling LM_CT106 settles it beyond
argument: `acc_current_volume` accumulates within the week, resets each
Monday, and ends on exactly the weekly figure (316,910 for w/e 09-28, 409,230
for 10-05). So committed ÷ delivered is one flow over another, and what it
measures is whether the book grew or drained that week. It is now called
`signings_vs_pace` and described that way.

**The evidence was in hand and was misread as a feature.** The ratio's median
is 1.03 with a standard deviation of 0.08 across 859 weeks and sixteen years —
reported at the time as "remarkable stability" and used to argue that a
reading of 1.21 was a 97th-percentile outlier. Two flows in steady state is
exactly what that distribution looks like. A stock over a weekly flow would
swing far wider. **A series that will not move is evidence about what it is,
not a property worth admiring.**

### The standing book, which is what leverage actually needs

LM_CT153 §C and its Breakdown section carry the real inventory — cattle bought
and not yet delivered. USDA's own heading on `ams_2480.pdf` is **"Cumulative
Total for Listed Months"**, 714,623 head on 2026-09-28, with a month-by-month
delivery schedule and the same months a year earlier.

That comparison is the leverage signal: 313,908 head committed over the next
three delivery months against 453,610 a year ago, **−31%**, and the gap widens
further out (Dec −47%, Jan −60%). Packers have far less captive supply coming
than they did, which is why the negotiated share sits high.

**THE MONTH LABELS REPEAT AND CANNOT BE KEYED ON.** The table spans two years,
so `Total Sep Deliveries` appears twice — 86,305 for Sep '26 and 9,453 for
Sep '27 — and a dict keyed on the label silently keeps the far month, then
reports a near-month book an order of magnitude too small with nothing
raising. Only the DETAIL rows carry a year (`Sep '26/Oct`), so the delivery
months are read from those in order and the summary rows are zipped on by
position. The layout is 16 delivery months × 6 basis rows, then 16 `Total`
rows, then 16 `Last Yr` rows, each block in the same order.

The audit is that the sixteen monthly totals sum to the published book figure
**exactly** — 714,623 on 2026-09-28. `reconciles()` checks it and the page
says so; if the row layout ever shifts, the sum stops matching instead of
quietly mis-attributing a month.

### `leverage.SCHEMA` exists because the cache serves shape, not freshness

Adding the `schedule` key to `load()` changed nothing on the page: the tile
read "—" and the whole section vanished, silently. `st.cache_data` keys on the
decorated function's own code and arguments and **never on the modules it
calls** — the trap recorded further up this file — and `fetch_leverage`'s body
is one line that had not changed, so the disk cache kept handing back a dict
from before the key existed.

`leverage.SCHEMA` is passed into the cached fetch purely as part of the key.
**Bump it whenever `load()` changes the shape of what it returns.** A reboot
would also clear it, but only on the deployed app and only if someone knew to.

### Four things that look wrong and are not

- **Negotiated grid is NOT folded into the headline.** Its base is negotiated
  in the week, so for "did the packer have to transact" it belongs with cash;
  for "what share discovered a cash price" the convention is cash alone. They
  differ by a third — 19.7% against 29.1% for w/e 2026-09-28 — so the page
  prints the strict one, shows grid as its own band, and picks neither.
- **The denominator is USDA's published total, not the four parts summed.**
  They agree exactly today (0 head across 12 weeks). If USDA ever adds a fifth
  category, a derived total would keep the shares summing to 100% while
  describing less than the whole kill; the published one makes that visible.
- **Coverage divides the committed book by a FOUR-WEEK shipping pace.** A
  holiday week halves the denominator and prints a coverage spike that is only
  the calendar.
- **Imported head are counted as committed supply.** An imported formula steer
  is still an animal nobody had to bid for.

**It is the share of the REPORTED kill, not of US fed slaughter.** Plants
outside mandatory reporting are not in the denominator, so read it as a ratio
over time — which is how it is published — not as a national head count. And
LM_CT153 reports the PRIOR week, so the tab is one week behind the daily cash
prices on the other tabs. That is USDA's schedule, not staleness.

A share is a number between 0 and 1 whether or not it is right, so none of the
above fails loudly. `tests/test_packer_leverage.py` pins all of it.

## The morning cutout — LM_XB402

Added 2026-10-06. The Beef Cutout page now reads **both** daily cutout
reports, behind a session switch at the top: `Morning (9:30am) | Afternoon
(close)`. Fetching, parsing and the Snowflake banking are in
`apps/beef_cutout/am_cutout.py`; the panel is in `app.py` next to the brand
helpers it needs, the same split as `cof_recap` and `leverage`.

**They are TWO REPORTS, not one report published twice**, and the sidebar used
to say otherwise. LM_XB403 goes out once, in the afternoon. The morning
figures are LM_XB402 — a separate report, a separate slug, and the gap between
them is the point: on 2026-10-06 the morning said Choice 382.46, **+4.20**,
and the close printed 378.93, **+0.67**. A $3.53 fade the portal could not
show.

### There is no feed for it and no history anywhere — do not go looking again

Established by probe on 2026-10-06. Every avenue is closed:

- The datamart catalog (`GET /services/v1.1/reports`, 151 reports) **does not
  list slug 2452 at all**. 2453 is the only daily boxed beef cutout in it.
- Slug 2452 answers HTTP **200** with the body `"No Results Found. "` to every
  query shape — bare, `lastReports`, `allSections`, and an explicit
  `report_date` range. A named section instead returns "Unable to find this
  subreport", so the service knows the slug and has no rows for it. A 200 that
  means "nothing here" is the trap `direct_reports.py` documents for MARS.
- MARS v1.2 refuses it: `"Slug Id is invalid / Report has no data"`. MARS
  carries **no boxed beef reports of any kind** — five titles match "beef" and
  they are trimmings, variety meats and retail features.
- The only live copy is `www.ams.usda.gov/mnreports/ams_2452.pdf`,
  **overwritten in place every morning**. A `?date=` parameter is accepted and
  silently ignored, returning today's bytes whatever you ask for.

So the look-back **cannot be back-filled**. It accrues from the first day the
page records one, and the panel says so rather than letting an empty table
read as a broken one.

**It costs no new secret and no new host.** `www.ams.usda.gov/mnreports/` is
already fetched from the deployed app by `letter/sources.AMS_3208_PDF` with
the same `pypdf`, so unlike `marsapi.ams.usda.gov` this path works on
Community Cloud.

### Banking is opportunistic, and that is a known gap

`JSA.BOXED_BEEF.CUTOUT_AM`, append-only and newest-wins per `REPORT_DATE`, the
same shape as `JSA.LETTER.DRAFTS` and for the same reasons: USDA issues
corrections, an INSERT needs no UPDATE grant, and no write can bury the figure
that was actually published.

Community Cloud has no scheduler — the constraint `letter/rundown.py` records
— so **the page itself is the only thing that writes**, on whichever days
somebody opens it after the morning release. Days nobody opens it are holes.
A cron on the droplet that already writes `JSA.BEEF_TRIMMINGS.IMPORT_COW90`
can take the same table over without changing the page.

**The portal created the schema itself on first run, which was not the
expectation.** It was expected to sit dead until an admin created
`JSA.BOXED_BEEF`, on the assumption that the deployed identity is scoped the
way Ross's CME_INGEST_ROLE is — read-only plus one schema. It is not: on the
first live run, 2026-10-07, `ensure_table()` created schema and table and
banked Oct 06 straight away (Choice AM 382.46 / PM 378.93, fade −3.53). That
is the same CREATE SCHEMA capability `letter/draft_store.py` relied on for
`JSA.LETTER`. **Do not assume the deployed app cannot create what it needs.**

If the write ever does fail, the page prints `⚠️ Morning cutout is not being
recorded` with the reason. That banner is deliberate: a write that silently
fails looks exactly like a page nobody has opened, and months later there
would be no history and no clue why. Same reasoning as the letter page's
autosave banner.

### The droplet cron — `deploy/run_am_cutout.sh`

Written 2026-10-07 to close the holes the opportunistic write leaves. It
**imports `apps/beef_cutout/am_cutout.py` by path rather than reimplementing
anything**, so the cron and the page can never disagree about what a morning
report says — a second copy of a PDF parser, running unattended where nobody
would see it drift, is the `snowflake_db.py`-times-five problem with no
renderer to catch it. A test asserts by AST that it defines none of
`parse_am`, `_num`, `_after`, `bank`, `history` or `fetch_am`.

    deploy/bank_am_cutout.py   the job (also `--dry-run`)
    deploy/run_am_cutout.sh    the cron wrapper
    deploy/install_am_cutout_cron.sh   installer, `--check` to report only

#### Read the droplet's crontab before writing a job for it

The first two versions of this were wrong in ways that would have installed
cleanly and then failed silently for ever. Both were settled by one read-only
`--check` run on the host, 2026-10-07, and neither was guessable from here.

- **Cron on that box mails NOTHING.** Its crontab header says so: there is no
  `MAILTO` and the machine has no MTA, so **a bare entry fails silently**.
  Every one of its ~25 jobs runs through `/opt/alerting/cron-alert "<name>"
  "<log glob>" <script>`, which emails on a non-zero exit, attaches the
  matching log, and kills a job that hangs past `ALERT_TIMEOUT` (90m). The
  installer refuses to write a bare entry. An earlier draft of this section
  asserted "cron mails stderr, and a non-zero exit is the whole alerting
  story" — the second half is right and the first is false here.
- **The host runs America/Chicago, not UTC** (`CDT -0500`, and the crontab
  header states it). An earlier wide 11–22 sweep was hedging that unknown.
- **Credentials live in `$DEST/.env`**, not root's environment — the
  convention `beef-trimmings-dashboard`'s `deploy/run_fetch.sh` has used
  since 2026-10-04. A crontab line calling `.venv/bin/python` directly gets
  no environment under cron, so `am_cutout.enabled()` returns False and the
  job records nothing while looking installed. Sourcing `.env` is the whole
  reason the wrapper exists.
- **`deploy/`, not `scripts/`.** Ten jobs on that host are
  `/opt/<repo>/deploy/run_<x>.sh` writing `/opt/<repo>/logs/<x>_*.log`.

The schedule, times CT:

    15 11 * * 1-5  cron-alert ... deploy/run_am_cutout.sh   # ~20m after release
    0  14 * * 1-5  cron-alert ... (catch-up)                # for a late USDA

Primary plus catch-up is the shape the beef-trimmings fetch already uses
(Fri 16:30 + Mon 07:00). Mon–Fri only: there is no weekend morning cutout.

**The job is idempotent, which is what makes a blunt schedule safe.**
`bank()` inserts only when the report date is absent or its figures changed,
so the catch-up costs one PDF fetch and writes nothing, and a run on a day
USDA did not publish is a no-op because the PDF still serves the last
session. No holiday calendar to maintain and none to get wrong.

Two details in the wrapper that look like paranoia and are not. **A missing
`flock` is handled explicitly**, because `if ! flock -n 9` reads as "could not
get the lock" when the binary is simply absent — command-not-found is 127,
`!` makes it true, and the job exits 0 having done nothing while looking
healthy. And it **`cd`s before creating anything**, so a wrong `APP_DIR`
fails instead of scattering a `logs/` directory elsewhere.

Needs `requests`, `pypdf`, `pandas`, `snowflake-connector-python`, and the
Snowflake block in `$DEST/.env`: `USE_SNOWFLAKE=1`, `SNOWFLAKE_ACCOUNT` /
`USER` / `ROLE` / `WAREHOUSE` / `DATABASE`, and either `SNOWFLAKE_PASSWORD`
or `SNOWFLAKE_PRIVATE_KEY`. **Not `SNOWFLAKE_SCHEMA`** — `am_cutout` names
its table in full and takes no part in the five-module collision at the top
of this file.

**The installer reads the crontab back after writing it**, counts its own two
lines, and exits non-zero if they are not there. That is not belt-and-braces:
the first version printed "appending", piped into `crontab -`, and went
straight to "done", with only a cosmetic `grep` whose empty output looked
exactly like a successful one. A sibling installer copied from it reported
"cron installed" on a host where nothing had been. **An installer that claims
success it has not earned is the same silent failure as the job it installs,
one level up.**

The installer is otherwise idempotent: it pulls rather than re-clones and
**appends to the crontab rather than replacing it**, so the ~25 jobs already
on that host survive. `--check` reports and changes nothing. It stops before cloning or
touching cron when the Snowflake block or the alerting wrapper is missing,
because **a job installed without credentials fails silently once a day for
ever**, which is the one outcome worse than not installing it.

**Claude cannot run it.** SSH to the droplet is blocked by the harness as a
production action, and the user saying "go ahead" does not clear it — nor can
Claude grant itself the rule, which is the point of the gate. Hand over the
command; the same applies to merging PRs.

**As of 2026-10-07 it is NOT installed**: `/opt/livestock-portal` does not
exist on that host, there is no `.env` for it, and no livestock-portal job is
in the crontab.

### Four things that look wrong and are not

- **Negotiated grid is NOT folded into the headline.** Its base is negotiated
  in the week, so for "did the packer have to transact" it belongs with cash;
  for "what share discovered a cash price" the convention is cash alone. They
  differ by a third — 19.7% against 29.1% for w/e 2026-09-28 — so the page
  prints the strict one, shows grid as its own band, and picks neither.
- **The denominator is USDA's published total, not the four parts summed.**
  They agree exactly today (0 head across 12 weeks). If USDA ever adds a fifth
  category, a derived total would keep the shares summing to 100% while
  describing less than the whole kill; the published one makes that visible.
- **Coverage divides the committed book by a FOUR-WEEK shipping pace.** A
  holiday week halves the denominator and prints a coverage spike that is only
  the calendar.
- **Imported head are counted as committed supply.** An imported formula steer
  is still an animal nobody had to bid for.

**It is the share of the REPORTED kill, not of US fed slaughter.** Plants
outside mandatory reporting are not in the denominator, so read it as a ratio
over time — which is how it is published — not as a national head count. And
LM_CT153 reports the PRIOR week, so the tab is one week behind the daily cash
prices on the other tabs. That is USDA's schedule, not staleness.

A share is a number between 0 and 1 whether or not it is right, so none of the
above fails loudly. `tests/test_packer_leverage.py` pins all of it.

## The morning cutout — LM_XB402

Added 2026-10-06. The Beef Cutout page now reads **both** daily cutout
reports, behind a session switch at the top: `Morning (9:30am) | Afternoon
(close)`. Fetching, parsing and the Snowflake banking are in
`apps/beef_cutout/am_cutout.py`; the panel is in `app.py` next to the brand
helpers it needs, the same split as `cof_recap` and `leverage`.

**They are TWO REPORTS, not one report published twice**, and the sidebar used
to say otherwise. LM_XB403 goes out once, in the afternoon. The morning
figures are LM_XB402 — a separate report, a separate slug, and the gap between
them is the point: on 2026-10-06 the morning said Choice 382.46, **+4.20**,
and the close printed 378.93, **+0.67**. A $3.53 fade the portal could not
show.

### There is no feed for it and no history anywhere — do not go looking again

Established by probe on 2026-10-06. Every avenue is closed:

- The datamart catalog (`GET /services/v1.1/reports`, 151 reports) **does not
  list slug 2452 at all**. 2453 is the only daily boxed beef cutout in it.
- Slug 2452 answers HTTP **200** with the body `"No Results Found. "` to every
  query shape — bare, `lastReports`, `allSections`, and an explicit
  `report_date` range. A named section instead returns "Unable to find this
  subreport", so the service knows the slug and has no rows for it. A 200 that
  means "nothing here" is the trap `direct_reports.py` documents for MARS.
- MARS v1.2 refuses it: `"Slug Id is invalid / Report has no data"`. MARS
  carries **no boxed beef reports of any kind** — five titles match "beef" and
  they are trimmings, variety meats and retail features.
- The only live copy is `www.ams.usda.gov/mnreports/ams_2452.pdf`,
  **overwritten in place every morning**. A `?date=` parameter is accepted and
  silently ignored, returning today's bytes whatever you ask for.

So the look-back **cannot be back-filled**. It accrues from the first day the
page records one, and the panel says so rather than letting an empty table
read as a broken one.

**It costs no new secret and no new host.** `www.ams.usda.gov/mnreports/` is
already fetched from the deployed app by `letter/sources.AMS_3208_PDF` with
the same `pypdf`, so unlike `marsapi.ams.usda.gov` this path works on
Community Cloud.

### Banking is opportunistic, and that is a known gap

`JSA.BOXED_BEEF.CUTOUT_AM`, append-only and newest-wins per `REPORT_DATE`, the
same shape as `JSA.LETTER.DRAFTS` and for the same reasons: USDA issues
corrections, an INSERT needs no UPDATE grant, and no write can bury the figure
that was actually published.

Community Cloud has no scheduler — the constraint `letter/rundown.py` records
— so **the page itself is the only thing that writes**, on whichever days
somebody opens it after the morning release. Days nobody opens it are holes.
A cron on the droplet that already writes `JSA.BEEF_TRIMMINGS.IMPORT_COW90`
can take the same table over without changing the page.

**The portal created the schema itself on first run, which was not the
expectation.** It was expected to sit dead until an admin created
`JSA.BOXED_BEEF`, on the assumption that the deployed identity is scoped the
way Ross's CME_INGEST_ROLE is — read-only plus one schema. It is not: on the
first live run, 2026-10-07, `ensure_table()` created schema and table and
banked Oct 06 straight away (Choice AM 382.46 / PM 378.93, fade −3.53). That
is the same CREATE SCHEMA capability `letter/draft_store.py` relied on for
`JSA.LETTER`. **Do not assume the deployed app cannot create what it needs.**

If the write ever does fail, the page prints `⚠️ Morning cutout is not being
recorded` with the reason. That banner is deliberate: a write that silently
fails looks exactly like a page nobody has opened, and months later there
would be no history and no clue why. Same reasoning as the letter page's
autosave banner.

### The droplet cron — `scripts/bank_am_cutout.py`

Written 2026-10-07 to close the holes the opportunistic write leaves. It
**imports `apps/beef_cutout/am_cutout.py` by path rather than reimplementing
anything**, so the cron and the page can never disagree about what a morning
report says — a second copy of a PDF parser running unattended, where nobody
would see it drift, is the `snowflake_db.py`-times-five problem with no
renderer to catch it. A test asserts by AST that it defines none of
`parse_am`, `_num`, `_after`, `bank`, `history` or `fetch_am`.

**The crontab is a blunt hourly sweep, not one pinned minute**, and that is
the design rather than laziness. `bank()` inserts only when the date is absent
or its figures changed, so the extra runs cost a PDF fetch each and write
nothing. Two things fall out:

- **No DST arithmetic.** USDA publishes on Central and droplets run on UTC, so
  a single pinned minute is wrong for half the year unless somebody remembers
  to move it twice a year. A window spans the shift.
- **No holiday calendar.** On a day USDA does not publish, the PDF still
  serves the previous session — already banked, so the run is a no-op. There
  is no list to maintain and none to get wrong.

    # USDA morning boxed beef cutout -> JSA.BOXED_BEEF.CUTOUT_AM
    0 11-22 * * 1-6 /opt/livestock-portal/scripts/run_am_cutout.sh

**CRON CALLS THE WRAPPER, NOT PYTHON, AND THAT IS NOT STYLE.** The Snowflake
block on the droplet lives in a `.env` FILE beside the code — the convention
`beef-trimmings-dashboard`'s `deploy/run_fetch.sh` has used there since
2026-10-04 — and cron gives a job almost no environment. A crontab line
calling `.venv/bin/python` directly therefore gets no credentials,
`am_cutout.enabled()` returns False, and the job installs cleanly and records
nothing, every run, for ever. Sourcing `.env` is the whole reason
`scripts/run_am_cutout.sh` exists. It also takes a `flock` so two runs cannot
overlap, writes a timestamped log under `logs/` and prunes at 30 days, all
matching `run_fetch.sh`.

Two things in that wrapper that look like paranoia and are not. **A missing
`flock` is handled explicitly**, because `if ! flock -n 9` reads as "could not
get the lock" when the binary is simply absent — command-not-found is 127,
`!` makes it true, and the job exits 0 having done nothing while looking
healthy. And it **`cd`s before creating anything**, so a wrong `APP_DIR`
fails instead of scattering a `logs/` directory somewhere else.

**The window is wide because the droplet's timezone is not assumed.**
`run_fetch.sh` documents its schedule in CT while the installer reports UTC,
and nobody here has read the droplet's clock. Idempotency makes the ambiguity
cheap: 11–22 in either reading covers the ~10:55 CT release, at the price of
a few no-op PDF fetches. The installer prints the host's actual timezone —
tighten the line once it is known.

**stdout goes to the log and stderr deliberately does not** — cron mails
stderr, and a non-zero exit is the whole alerting story. Redirecting `2>&1`
would silence it.

It lives in `scripts/` rather than `deploy/` because that is where THIS repo
already keeps its droplet jobs (`scripts/mx_auction.py` and its installer).
`beef-trimmings-dashboard` uses `deploy/`; the two repos disagree and were
left that way deliberately rather than moved unilaterally.

Needs `requests`, `pypdf`, `pandas`, `snowflake-connector-python`, and the
Snowflake env `snowflake_db.get_conn()` reads: `USE_SNOWFLAKE=1`,
`SNOWFLAKE_ACCOUNT` / `USER` / `ROLE` / `WAREHOUSE` / `DATABASE`, and either
`SNOWFLAKE_PASSWORD` or `SNOWFLAKE_PRIVATE_KEY`. **Not `SNOWFLAKE_SCHEMA`** —
`am_cutout` names its table in full and takes no part in the five-module
collision at the top of this file, so there is nothing for it to set.

`--dry-run` fetches and prints without writing; run that first on a new host.
`ensure_table()` runs every time, so a fresh host needs no manual DDL step.

`scripts/install_am_cutout_cron.sh` does the install, idempotently: it pulls
rather than re-clones, and **appends to the crontab rather than replacing
it**, so the beef-trimmings job already on that host survives. `--check`
reports and changes nothing. It refuses to install when the Snowflake
environment is incomplete, and stops before cloning or touching cron —
**a job installed without credentials fails silently once a day forever**,
which is the one outcome worse than not installing it. It reports credentials
by presence and never prints one.

**Claude cannot run it.** SSH to the droplet is blocked by the harness as a
production action, and the user saying "go ahead" does not clear that — it
needs a Bash permission rule. Hand over the command rather than looking for
another route; the same gate is recorded for merging PRs.

### Four things that look wrong and are not

- **Parentheses are negative.** USDA prints a down day as `(2.23)`, not
  `-2.23` — verified against the PM report on 2026-10-06, where Select fell
  2.23. The trap `letter/sterling.py` documents. Read naively that is a
  two-dollar *rally*, and the tile is green on a day the cutout broke.
- **The spread is a free audit and the parser refuses a row that fails it.**
  USDA prints Choice, Select and the spread independently, so the first two
  must difference to the third. A shifted column is the failure that does not
  raise and does not look wrong; `SPREAD_TOLERANCE` allows one cent of
  independent rounding and no more.
- **The parser checks it is reading LM_XB402 and the word "Morning".** The two
  PDFs sit one slug apart in the same directory with a near-identical layout.
  If USDA ever repoints that path, the afternoon close would be banked as a
  morning reading and every fade would silently become zero.
- **The default session reads the two REPORT DATES, not the clock.** A rule
  like "after 3pm show the close" opens on a report that does not exist on
  every day USDA runs late. `am_cutout.default_session()` owns it and
  `tests/test_am_cutout.py` pins the truth table.

**`am_cutout.SCHEMA` exists because the cache serves shape, not freshness** —
the `leverage.SCHEMA` trap. Bump it whenever `parse_am` changes the shape of
what it returns, or the page keeps serving a dict from before the new key
existed and the tile renders "—" with nothing raising.

**The morning panel renders ABOVE the page's `st.stop()` guard**, the same
four-line shape as the Saturday Slaughter view below. It reads a different
USDA host over a different protocol, so an LMR outage must not blank it.

Everything below the switch — attribution, charts, grading, the data table —
is the afternoon report regardless, and a caption says so. USDA publishes no
cut-level detail for the morning report in any feed.

## The Mexican Feeder Prices tab

Added 2026-10-07. Mexican Feeder Imports is now **two tabs** — `Mexican Feeder
Crossings | Mexican Feeder Prices` — `st.tabs`, the Cash Cattle Trade shape.
The first is the whole page as it was; the second answers what a Mexican feeder
calf is worth **inside Mexico** against the border quote the page has always
shown. Arithmetic and every read are in `apps/mexican_feeder_imports/
mx_prices.py`; the layout is in `app.py`, the same split as `cof_recap`,
`leverage` and `am_cutout`.

    JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES   Tamaulipas auction, MXN/kg
    JSA.CME_FEEDER_CATTLE.FX_USDMXN           ECB reference rate, per sale day
    border_prices                             AMS 3486, the Crossings tab's own

On the 2026-09-30 sale a 664–772 lb Tamaulipas steer calf is **$188.64/cwt**
against **$315.00** for AMS 700–800 lb #1-2 steers at Douglas the same day —
**60%**. Three sales on file run 64.2%, 60.5%, 59.9%.

**THE CAVEAT IS THE FIRST THING ON THE TAB AND MUST STAY THERE.** Tamaulipas is
**not** where these cattle come from: Douglas and Santa Teresa take **Sonora**
and **Chihuahua**, and neither state runs a published feeder auction. The
figure is correctly computed and describes a different state's cattle, so a
reader who meets the number before the caveat has already drawn the wrong
conclusion. Moving it to a footnote would make the page wrong without changing
a single value.

**There is no Mexican feeder index, and this was probed properly.** SNIIM
(`economia-sniim.gob.mx`) is a *slaughter*-market system — `Var=Bov` is
substantial and current but prices cattle delivered to a rastro, and `Var=Bec`
is effectively dead (15 rows in Sep 2024, empty for Aug 2026, and 45–50 kg bob
calves where it does report). SIAP carries `Precio` by municipality for
Chihuahua and Sonora, but **annually, on a carcass basis**, with 2025 published
in August 2026. Neither can answer what a feeder calf is worth this week. Do
not go looking again.

### Five things that look wrong and are not

- **Weight is matched on the MIDPOINT, and a band that matches nothing is left
  alone.** The ladders do not align — Tamaulipas in kg, AMS in lb — so each
  Mexican band takes the AMS bracket containing its own midpoint in pounds. The
  351–400 kg lot is 774–882 lb and AMS stops at 800, so it matches nothing.
  Snapping it to 700–800 would compare a heavier calf to a lighter quote and
  **report the weight slide as a price gap** — a number that moves the right
  way for the wrong reason.
- **Two Mexican bands can share one AMS bracket and are kept separate.** 181–200
  and 201–230 kg both sit inside 400–500 lb. With no head counts an average
  would weight a thin band equally with a heavy one and print a figure no lot
  ever traded at.
- **Every heifer band matches nothing, and that is the US feed's state.** AMS
  last priced `Spayed Heifers` at the border on **2025-05-12**; all 23 of 2026's
  quoted days are Steers. A column of dashes looks exactly like a broken join,
  so `us_last_quoted()` exists for no other purpose than letting the panel say
  which it is. Sex is matched because pairing a Mexican heifer against a steer
  quote reads as a discount that is really a sex difference.
- **Only the `CN` ladder is compared.** The site also prints wide `CNH` lots
  (100–180, 181–260, 251–330 kg) that overlap the narrow ladder and run a grade
  cheaper — 58.33 against 81.89 MXN/kg on the same sale. Mixing them would
  double-count a weight and drag every figure down by a grade difference the US
  quote does not share. They are still priced in dollars and shown, flagged.
- **FX reaches BACKWARD only.** A sale is priced at the rate that stood when it
  traded. Reaching forward would restate a past sale every time the peso moved
  — the decay failure `FORECAST_MAX_ANALOGUES` exists to stop on the cash
  forecast tab, arriving by a different route.

**It is a LEVEL, not a margin**, and the page says so. Nothing nets out
freight, the test, the crossing fee, shrink or the buyer's margin, so a calf at
60% of the Douglas price is not 40% of profit.

**The two sides are rarely quoted the same day**, so `compare()` pairs each sale
with the nearest priced border date in either direction and returns `gap_days`
for the panel to print, refusing anything beyond `MAX_GAP_DAYS` (21). A
silently same-day-looking spread would be the letter-vs-dashboard FCI failure
recorded above, by a new route.

**`mx_prices.py` does not import `requests`, and a test asserts it by AST.**
The rule for this page is that `border.py` has no HTTP path so the Streamlit
process cannot acquire one. That forces `usd_per_cwt` to be a *copy* of
`mx_auction.usd_per_cwt` rather than an import, so `tests/test_mx_prices.py`
runs the two against each other over a grid — a test may import the scraper
because a test is not the page.

**`mx_prices.SCHEMA` exists because the cache serves shape, not freshness** —
the `leverage.SCHEMA` trap. Bump it whenever `compare()` changes the shape of
what it returns, or the tiles render "—" with nothing raising.

### The history accrues and cannot be back-filled

`mexicoganadero.com` keeps the **current sale and one previous**, with no
archive and no date parameter, so the series starts at the first run of the
recording job — the same shape as `JSA.BOXED_BEEF.CUTOUT_AM` and for the same
reason. The panel says so rather than letting a short chart read as a broken
feed. Both pages are fetched every run so a missed day is recovered by the
next, which matters more here than for most jobs: a sale nobody fetches is gone.

The writer is `deploy/mx_auction.py` behind `deploy/run_mx_auction.sh`, on the
droplet conventions recorded above — **it was in `scripts/` with a bare crontab
line until 2026-10-07**, which on that host would have failed silently for ever.
As of that date **nothing is installed on the droplet**: every row in
`MX_AUCTION_PRICES` was banked from Ross's desktop (`RECORDED_BY` is
`mx_auction@JSA-Nitro2`), so the series does not advance until the cron is in.

### The tab split, if the page is ever split again

Indenting 1,040 lines under `with tab_crossings:` was done with a
tokenizer-aware pass, not a blind one: a blind indent injects four spaces into
every line **inside** a triple-quoted string, which for a CSS block renders
almost right. The AST cannot distinguish a triple-quoted string from four
adjacent single-line f-strings — implicit concatenation is one node spanning
every line — so `tokenize` is what separates them. Afterwards every string
constant in the module was compared before and after and the write refused if
any had moved.

**`_MX_METHOD` is at module level on purpose**, the lesson CLAUDE.md already
records for the letter page: every multi-line string living above the split is
the only reason indenting the rest is safe. Check that again before moving this
one.

## US Beef Trade — the thirteenth dashboard

Added 2026-10-07. Monthly US beef exports and imports, each against the USDA
WASDE forecast for the same flow. Three tabs — `Exports | Imports | Net
trade` — and **every one of them carries its own WASDE expectation panel**,
which is the requirement the page was built for rather than a flourish. The
arithmetic is in `apps/beef_trade/trade_flows.py`, the WASDE reader is the
root-level `wasde.py` (shared — see the Cash Cattle Trade section below), and the layout is `app.py` — the same split as
`cof_recap`, `leverage` and `am_cutout`.

**No new secret and no new host.** ERS is a plain CSV and ESMIS is the host
`letter/sources.fetch_report_calendar` already reads from the deployed app.

    https://www.ers.usda.gov/media/29544/beef-and-veal-monthly-us-trade-carcass-weight-1000-pounds.csv
    https://esmis.nal.usda.gov/api/v1/release/findByPubId/1659     (WASDE)

### ERS and WASDE are THE SAME SERIES, and that is what licenses the page

For 2025 the ERS file totals **2,579.1** million lb of exports and **5,388.0**
of imports. The September 2026 WASDE prints **2,579** and **5,388**. Not two
similar numbers — the same number, to the rounding step.

That is the whole reason an actual-against-forecast panel means anything here,
so it is **checked live on every load** by `basis_agrees()` rather than
asserted in a comment, and the page says so loudly if it ever stops holding.
A test pins it too, but a test describes the fixture; only the live check
describes production.

It is also why neither obvious alternative source was used:

- **FAS ESR** is what JSA's own `jpsi.com/export-sales-dashboard` already
  reads, and it is the right tool for what it does — weekly, by destination,
  with outstanding sales, and it does carry Beef and Pork. But it is **exports
  only**, it reports *sales* rather than customs-cleared trade, and it is
  product weight in thousand metric tons. None of that can be set against a
  WASDE forecast.
- **Census** is the underlying customs data and the portal already has a
  `CENSUS_API_KEY` pattern for it, but it is product weight by HS code.
  Converting 0201/0202/0206 to carcass weight means applying factors ERS has
  already applied and published.

**TWO JSA SURFACES NOW QUOTE A US BEEF EXPORT FIGURE AND THEY WILL NOT
AGREE.** That is the shape of the letter-versus-dashboard FCI failure recorded
above, so it is worth being explicit that this one is not a bug: a sale is not
a shipment, a shipment is not a customs entry, and product weight is not
carcass weight. The caption under the exports table says exactly that. Do not
"reconcile" them.

### The WASDE meats year is a CALENDAR year — the grain tables are not

Worth stating because the same report disagrees with itself. WASDE's grain
tables are split marketing years (corn 2026/27 runs September to August);
the meats table is plain January to December, and nothing in the file labels
which is which. Anyone who knows WASDE from the grain side will assume wrong.

That is what lets the page sum ERS monthly actuals Jan–Dec and set them
against the forecast at all, so it is pinned rather than assumed — and the
proof is the join itself: ERS Jan–Dec 2025 reproduces WASDE's 2025 line to
0.05 million lb.

**The counterfactual discriminates on PRECISION, not on being obviously
wrong**, and the first version of that test demanded a 50 million lb miss and
failed. A corn-style September–August window lands at 5,415.7 against 5,388 —
only 27.7 out, because imports ran at a similar rate through late 2024 and
late 2025. It is 0.05 against 27.7, a factor of about 500, which settles it;
but a reader expecting the wrong window to look wildly wrong will not find
that.

### Why the WASDE reader parses the .txt when there is an .xml

ESMIS publishes each release four ways. The XML is the structured one and is
2 MB; the text report is **24 KB**. The revision panel wants a dozen releases,
and twenty-five releases of XML is 50 MB for two numbers apiece.

A fixed-width text parse is normally the fragile choice. Two things make it
the safe one here:

- **Every row carries its own audit.** Beginning stocks + production +
  imports must equal total supply, and total supply less exports and ending
  stocks must equal total disappearance. `_row_ok` refuses a row that fails
  either, so a shifted column shows up as a missing figure rather than as a
  plausible number in the wrong place. The tolerance is 2 million lb, because
  USDA rounds each component independently — Pork 2025 prints 21,744 where
  the subtraction gives 21,743.
- **The XML is the test oracle.** `tests/test_beef_trade.py` parses it
  independently and asserts the text parser agrees figure for figure, over a
  hundred values. The structured file still does the job it is good at; it
  does it in CI instead of on every page load.

Validated against all 25 releases ESMIS serves: zero parse failures, seven
commodities every time.

### Four things in the WASDE reader that look wrong and are not

- **The data starts after the SECOND banner of `=`, not the first.** The
  table opens with a rule under its title, four lines of column headings
  ("Beg- Produc-", "Item inning tion"), then a second rule. Starting at the
  first reads the headings as data; treating the first banner after them as
  the END closes the table before Beef's first row, and the parse then
  returns a report month, no commodities, and nothing resembling an error. It
  reads exactly like a report that has stopped publishing. Cost one debugging
  round.
- **A commodity heading can span two lines, and the join is decided by what
  FOLLOWS it.** The report squeezes out the spaces and wraps: "TotalRed" /
  "Meat5/", "Total" / "Poultry6/". Trailing padding separates a finished
  heading from a fragment today — but `RedMeat& Poultry` is complete on one
  line with no padding, so that tell is wrong on the last commodity in the
  table. A heading is finished when the next non-blank line is indented.
- **The prior month is taken POSITIONALLY, not by month name.** Rows arrive
  oldest first, "Aug" then "Sep". Sorting on the name breaks every December
  to January roll, where the prior month sorts after the current one.
- **`get()` with no year returns the EARLIEST forecast year.** WASDE carries
  the following marketing year from May onward; defaulting to the latest
  would silently switch the page's headline mid-season, from the year being
  revised to one nobody is trading yet.

**The revision is free; the revision history is not.** Each release prints
last month's estimate beside this month's, so the month-over-month change
needs no stored history and no second request — that is why the headline
panel always has it. A longer series is one request per release, so it sits
behind a button, which also stops a hidden tab fetching twelve releases
because somebody opened a different one.

**ESMIS serves 25 releases and OCTOBER 2025 IS NOT ONE OF THEM** — that WASDE
was never published. So the history is about two years deep with a real hole
in it, and the gap is left in rather than bridged. The November 2025 release
proves the point from the other side: its prior-month column is labelled
**"Sep"**, not "Oct", and the parser reads it correctly because it never
assumes the two are adjacent.

### `World total` is a ROW in the ERS file

Summing every `GEOGRAPHY_DESC` double-counts the total by exactly 100%. That
gives a monthly beef export figure around 390 million lb against a true 195 —
wrong by a factor of two and still entirely plausible-looking as a beef trade
number. I made that mistake in the first probe of the file.

The countries sum to USDA's published total with **zero error across all 904
month/flow checks**, so `reconciles()` audits the identity on every load
rather than trusting either side, every helper filters the row explicitly,
and every headline reads USDA's own total rather than a sum. A test asserts
the naive sum is exactly double, so the fixture cannot quietly stop
exercising the trap.

### Five more things that look wrong and are not

- **The projection is seasonal, not `YTD × 12/n`.** It scales realised
  year-to-date by the share of the year those months normally carry, over the
  last five COMPLETE years. Beef imports run heavy in the first quarter, so a
  straight annualisation reads high all spring; exports are nearly flat
  (Jan–Aug is 68% of a normal year against a naive 67%) and barely care. The
  page prints which months are heavy and light for the flow being viewed, so
  a reader can see how much the adjustment is doing.
- **The seasonal band on the chart and the projection use the SAME five
  years.** They are two views of one claim about what a normal year looks
  like. For about an hour the band was six years and the legend still said
  "5-yr".
- **"Required to hit WASDE" and the projection answer different questions and
  are not merged.** The first is arithmetic on USDA's forecast; the second is
  what the year does if it behaves normally. On 2026-10-07 imports needed
  475.9 a month and had been running 534.6 — the pace is 12.3% hot, and the
  projection lands 156 million lb above USDA. That disagreement is the
  information.
- **Most deltas on this page are deliberately NOT coloured.** Imports running
  ahead of forecast is good news for a packer buying 90s and bad news for a
  cow-calf operator, and the page does not know which one is reading it.
  Green and red are kept for a figure against its own year-ago. A zero
  revision prints "unchanged" rather than "0", because USDA leaving a
  forecast alone is an answer and "0" reads as a missing one.
- **The part year in progress is left OFF the annual chart.** A bar covering
  eight months beside twelve-month bars tells a true story wrongly.

### The forecast percentages, and why there are no parentheses

What change USDA is forecasting is the question the WASDE panel exists to
answer, and for a few hours it was answerable only by dividing two tiles in
your head. The year-on-year move is now a tile value in its own right
(`Forecast vs 2025`, **+16.2%** for imports, **-9.2%** for exports), the
month-over-month revision carries its percentage beside the absolute, and the
following calendar year is expressed against this one.

**NO PARENTHESES AROUND A PERCENTAGE.** The first version rendered
`▲ 130 (2.1%)`, which is the one notation this audience cannot be given:
**in USDA's own reports parentheses mean NEGATIVE** — the trap
`letter/sterling.py` and `am_cutout` both document, where `(2.23)` is a $2.23
fall. On a page of USDA figures that reads as a cut to exactly the people
most likely to misread it. A middle dot separates them instead.

**The arrow carries the sign, so no figure after it is signed.** The first
version formatted the percentage with `:+` as well and printed `▼ -0.8%`.
A standalone tile value with no arrow does keep its sign, which is why
`Forecast vs 2025` reads `+16.2%` rather than `16.2%`.

`pct()` returns None rather than 0.0 on a missing or zero base: "USDA is
forecasting no change" and "there is nothing to compare against" are
different answers, and the panel would otherwise print a confident `+0.0%`
where it has nothing. Same rule as `Wasde.revision`.

### The forecast bar that rendered nowhere

`annual_figure` forces `xaxis type="category"` and **that line is
load-bearing.** Plotly type-sniffs an axis, and "2014".."2025" are all
numeric strings, so it builds a LINEAR axis from 2013.5 to 2025.5 — at which
point `"2026F"` has no numeric position and its bar is never drawn.

It is not dropped either, which is what makes it nasty: the trace exists, the
legend entry renders, and the value still stretches the y-axis, so the chart
reserved headroom to 6,592 for a bar nobody could see. Nothing raised. Caught
2026-10-07 by reading `_fullLayout.xaxis._categories` out of the live page
after the bar failed to show in a screenshot — `barNodes` was `[12, 1]`, so
the DOM node had been there all along.

The figure builder is split out of the renderer purely so a test can assert
the axis type without rendering anything.

### Tabs, not a switch, and why that is allowed here

The rule further up this file is that a hidden Streamlit tab is hidden and
not skipped, so a tab is right only when the hidden body is cheap. All three
views read the **same two cached fetches** — one ERS file, one WASDE release
— so the second and third tabs cost rendering and no network at all. The one
expensive thing on the page is behind a button for exactly this reason.

`trade_flows.SCHEMA` and `wasde.SCHEMA` exist because the cache serves shape,
not freshness — the `leverage.SCHEMA` trap. Bump them whenever `load()`,
`history()` or `pace()` changes the shape of what it returns, or the tiles
render "—" with nothing raising.

**`wasde.py` knows nothing about beef and a test asserts it.** It returns
every commodity and attribute in the table, so the next page wanting a WASDE
production or per-capita line imports it rather than growing a second WASDE
reader. That is the `snowflake_db.py`-times-five lesson applied before the
fact instead of after it — and it is what makes "every dashboard carries the
WASDE expectation" cheap to extend to the other twelve.

### The home grid stopped working at thirteen

Thirteen tiles leaves a remainder of one at two, three, four and six per row,
so every candidate width stranded a tile — and five, the only one that
divides it acceptably (5/5/3), is the width the `TILES_PER_ROW` comment had
already rejected on measurement. The grid now **borrows**: when the last row
would hold a single tile, one moves down from the row above, giving 4/4/3/2.
Tiles keep their four-column width. A test pins the arithmetic for every
count from 2 to 40.

## WASDE on Cash Cattle Trade — and why only there

Added 2026-10-07, at the top of the Weekly tab. USDA's quarterly 5-Area steer
price forecast, the calendar-year total, the month's revision and each
quarter marked actual or projected.

**IT IS THIS PAGE'S OWN SERIES, NOT A RELATED INDICATOR PLACED NEARBY.**
WASDE's footnote defines its steer price as *"5-Area, Direct, Total all
grades"* — which is what LM_CT150 reports and what the tiles beneath it
chart. `wasde.STEER_PRICE_BASIS` carries that footnote around rather than
paraphrasing it, because "the USDA steer price" on its own would not
establish the comparison.

What it adds that nothing else on the portal does: USDA **cut the 2026
forecast from $245.35 to $237.35 in one month**, and the 2027 from $249 to
$238. An $8 and an $11 revision, invisible here until now.

### WASDE HAS NOTHING FOR THE OTHER ELEVEN PAGES, and that is checked

Searched the whole September 2026 release on 2026-10-07: **zero** occurrences
of *feeder*, *cutout*, *cow*, *heifer*, *on feed* or *placement*. The only
cattle price in WASDE is the steer line above, and the only cattle quantity
is beef production.

So there is no WASDE panel for CME Feeder Cattle Index, Beef Cutout, US Cow
Herd, Cattle on Feed, Livestock Inventory, Beef Trimmings, Mexican Feeder
Imports or Backgrounding Crush — not an oversight, and **not worth probing
again**. Adding one would mean showing a loosely-related number, which is
worse than showing none. Seasonal Futures already marks WASDE release dates
as chart vlines, which is the right treatment there.

Two that would work and were not asked for: **Cattle Weights** (beef
production, onto the Beef Production tab) and **Fed Cattle Crush** (the same
steer price, against the futures-derived sale price).

### WASDE PRINTS BEEF PRODUCTION TWICE AND THE TWO DISAGREE

The quarterly table (page 31) says **24,877** for 2026; the meats
supply-and-use table (page 32) says **24,945**. The gap is farm production —
**68 million lb**, the same in both years on file.

Page 31 is *"Commercial production for red meats"*; page 32 is *"Total
including farm production"*. Both are right. Two portal pages reading
different tables would quote different US beef production and neither would
raise — the letter-versus-dashboard failure this file records twice already,
waiting on a third route. `tests/test_beef_trade.py` pins the 68.

### `wasde.py` lives at the REPO ROOT, and must stay one file

It moved out of `apps/beef_trade/` the moment a second page wanted it. Both
pages put the repo root on `sys.path` and `import wasde`, the convention
`apps/weekly_reports/app.py` already uses to reach `letter`.

**Do not copy it next to the page that needs it.** Python caches modules by
NAME, so a second `wasde.py` under an app directory would mean whichever page
loaded first decided which copy every other page got — the
`snowflake_db`-times-five problem at the top of this file, which this module
was written to avoid rather than to join. A test asserts `rglob("wasde.py")`
returns exactly one path.

### Four things in the quarterly parser that look wrong and are not

- **The annual rows sit at the LEFT MARGIN, like a year heading.** Quarter
  rows are indented (`     III*`); `AugProj.` and `SepProj.` are not. The
  first period regex required leading whitespace and silently dropped every
  annual row — the table parsed, all four quarters were correct, and
  `annual()` returned None with nothing raising. Those rows are the only ones
  the panel wants.
- **A forecast year has no "Annual" row at all.** It prints `<Mon>Proj.`
  twice, last month's and this month's, so the newest Proj. row IS the annual
  forecast and the month-over-month revision is free — the same arrangement
  the meats table uses. Reaching for "Annual" on the current year returns
  nothing.
- **`quarter_number` is a MAP, not the length of the numeral.** `len("III")`
  is 3 and right; `len("IV")` is 2 and labels the fourth quarter "Q2". That
  shipped for about ten minutes and rendered the year as Q1, Q2, Q3, Q2.
- **Two tables share printed page 31**, so the prices table has no page
  header above it and its month comes from the first header anywhere in the
  document. Tables are found by TITLE, never by page.

### The audit, because a price table has no accounting identity

The meats table has two identities per row and refuses a row that fails
either. A price table has none, so a shifted column there would be invisible
from the row alone.

The substitute: USDA's footnote says the annual is a simple average of months
and each quarter is three months, so **the annual must equal the mean of its
four quarters**. For September 2026 that is 237.3525 against a printed
237.35. `reconciles()` checks it and the panel prints a warning if it ever
fails.

`ok` is **None, not False**, when fewer than four quarters are published —
which is every forecast year before the following May. Refusing to judge is
different from judging it wrong, and a banner that fires for eight months of
every year is one nobody reads in the month it matters.

### Placement and caching

**The panel renders ABOVE the LMR outage guard**, the same four-line shape as
the Saturday Slaughter view and the morning cutout panel. WASDE comes from
ESMIS over a different host; below the guard the whole thing would vanish on
exactly the days a reader most wants a reference price. A test asserts the
call precedes `if not load_ok:`.

`fetch_wasde_steer` is cached six hours and keyed on `wasde.SCHEMA` — the
cache serves shape, not freshness, and never notices that `wasde.py` changed.
It also flattens the dataclass to a plain dict before caching, because
`st.cache_data` pickles what it stores and a cached dataclass goes stale
against its own class the moment the module is edited.

**A local dev server will not pick up an edit to `wasde.py` either.** Seen
while building this: the page raised `AttributeError: module 'wasde' has no
attribute 'quarter_number'` against code where the attribute plainly existed
and the tests passed. The server had imported the module before the function
was added, and a rerun reuses `sys.modules`. Restart the server; on the
deployed app, reboot. Same cause as the entry further up this file.

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

### Two image buttons, because texting and HubSpot want opposite things

Added 2026-10-06. The preview toolbar has **Save pages (texting)** and **Save
one image (HubSpot)** beside Print.

- **Texting** needs one PNG per page. A phone fits an image to the message
  bubble width, so the 2026-10-02 afternoon letter at 1632x6336 — about 1:3.9
  — squeezed 8.5pt body text to roughly ONE PIXEL tall, and MMS re-compressed
  on top of that. Each page is stamped *Page N of M* in the frame's sage,
  in a reserved strip, because the client sees pixels and never the filename
  and MMS guarantees no ordering.
- **HubSpot** needs exactly one image. Dragging a set of page images into the
  email editor does not work; it takes a single asset. That export returns
  before any of the splitting work — no stamp, no cut-finding, no page suffix
  on the filename.

**ONE CAPTURE, TWO SAVE PATHS**, and a test asserts `html2canvas(el, {`
appears once. Capturing separately would let the two exports drift into
different margins or line breaks, which nobody would notice until a client
had both.

Verified in a browser on a real three-page letter: the HubSpot button gives
one 1632x6336 PNG, the texting button three stamped pages.

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

### The Cattle Market Rundown Slide tab

Added 2026-10-06. The letter page is now TWO TABS -- `Letter` and `Cattle
Market Rundown Slide` -- and the second builds the one-pager Ross had been
typing into PowerPoint by hand each week, downloadable as a 16:9 `.pptx`.
`letter/rundown.py` formats and writes it; the tab body is in
`apps/weekly_reports/app.py`.

**IT BUILDS FROM `ctx`, NEVER FROM ITS OWN FETCHES.** `rundown.rows()` takes
the ctx `gather()` already assembled. The module has no `requests`, no
`sources` import and no database handle, and a test asserts it **by AST**
rather than by grep -- the first version of that test failed on the module's
own docstring explaining the rule. The reason is the failure recorded twice
above: the letter and a dashboard quoting the same figure and disagreeing,
each defensible, neither raising. A slide with its own fetches would be a
third number in that argument.

**The tab split meant hoisting four statements.** `_PRINT_STYLE`,
`_PRINT_BUTTON`, `_IMAGE_SCRIPT` and `_with_print_button` sat in the middle of
the region that moved under `with tab_letter:`, and
`tests/test_print_preview.py` pulls them off the MODULE by AST -- indenting
them would have broken 28 tests. They are lifted above the split and stay at
top level. Every multi-line string in the file lives inside that block, which
is the only reason indenting the rest was safe; check that again before moving
the split.

**A hidden tab still executes**, so writing the `.pptx` is memoised on the
slide's own rows (`_rundown_pptx`). Without it the page writes a PowerPoint
file on every keystroke in the commentary boxes.

### Slide 7, and the Sterling Profit Tracker

Added 2026-10-06. `letter/sterling.py` fetches John Nalivka's weekly PDF from
the mailbox and parses it; `rundown.build_sterling_pptx` renders deck slide 7
from it. One PDF carries everything on that slide: the feedlot and packer
margins, the weekly slaughter table with Sterling's own plant capacity
utilisation, and the annual projections.

**"Cattle Market Rundown" IS A SECTION NAME, NOT A SLIDE.** It titles five of
the thirteen slides in the weekly deck -- 3, 4, 7, 11 and 12. Slide 3 is the
bulleted rundown; slide 7 is this one. An earlier pass here conflated them and
criticised figures on slide 7 as hand-typed when they were a pasted screenshot
(`ppt/media/image9.png`). Check the slide number before attributing anything.

**THE DATA IS SOMEONE ELSE'S AND THAT CHANGES THE RULES.** Sterling is a paid
subscription and the PDF says "considered proprietary material".

- **Reproduce, never recompute.** AMS publishes its own weekly split and it
  disagrees -- for w/e 2026-09-26, Steers/Heifers 382,000 and Cows/Bulls
  102,000 against Sterling's 395,428 and 82,280. Sterling's figures do not
  always reconcile against each other either, and they are still printed
  exactly. Substituting AMS would produce a table that is neither source's.
  A test asserts `sterling.py` never imports the USDA fetchers.
- **The attribution is part of the slide.** "Margins compiled by Sterling
  Marketing, Inc." is written unconditionally.
- **The test fixture is SYNTHETIC.** This repo is public. The fixture copies
  the tracker's layout and none of its numbers; committing a real one would
  publish Sterling's product.

**AMS DOES NOT HAVE THESE FIGURES AT ALL**, which is worth not re-deriving:
201 weeks of *Actual Slaughter Under Federal Inspection* (3658, section
`Report FIS Cattle`, back to 2022-11-19) contain none of the slide's class
figures -- not 395,428, 82,280, 447,720, 451,300, 84,422 or 76,518. The AMS
estimates in 3208 `/Report Livestock Class` are rounded to thousands and sum
to the SJ_LS712 total exactly; Sterling's do not sum to their own total,
being 6,292 head short. Different methodology, not a defect.

**What it fixes.** The hand-typed slide for 2026-09-28 read "Packer Margins -
Last week- 117.37" where the tracker says **137.37** -- one digit, in a client
deck, in the row directly above Sterling's own attribution line.

Four parsing traps, each with a test:

- **Take the LAST FOUR numeric tokens on a row, never the first.** Labels
  carry footnote markers and ranges -- "Beef Cutout 1 ($ / cwt)", "Cow-Calf
  Margin 3($ / cow)", "Feeder Steer (Ok City 750-800 lb...)" -- and a
  leading-token rule reads a footnote as a price.
- **A row yielding fewer than four values returns None, not a padded list.**
  Padding still renders and shifts every column silently.
- **Parentheses are negative.** ($335.15) is a loss. Reading it as positive
  turns the worst feedlot margin in two years into a profit.
- **The annual block repeats two labels** ("Feedlot Margin", "Packer Margin")
  and its header line carries FIVE four-digit years, because the as-of date
  contains one. Both are parsed from the block's own section.

Sterling's abbreviations are kept verbatim -- they write "Sept.", which no
locale's strptime accepts and which `strftime('%b')` would render "Sep".
Reformatting their header is the same class of mistake as recomputing their
figures.

**The tables are generated as real PowerPoint tables**, not the pasted
screenshots the hand-built slide uses. `image9.png` is 603x102 stretched to
6.28in, which is why it is soft on a projector; a native table stays sharp and
keeps the figures selectable. Geometry is measured off the real deck, so a
generated slide drops in without nudging.

**The mailbox fetch is cached for an hour**, because the tab it lives in runs
whether or not it is on screen. Sterling publishes roughly weekly, so an hour
is generous -- the same deal the Saturday Slaughter view takes for its MARS
fetch.

### The mailbox is connected — that entry was stale

The "In flight" note below says Azure admin consent is pending for "JSA Letter
- email read", blocking the four subscription digests. **It was granted at
some point before 2026-10-06**: `mailbox.token(interactive=False)` returns a
token silently and a Graph search against `jnalivka@fmtc.com` returns a
hundred messages. Nothing needed changing in the code. Two consequences: the
headline candidate panel has the digests it was documented as lacking, and the
Sterling fetch above is possible at all.

One Graph quirk, since it costs a round trip to rediscover: `$filter` on
`from/emailAddress/address` returns **400 InefficientFilter**. Use
`$search: "from:<addr> <subject words>"` instead. `$skip` is not supported
alongside `$search` either -- it returns zero rows rather than an error.

### What the slide fixed, and the one number that keeps moving

Four figures on the hand-typed 2026-10-05 deck were wrong, and all four were
wrong in ways nothing would ever have flagged:

| | typed | actual |
|---|---|---|
| carcass weights | "as of **8/19/26**" | week ending **9/19/26** |
| Select 5-day | 358.13 | 358.14 (358.136, truncated not rounded) |
| Slaughter YTD | -7.7% | **-7.5%** |
| Beef Production YTD | -5.3% | **-5.2%** |

The month typo survived because AMS 3658 runs about a fortnight behind, so a
four-week-old weight looks no different from a two-week-old one; the slide now
PRINTS the week ending from the data. Both YTD rates are read straight off
USDA's own Change rows -- they are not our arithmetic -- and the typed pair had
been carried over from the previous week's deck.

**The Feeder Index is the one that is not a fix, and the first explanation of
it here was wrong.** This section said 337.79 was a mid-afternoon reading of
the 10/05 row that firmed to 337.22 overnight. It was not. `fci_daily` has
**09/25 at 337.794 and 10/05 at 337.218**: the 337.79 on the hand-typed slide
is the PREVIOUS DECK'S figure, carried forward a week and a half, exactly like
the two YTD rates above it.

The firming-up effect is real and separate -- the 10/05 row read 337.66 in the
morning of 10/06 and 337.22 that afternoon, because the headline index date is
the first business day after CME's last published file and auctions are still
reporting into it. Both things are true; attributing the stale figure to the
live effect is what went wrong, and it went into a shipped caption before
anyone checked the series. **Check `fci_daily` before explaining a difference
in this number.**

### The 5-day average changed, and it changed the LETTER too

`sources.fetch_cutout` computed `avg5` as `tail(5)` -- the trailing five
sessions INCLUDING the one being reported. The slide has always used the five
sessions BEFORE it. For 2026-10-05 that is Choice **378.94** against
**379.38**, and Select 358.20 against 358.14.

Ross's convention won and `sources.py` now uses `iloc[-6:-1]`, so **the
letter's own 5-day average line moved** -- it prints in two places in
`render.py`. Neither convention is wrong in isolation, which is exactly why the
disagreement went unnoticed; the excluding one is the better of the two because
it is a fixed benchmark the new print is read against rather than a window that
chases it. It needs SIX rows now, not five. `tests/test_rundown.py` pins the
window so it cannot drift back.

### Two things in the slide writer that looked fine and were not

Both rendered without complaint and both were only visible in a picture of the
slide, which is the argument for the arithmetic assertions now in
`tests/test_rundown.py`.

- **`para.level` alone produces no bullet and no indent.** A level selects a
  style from the layout's list styles and a blank-layout text box has none, so
  the first build was flat, unbulleted text that still reported the right
  `level` back through python-pptx. `_bullet()` writes `buChar` and the margins
  explicitly, which also makes it render the same in Google Slides.
- **The text printed through the logo.** At 20/17/15/14pt the eighteen rows ran
  to 6.60in and the logo sat at 6.55in, so the last line crossed the wordmark.
  Sizes are now 19/16/14/13 with the logo at 6.80in, and the test does the
  collision arithmetic from `text_height_in()` rather than rendering anything.

**DO NOT VERIFY A GENERATED DECK BY DRIVING POWERPOINT.** `win32com`'s
`Dispatch("PowerPoint.Application")` attaches to the instance Ross already has
open -- `WithWindow=False` does not isolate it -- and `app.Quit()` closed an
unsaved presentation he was working in on 2026-10-06. It was not recoverable:
no AutoRecover entry, nothing in `UnsavedFiles`, no temp artefact. Read the
file's XML instead, which is what caught the missing `buChar` anyway.

**The slide needs no new secret** and costs no HTTP. `python-pptx` is the one
new dependency, added to `requirements.txt`; it is pip-installable on Community
Cloud, which is not subject to the Snowflake Anaconda channel constraint.

**Nothing rebuilds it at 3pm.** Community Cloud has no scheduler, so the tab is
built when it is opened and `rundown.freshness()` says out loud which session's
cutout it is holding -- a previous session's is a perfectly good number and
looks exactly like today's. It deliberately does NOT cry stale at a weekend
or before the PM release, because a banner that fires every Saturday is one
nobody reads on the Monday it matters.

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
- **Azure admin consent LANDED** for "JSA Letter - email read" (delegated
  `Mail.Read`), some time before 2026-10-06. This bullet said it was pending
  for a fortnight after it was not. `mailbox.token(interactive=False)` returns
  a token silently and Graph answers for `jnalivka@fmtc.com`; no code change
  was needed, exactly as predicted. The headline candidate panel therefore has
  its four subscription digests, and the Sterling slide 7 work above depends
  on it. Back-filling the letters published before 2026-09-24 from Sent Items
  is now possible and has not been done.
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
