#!/usr/bin/env bash
# Install the Mexican auction-price cron on the droplet. Run ON the droplet, as root.
#
#   bash install_mx_auction_cron.sh            # install
#   bash install_mx_auction_cron.sh --check    # report only, change nothing
#
# IDEMPOTENT THROUGHOUT, and it shares the checkout and venv the morning-cutout
# job already uses. An existing checkout is pulled rather than re-cloned, and
# the crontab is read, appended to and written back -- never replaced -- so the
# am_cutout and beef-trimmings jobs on this host survive.
#
# It will NOT invent Snowflake credentials. If the environment is not already
# set up it says exactly what is missing and stops before touching cron,
# because a job installed without credentials fails silently once a day forever.

set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/livestock-portal.git"
DEST="${DEST:-/opt/livestock-portal}"
LOG="${LOG:-/var/log/mx_auction.log}"
PY="$DEST/.venv/bin/python"

# TWICE A DAY, AT NO PARTICULAR TIME, AND THAT IS THE DESIGN.
# mexicoganadero.com keeps the current sale and the previous one and nothing
# else -- there is no archive and no date parameter -- so the only question is
# whether a run lands before a sale rolls off. Tamaulipas sells about weekly,
# so two sales is roughly two weeks of slack and a daily sweep has ample room.
# The second run is insurance against one failing, not precision.
#
# Both pages are fetched every run and the write is idempotent, so a run that
# finds nothing new costs two small requests and writes nothing. That is what
# lets this be a blunt schedule instead of a guess at when an auction posts,
# and it means no DST arithmetic and no Mexican holiday calendar to maintain.
CRON_LINE="30 13,23 * * * cd $DEST && .venv/bin/python scripts/mx_auction.py >> $LOG"
CRON_TAG="scripts/mx_auction.py"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '  %s\n' "$*"; }

echo "== what is already here =="
say "host:    $(hostname)"
say "date:    $(date -u '+%Y-%m-%d %H:%M:%SZ') (UTC)"
say "checkout: $([ -d "$DEST/.git" ] && echo "$DEST" || echo 'absent')"
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "cron:    already installed"
else
  say "cron:    not installed"
fi
echo "  existing crontab:"
crontab -l 2>/dev/null | sed 's/^/    /' || echo "    (none)"

# -- credentials, by presence only; never print a secret ----------------------
echo
echo "== snowflake environment =="
MISSING=""
for v in USE_SNOWFLAKE SNOWFLAKE_ACCOUNT SNOWFLAKE_USER SNOWFLAKE_ROLE \
         SNOWFLAKE_WAREHOUSE SNOWFLAKE_DATABASE; do
  if [ -n "${!v:-}" ]; then say "$v = set"; else say "$v = MISSING"; MISSING="$MISSING $v"; fi
done
if [ -n "${SNOWFLAKE_PASSWORD:-}" ] || [ -n "${SNOWFLAKE_PRIVATE_KEY:-}" ]; then
  say "credential = set"
else
  say "credential = MISSING (need SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY)"
  MISSING="$MISSING SNOWFLAKE_PASSWORD|SNOWFLAKE_PRIVATE_KEY"
fi
# SNOWFLAKE_SCHEMA is deliberately absent from that list. mx_auction.py names
# its table in full, so it needs none -- and CLAUDE.md records that setting it
# breaks nine other modules that each default it to the schema they own.

if [ "$CHECK_ONLY" = "1" ]; then
  echo
  echo "== --check only, nothing changed =="
  exit 0
fi

if [ -n "$MISSING" ]; then
  echo
  echo "STOPPING: missing env:$MISSING" >&2
  echo "Export these (the same block the am_cutout job uses) and re-run." >&2
  echo "Nothing was changed." >&2
  exit 1
fi

# -- checkout -----------------------------------------------------------------
echo
echo "== code =="
if [ -d "$DEST/.git" ]; then
  say "pulling $DEST"
  git -C "$DEST" pull --ff-only
else
  say "cloning into $DEST"
  git clone --depth 50 "$REPO_URL" "$DEST"
fi

if [ ! -x "$PY" ]; then
  say "creating venv"
  python3 -m venv "$DEST/.venv"
fi
# The same list the am_cutout installer uses, because the venv is shared. Only
# requests and the connector are needed here; installing the pair's full set
# keeps one environment rather than two that can drift.
say "installing deps"
"$DEST/.venv/bin/pip" install --quiet --upgrade \
  requests pypdf pandas snowflake-connector-python

# -- prove it works BEFORE installing the schedule ----------------------------
echo
echo "== dry run (writes nothing) =="
"$PY" "$DEST/scripts/mx_auction.py" --dry-run

echo
echo "== first real run =="
"$PY" "$DEST/scripts/mx_auction.py"

# -- crontab: append, never replace -------------------------------------------
echo
echo "== cron =="
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "already present, leaving it alone"
else
  say "appending"
  { crontab -l 2>/dev/null || true; \
    echo "# Mexican auction prices -> JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES"; \
    echo "$CRON_LINE"; } | crontab -
fi
touch "$LOG"

echo
echo "== done =="
say "log:  $LOG"
say "table: JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES"
say "HISTORY ACCRUES FROM NOW -- the site keeps two sales and cannot be backfilled."
