#!/bin/sh
# Back up the EduNexa database: a compressed PostgreSQL archive in deploy/backups/, checked to be
# readable, with archives older than KEEP_DAYS (default 14) removed. Prints the archive's path.
#
# Run nightly from cron, and before every release:
#   15 1 * * * /opt/edunexa/deploy/backup.sh >> /var/log/edunexa-backup.log 2>&1
# Copy deploy/backups/ off the server too (another machine or storage bucket): a backup on the
# same disk does not survive losing that disk.
set -eu
cd "$(dirname "$0")"
compose="docker compose -f compose.production.yaml ${COMPOSE_EXTRA:-}"
mkdir -p backups
chmod 700 backups
archive="backups/edunexa-$(date -u +%Y%m%d-%H%M%S).dump"
$compose exec -T db pg_dump --username edunexa --dbname edunexa --format custom > "$archive.partial"
# An archive that pg_restore can't list is not a backup.
$compose exec -T db pg_restore --list < "$archive.partial" > /dev/null
mv "$archive.partial" "$archive"
find backups -name 'edunexa-*.dump' -mtime +"${KEEP_DAYS:-14}" -delete
echo "$archive"
