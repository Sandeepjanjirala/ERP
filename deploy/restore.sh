#!/bin/sh
# Restore a backup made by backup.sh in place of the current database:
#   deploy/restore.sh backups/edunexa-20261110-011500.dump --yes
#
# The archive is loaded into a new database first; only if that succeeds is it swapped in. The
# database it replaces is kept (renamed edunexa_replaced_<time>) until you drop it, so a restore
# can itself be undone. Migrations then bring the data up to this release's code.
set -eu
cd "$(dirname "$0")"
compose="docker compose -f compose.production.yaml ${COMPOSE_EXTRA:-}"
archive="${1:-}"
if [ ! -f "$archive" ] || [ "${2:-}" != "--yes" ]; then
    echo "usage: $0 <archive made by backup.sh> --yes   (replaces the current database)" >&2
    exit 2
fi
psql="$compose exec -T db psql --username edunexa --dbname postgres --set ON_ERROR_STOP=1 --quiet"
replaced="edunexa_replaced_$(date -u +%Y%m%d%H%M%S)"

$psql --command "DROP DATABASE IF EXISTS edunexa_restore" --command "CREATE DATABASE edunexa_restore"
if ! $compose exec -T db pg_restore --username edunexa --dbname edunexa_restore \
        --no-owner --exit-on-error < "$archive"; then
    $psql --command "DROP DATABASE edunexa_restore"
    echo "The archive could not be restored; nothing was changed." >&2
    exit 1
fi
$compose stop caddy web worker beat
$psql --command "ALTER DATABASE edunexa RENAME TO $replaced" \
      --command "ALTER DATABASE edunexa_restore RENAME TO edunexa"
$compose run --rm --no-deps web python manage.py migrate --noinput
$compose up --detach --wait
echo "Restored $archive. The previous database is kept as $replaced; when you are sure, drop it:"
echo "  $compose exec db dropdb --username edunexa $replaced"
