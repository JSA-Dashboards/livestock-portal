#!/usr/bin/env bash
# Install the Frozen 90s import cron on the droplet. Run ON the droplet, as root.
#
#   bash install_import_cow90_cron.sh                     # report, install if safe
#   bash install_import_cow90_cron.sh --check             # report only, change nothing
#   bash install_import_cow90_cron.sh --replace-existing  # also remove the OLD job's line
#
# THIS JOB ALREADY EXISTS ON THIS HOST IN SOME FORM. Until 2026-10-07 the
# fetching half of the Beef Trimmings import series lived only here, in a
# script that was in no repository -- the page carried the reader, nothing
# carried the writer. This installs the versioned replacement.
#
# So the dangerous outcome is not a failed install, it is TWO WRITERS on one
# table: the old unversioned script and this one, both rewriting
# JSA.BEEF_TRIMMINGS.IMPORT_COW90 on different schedules. This script will not
# create that silently. It finds candidate old lines, prints them, and refuses
# to install until you either remove them yourself or pass --replace-existing.

set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/livestock-portal.git"
DEST="${DEST:-/opt/livestock-portal}"
LOG="${LOG:-/var/log/import_cow90.log}"
PY="$DEST/.venv/bin/python"

# DAILY, AND THAT IS THE WHOLE POINT OF THIS CHANGE. The old schedule was
# weekly against a weekly publication, which leaves no slack: USDA posted the
# 2026-10-02 report after the 10-05 run, so the page sat on 09-25 data for a
# week with nothing wrong anywhere and nothing to alert on. A daily sweep costs
# one request; the write is a full-series rewrite, so a day with no new report
# rewrites the same rows and changes nothing but FETCHED_AT.
CRON_LINE="15 12 * * * cd $DEST && .venv/bin/python scripts/bank_import_cow90.py >> $LOG"
CRON_TAG="scripts/bank_import_cow90.py"

# Anything that looks like the OLD job. Deliberately broad -- a line this
# misses becomes a second writer, which is worse than a line it names wrongly
# and you decline to remove.
OLD_PATTERN='cow90|COW90|import_cow90|trimmings|LS421|2823'

MODE=install
[ "${1:-}" = "--check" ] && MODE=check
[ "${1:-}" = "--replace-existing" ] && MODE=replace

say() { printf '  %s\n' "$*"; }

echo "== what is already here =="
say "host:     $(hostname)"
say "date:     $(date -u '+%Y-%m-%d %H:%M:%SZ') (UTC)"
say "checkout: $([ -d "$DEST/.git" ] && echo "$DEST" || echo 'absent')"
echo "  existing crontab:"
crontab -l 2>/dev/null | sed 's/^/    /' || echo "    (none)"

MINE=0
crontab -l 2>/dev/null | grep -qF "$CRON_TAG" && MINE=1
OLD_LINES="$(crontab -l 2>/dev/null | grep -vF "$CRON_TAG" | grep -E "$OLD_PATTERN" || true)"

echo
echo "== the old unversioned job =="
if [ -n "$OLD_LINES" ]; then
  echo "  candidate lines for the job this REPLACES:"
  printf '%s\n' "$OLD_LINES" | sed 's/^/    /'
else
  say "none found matching: $OLD_PATTERN"
  say "if the old job is scheduled some other way, stop and remove it by hand --"
  say "two writers on one table is the one outcome worth avoiding here."
fi

# -- credentials, by presence only; never print a secret ----------------------
echo
echo "== environment =="
MISSING=""
for v in USE_SNOWFLAKE SNOWFLAKE_ACCOUNT SNOWFLAKE_USER SNOWFLAKE_ROLE \
         SNOWFLAKE_WAREHOUSE SNOWFLAKE_DATABASE MARS_API_KEY; do
  if [ -n "${!v:-}" ]; then say "$v = set"; else say "$v = MISSING"; MISSING="$MISSING $v"; fi
done
if [ -n "${SNOWFLAKE_PASSWORD:-}" ] || [ -n "${SNOWFLAKE_PRIVATE_KEY:-}" ]; then
  say "credential = set"
else
  say "credential = MISSING (need SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY)"
  MISSING="$MISSING SNOWFLAKE_PASSWORD|SNOWFLAKE_PRIVATE_KEY"
fi
# NOT SNOWFLAKE_SCHEMA -- import_cow90 names its table in full, and CLAUDE.md
# records that setting it breaks nine modules that each default it themselves.
#
# THE ROLE MATTERS HERE AND NOT ONLY ITS PRESENCE. DELETE/INSERT/UPDATE on
# JSA.BEEF_TRIMMINGS.IMPORT_COW90 belong to JSA_EDITOR (checked 2026-10-07);
# SELECT alone is held by JSA_ANALYST, BEEF_TRIMMINGS_ROLE and
# LIVESTOCK_PORTAL_ROLE. A read-only role installs fine and then fails every
# day forever, so the real run below is the check that matters -- it writes or
# this script stops before touching cron.
say "SNOWFLAKE_ROLE must be able to DELETE+INSERT on JSA.BEEF_TRIMMINGS (JSA_EDITOR)"

if [ "$MODE" = "check" ]; then
  echo
  echo "== --check only, nothing changed =="
  exit 0
fi

if [ -n "$MISSING" ]; then
  echo
  echo "STOPPING: missing env:$MISSING" >&2
  echo "Nothing was changed." >&2
  exit 1
fi

if [ -n "$OLD_LINES" ] && [ "$MODE" != "replace" ]; then
  echo
  echo "STOPPING: an older job for this table is still scheduled." >&2
  echo "Re-run with --replace-existing to remove the lines above, or remove" >&2
  echo "them by hand first. Installing now would leave TWO writers." >&2
  echo "Nothing was changed." >&2
  exit 1
fi

# -- checkout -----------------------------------------------------------------
echo
echo "== code =="
if [ -d "$DEST/.git" ]; then
  say "pulling $DEST"; git -C "$DEST" pull --ff-only
else
  say "cloning into $DEST"; git clone --depth 50 "$REPO_URL" "$DEST"
fi
if [ ! -x "$PY" ]; then
  say "creating venv"; python3 -m venv "$DEST/.venv"
fi
say "installing deps"
"$DEST/.venv/bin/pip" install --quiet --upgrade \
  requests pypdf pandas snowflake-connector-python

# -- prove it works BEFORE installing the schedule ----------------------------
echo
echo "== dry run (writes nothing) =="
"$PY" "$DEST/scripts/bank_import_cow90.py" --dry-run

echo
echo "== first real run (this is also the write-permission check) =="
"$PY" "$DEST/scripts/bank_import_cow90.py"

# -- crontab ------------------------------------------------------------------
echo
echo "== cron =="
if [ "$MODE" = "replace" ] && [ -n "$OLD_LINES" ]; then
  say "removing the old job's line(s)"
  crontab -l 2>/dev/null | grep -vE "$OLD_PATTERN" | crontab - || true
fi
if [ "$MINE" = "1" ]; then
  say "my line already present, leaving it alone"
else
  say "appending"
  { crontab -l 2>/dev/null || true; \
    echo "# USDA NW_LS421 Frozen 90s imports -> JSA.BEEF_TRIMMINGS.IMPORT_COW90"; \
    echo "$CRON_LINE"; } | crontab -
fi
touch "$LOG"

echo
echo "== done =="
say "log:   $LOG"
say "table: JSA.BEEF_TRIMMINGS.IMPORT_COW90"
echo "  resulting crontab:"
crontab -l 2>/dev/null | sed 's/^/    /'
