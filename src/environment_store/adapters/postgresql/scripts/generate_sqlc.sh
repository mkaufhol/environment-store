#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

YOYO_DB_CONFIG="$PROJECT_DIR/yoyo-database.ini"
SCHEMA_OUT="$PROJECT_DIR/schema.sql"
SQLC_CONFIG="$PROJECT_DIR/sqlc.yaml"
TMP_SCHEMA="$(mktemp)"

cleanup() {
  rm -f "$TMP_SCHEMA"
}

trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: required command '$1' is not installed or not on PATH." >&2
    exit 1
  fi
}

require_file() {
  if [[ ! -f "$1" ]]; then
    echo "Error: required file '$1' was not found." >&2
    exit 1
  fi
}

require_command sqlc
require_command pg_dump
require_file "$YOYO_DB_CONFIG"
require_file "$SQLC_CONFIG"

database_url="$(sed -n 's/^database[[:space:]]*=[[:space:]]*//p' "$YOYO_DB_CONFIG" | head -n 1)"

if [[ -z "$database_url" ]]; then
  echo "Error: no 'database =' entry found in $YOYO_DB_CONFIG." >&2
  exit 1
fi

pg_dump_url="$(printf '%s' "$database_url" | sed -E 's#^postgresql\+[A-Za-z0-9_]+://#postgresql://#')"

mkdir -p "$(dirname -- "$SCHEMA_OUT")"

echo "Dumping schema to temporary file"
pg_dump \
  --schema-only \
  --schema=public \
  --no-owner \
  --no-privileges \
  --no-comments \
  --exclude-table='_yoyo_migration' \
  --exclude-table='_yoyo_log' \
  --exclude-table='_yoyo_version' \
  --exclude-table='yoyo_lock' \
  --file "$TMP_SCHEMA" \
  "$pg_dump_url"

echo "Sanitizing schema for sqlc at $SCHEMA_OUT"
awk '
  /^\\/ { next }
  /^--/ { next }
  /^SET / { next }
  /^SELECT pg_catalog\.set_config/ { next }
  /^CREATE EXTENSION / { next }
  /^COMMENT ON EXTENSION / { next }
  /^CREATE SCHEMA / { next }
  /^ALTER SCHEMA / { next }
  /^COMMENT ON SCHEMA / { next }
  /^$/ {
    if (blank) next
    blank = 1
    print
    next
  }
  {
    blank = 0
    print
  }
' "$TMP_SCHEMA" > "$SCHEMA_OUT"

echo "Running sqlc generate"
sqlc generate -f "$SQLC_CONFIG"

echo "Done."
