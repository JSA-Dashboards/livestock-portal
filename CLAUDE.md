# JSA Livestock Portal

A single Streamlit process (`Home.py`) bundling eight livestock dashboards
under `apps/`: CME Feeder Cattle Index, Seasonal Futures & Spreads, Cattle on
Feed, Beef Weight, Beef Cutout, Beef Trimmings, Livestock Inventory, Cash
Cattle Trade.

## Never set SNOWFLAKE_SCHEMA in this app's secrets

Three bundled modules read Snowflake and each defaults `SNOWFLAKE_SCHEMA` to
the schema **it** owns:

| module | its default |
|---|---|
| `apps/beef_weight/nass_cache_client.py` | `NASS_CACHE` |
| `apps/livestock_inventory/nass_cache_client.py` | `NASS_CACHE` |
| `apps/cme_feeder_cattle/snowflake_db.py` | `CME_FEEDER_CATTLE` |

Setting it to any one value overrides all three and silently breaks the others.
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

Both API keys previously had hardcoded fallbacks committed to this public repo.
Those were removed 2026-09-06 — a missing key now fails loudly, which is the
intent. Do not reintroduce a literal.

## Apps sharing code do not share secrets

Beef Weight, Beef Trimmings, Livestock Inventory, Cattle on Feed, CME Feeder
Cattle Index and Livestock Seasonal all also exist as standalone repos running
the same files. Each deployment has its own secrets. Removing a secret here
does nothing to the standalone app — and vice versa. Check both.

## Deployment facts

- Branch `master`, main file `Home.py`, Python 3.14
- Live at `jsa-livestock.streamlit.app`
- Hosted in the personal Streamlit workspace, not the org one. An attempt to
  move it to the org workspace on 2026-09-05 failed for reasons never
  established, and was reverted. Do not retry casually — it takes eight
  dashboards down.
