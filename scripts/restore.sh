#!/usr/bin/env bash
set -euo pipefail
[ "$#" -eq 1 ] || { echo "Usage: DATABASE_PATH=/path/app.db $0 backup.db"; exit 2; }
: "${DATABASE_PATH:?Set DATABASE_PATH}"; [ -f "$1" ] || { echo "Backup not found"; exit 2; }
sqlite3 "$1" 'PRAGMA integrity_check;' | grep -qx ok
mkdir -p "$(dirname "$DATABASE_PATH")"; tmp="${DATABASE_PATH}.restore.$$"
sqlite3 "$1" ".backup '$tmp'"; mv "$tmp" "$DATABASE_PATH"; echo "Restored $DATABASE_PATH"
