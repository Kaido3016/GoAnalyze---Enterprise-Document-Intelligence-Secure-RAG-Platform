#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=I_UNDERSTAND to confirm an isolated restore drill}"
[[ "$RESTORE_CONFIRM" == "I_UNDERSTAND" ]] || { echo "Confirmation mismatch" >&2; exit 2; }
: "${POSTGRES_DUMP_AGE:?Set POSTGRES_DUMP_AGE to an encrypted custom-format dump}"
: "${OBJECTS_TAR_AGE:?Set OBJECTS_TAR_AGE to the encrypted object backup}"
: "${RESTORE_DATABASE_URL:?Set RESTORE_DATABASE_URL to a dedicated empty restore-drill database}"
: "${BACKUP_AGE_IDENTITY:?Set BACKUP_AGE_IDENTITY to the private age identity file}"
: "${MINIO_ENDPOINT:?Set MINIO_ENDPOINT}"
: "${MINIO_ACCESS_KEY:?Set MINIO_ACCESS_KEY}"
: "${MINIO_SECRET_KEY:?Set MINIO_SECRET_KEY}"
: "${RESTORE_BUCKET:?Set RESTORE_BUCKET to a dedicated bucket ending in -restore-drill}"
[[ "$RESTORE_BUCKET" == *-restore-drill ]] || { echo "RESTORE_BUCKET must end in -restore-drill" >&2; exit 2; }
command -v age >/dev/null || { echo "age is required" >&2; exit 2; }
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 2; }
command -v mc >/dev/null || { echo "mc is required" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
chmod 700 "$work"

age -d -i "$BACKUP_AGE_IDENTITY" "$POSTGRES_DUMP_AGE" \
  | pg_restore --dbname="$RESTORE_DATABASE_URL" --clean --if-exists --no-owner --no-acl

age -d -i "$BACKUP_AGE_IDENTITY" "$OBJECTS_TAR_AGE" \
  | tar -xzf - -C "$work"
mc alias set goanalyze-restore "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc mb --ignore-existing "goanalyze-restore/$RESTORE_BUCKET"
mc mirror --overwrite "$work/objects" "goanalyze-restore/$RESTORE_BUCKET"

echo "Restore completed to the explicitly named restore-drill database and bucket."
echo "Now run application smoke tests, compare row/object counts, and record measured RPO/RTO."
