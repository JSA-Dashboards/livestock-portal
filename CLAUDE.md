# JSA Livestock Portal

A single Streamlit process (`Home.py`) bundling ten livestock dashboards
under `apps/`: CME Feeder Cattle Index, Seasonal Futures & Spreads, Cattle on
Feed, US Cow Herd, Mexican Feeder Imports, Cattle Weights, Beef Cutout, Beef
Trimmings, Livestock Inventory, Cash Cattle Trade.

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
minutes; the "not found" page partway through provisioning is normal.

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

A related trap: `snowflake_db.py` now exists **three times** — under
`apps/cme_feeder_cattle/`, `apps/us_cow_herd/` and
`apps/mexican_feeder_imports/`. Each page does
`sys.path.insert(0, <its own dir>)`, but Python caches modules by NAME in
`sys.modules`, so whichever page loads first wins and the others get its copy.
The three are equivalent today, which is the only reason this works. Do not let
them drift: a change to one must be made to all three, or a page will silently
run against another page's connection logic.

The same applies to `app.py` for CME Feeder Cattle Index, which also lives in
the cme-feeder-cattle-index repo. The two are deliberately NOT identical (the
standalone calls `set_page_config`, loads `.env`, and uses its own palette), so
diff before copying — but a layout or logic fix belongs in both.

## Deployment facts

- Branch `master`, main file `Home.py`, Python 3.14
- Live at `jsa-livestock.streamlit.app`
- Hosted in the personal Streamlit workspace, not the org one. An attempt to
  move it to the org workspace on 2026-09-05 failed for reasons never
  established, and was reverted. Do not retry casually — it takes all ten
  dashboards down.
