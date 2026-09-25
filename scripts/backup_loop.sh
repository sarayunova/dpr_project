#!/bin/sh
# Scheduled backups -- the `backup` service in docker-compose.yml runs this.
# docs/07_non_functional_requirements.md requires backups; the default
# mechanism (pending the user's confirmation) is a scheduled pg_dump.
#
# Each cycle:
#   1. pg_dump (custom format, restorable with pg_restore) to
#      /backups/db/dpr_monitor_<UTC timestamp>.dump
#   2. mirror /uploads (the original PDFs -- system of record) into
#      /backups/uploads. Stored PDFs are content-addressed and never
#      modified, so copying only files not already present is a complete
#      incremental mirror.
#   3. delete database dumps older than BACKUP_KEEP_DAYS. Mirrored PDFs
#      are never deleted (retention is indefinite).
set -eu

INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"

mkdir -p /backups/db /backups/uploads

while true; do
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    target="/backups/db/dpr_monitor_${stamp}.dump"

    # Write to a temp name first so a failed/partial dump never looks like
    # a good backup.
    if pg_dump --format=custom --file="${target}.partial"; then
        mv "${target}.partial" "${target}"
        echo "[backup] ${stamp}: wrote ${target}"
    else
        rm -f "${target}.partial"
        echo "[backup] ${stamp}: pg_dump FAILED" >&2
    fi

    cp -Rn /uploads/. /backups/uploads/ \
        && echo "[backup] ${stamp}: uploads mirrored" \
        || echo "[backup] ${stamp}: uploads mirror FAILED" >&2

    find /backups/db -name 'dpr_monitor_*.dump' -mtime +"${KEEP_DAYS}" -delete

    sleep "$((INTERVAL_HOURS * 3600))"
done
