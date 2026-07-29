#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_PATH:?Set DATABASE_PATH to the SQLite database path}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"; mkdir -p "$BACKUP_DIR"
out="$BACKUP_DIR/app-$(date -u +%Y%m%dT%H%M%SZ).db"
sqlite3 "$DATABASE_PATH" ".timeout 30000" ".backup '$out'"
echo "$out"
