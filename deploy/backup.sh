#!/bin/sh
# Ежедневный дамп БД, хранить 14 копий. Cron: 15 3 * * * /opt/cinemate/deploy/backup.sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
docker compose exec -T db pg_dump -U cinemate cinemate | gzip > "backups/cinemate_$(date +%F).sql.gz"
ls -1t backups/cinemate_*.sql.gz | tail -n +15 | xargs -r rm --
