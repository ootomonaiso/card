#!/bin/sh
# SQLite DB の安全なバックアップ（WAL 稼働中でも整合の取れたコピーを作る）。
# 使い方:  ./backup_db.sh [DBパス] [出力先ディレクトリ]
# cron 例（毎日 3:00、日付名で保存し 30 日より古い世代を自動削除）:
#   0 3 * * * /home/pi/card/deploy/backup_db.sh /home/pi/card/lending.sqlite3 /home/pi/backups
set -eu

DB="${1:-lending.sqlite3}"
OUT_DIR="${2:-backups}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/lending-$(date +%Y%m%d).sqlite3"

# .backup はオンラインバックアップ API を使うため、稼働中でも安全。
sqlite3 "$DB" ".backup '$OUT'"
echo "backup: $OUT"

# 30日より古いバックアップを削除
find "$OUT_DIR" -name 'lending-*.sqlite3' -mtime +30 -delete
