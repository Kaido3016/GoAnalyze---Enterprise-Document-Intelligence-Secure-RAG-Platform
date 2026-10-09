#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${BACKUP_DIR:?Set BACKUP_DIR to an encrypted backup destination}"
: "${BACKUP_AGE_RECIPIENT:?Set BACKUP_AGE_RECIPIENT to the age public recipient}"
: "${PGHOST:?Set PGHOST}"
: "${PGUSER:?Set PGUSER}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${PGPASSWORD:?Set PGPASSWORD}"
: "${MINIO_ENDPOINT:?Set MINIO_ENDPOINT}"
: "${MINIO_ACCESS_KEY:?Set MINIO_ACCESS_KEY}"
: "${MINIO_SECRET_KEY:?Set MINIO_SECRET_KEY}"
: "${MINIO_BUCKET:?Set MINIO_BUCKET}"
command -v age >/dev/null || { echo "age is required for encrypted backups" >&2; exit 2; }
command -v pg_dump >/dev/null || { echo "pg_dump is required" >&2; exit 2; }
command -v mc >/dev/null || { echo "MinIO client (mc) is required" >&2; exit 2; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export PGPASSWORD

# Coordinate a write-quiesce or take a consistent managed-database snapshot
# before running this script; PostgreSQL and object storage are separate systems.
pg_dump --format=custom --no-owner --no-acl \
  | age -r "$BACKUP_AGE_RECIPIENT" -o "$BACKUP_DIR/postgres-$stamp.dump.age"

mc alias set goanalyze-backup "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc mirror --overwrite "goanalyze-backup/$MINIO_BUCKET" "$work/objects"
tar -C "$work" -czf - objects \
  | age -r "$BACKUP_AGE_RECIPIENT" -o "$BACKUP_DIR/objects-$stamp.tar.gz.age"

sha256sum "$BACKUP_DIR/postgres-$stamp.dump.age" "$BACKUP_DIR/objects-$stamp.tar.gz.age" \
  > "$BACKUP_DIR/SHA256SUMS-$stamp"
chmod 600 "$BACKUP_DIR/"*
echo "Encrypted backups created: postgres-$stamp.dump.age and objects-$stamp.tar.gz.age"
echo "Verify copies, keys, retention, and restore using docs/PRODUCTION_ACCEPTANCE.md."
