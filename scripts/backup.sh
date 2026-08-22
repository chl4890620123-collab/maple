#!/usr/bin/env sh
# Linux/local helper only. The production Windows mini-PC uses deploy/scripts/deploy.ps1.
set -eu
BACKUP_DIR="${BACKUP_DIR:-./data/backups}"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
CID=$(docker compose ps -q maple-craft)
if [ -z "$CID" ]; then
  echo "maple-craft container is not running" >&2
  exit 1
fi
TMP="/tmp/maple_craft_${STAMP}.db"
docker exec "$CID" python -c "import os,sqlite3; src=os.getenv('DB_PATH','/app/data/maple_craft.db'); s=sqlite3.connect(src); d=sqlite3.connect('$TMP'); s.backup(d); d.close(); s.close()"
docker cp "$CID:$TMP" "$BACKUP_DIR/maple_craft_${STAMP}.db"
docker exec "$CID" rm -f "$TMP"
find "$BACKUP_DIR" -type f -name 'maple_craft_*.db' -mtime +28 -delete
