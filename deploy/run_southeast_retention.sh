#!/usr/bin/env bash
# run_southeast_retention.sh — refresh the US Cow Herd page's southeastern
# retention series, invoked by cron on the Droplet: /opt/livestock-portal is a
# git clone of this repo.
#
# WHY A WRAPPER AND NOT JUST A PYTHON LINE IN THE CRONTAB. The Snowflake block
# and MARS_API_KEY on that host live in a .env FILE beside the code, not in
# root's environment -- the convention beef-trimmings-dashboard's
# deploy/run_fetch.sh has used there since 2026-10-04. cron gives a job almost
# no environment, so a crontab line calling python directly gets no
# credentials: refresh_southeast.py would exit 1 on every run, or worse find
# USE_SNOWFLAKE unset and refuse. Sourcing .env is the whole reason this file
# exists.
#
# Deliberately the same shape as run_mx_auction.sh and run_am_cutout.sh --
# same /opt/<repo> clone, same .venv, same flock, same logs/ directory and
# 30-day prune. The droplet's crontab shows ten jobs on exactly this pattern.
#
# IDEMPOTENT, so the schedule can be blunt. refresh_southeast.py skips any
# year whose ratio and sample have not moved, so a catch-up run costs seven
# MARS fetches and writes nothing at all. There is no holiday calendar to
# maintain and none to get wrong.
set -uo pipefail

APP_DIR="${APP_DIR:-/opt/livestock-portal}"
VENV="$APP_DIR/.venv"
LOG_DIR="$APP_DIR/logs"

# cd BEFORE creating anything, so a wrong APP_DIR fails instead of scattering a
# logs/ directory somewhere it does not belong.
cd "$APP_DIR" || { echo "APP_DIR $APP_DIR missing" >&2; exit 1; }

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/southeast_retention_$(date +%Y%m%d_%H%M%S).log"

# THE MISSING-flock CASE HAS TO BE HANDLED EXPLICITLY. `if ! flock -n 9` reads
# as "could not take the lock" when flock is simply absent -- command-not-found
# is 127, `!` makes that true, and the job exits 0 having done nothing, every
# run, looking healthy.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOG_DIR/.southeast_retention.lock"
    if ! flock -n 9; then
        echo "$(date -Is) another run is in progress — skipping" >>"$LOG"
        exit 0
    fi
else
    echo "$(date -Is) flock not available — running without a lock" >&2
fi

if [ ! -f .env ]; then
    echo "$(date -Is) no .env in $APP_DIR — nothing would be recorded" >&2
    exit 1
fi
# SNOWFLAKE_SCHEMA is irrelevant whatever .env holds: refresh_southeast.py
# names JSA.CME_FEEDER_CATTLE.SOUTHEAST_RETENTION in full and takes no part in
# the nine-module collision CLAUDE.md documents at the top of this repo.
set -a; source .env; set +a

rc=0
{
    echo "=== southeast retention start $(date -Is) ==="
    "$VENV/bin/python3" deploy/refresh_southeast.py
    rc=$?
    echo "=== southeast retention finished $(date -Is) rc=$rc ==="
} >>"$LOG" 2>&1

# Re-surface a failure on stderr and EXIT NON-ZERO, because that is what
# /opt/alerting/cron-alert keys on -- the crontab's own header says this box
# has no MAILTO and no MTA, so plain cron mails nothing and a bare entry fails
# SILENTLY. The exit code is the entire alerting contract here.
if [ "$rc" -ne 0 ]; then
    echo "southeast_retention failed rc=$rc — see $LOG" >&2
    tail -n 10 "$LOG" >&2
fi

find "$LOG_DIR" -name 'southeast_retention_*.log' -mtime +30 -delete 2>/dev/null || true

exit "$rc"
