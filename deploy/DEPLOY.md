# Деплой на VPS (Ubuntu 22.04+)

Нужны: VPS с Docker и docker compose, домен с A-записью на IP сервера, открытые порты 80/443.

## 1. Подготовка
```bash
git clone <ваш-репозиторий> /opt/cinemate && cd /opt/cinemate
cp .env.example .env
# заполните .env: DOMAIN, PUBLIC_URL, секреты (openssl rand -hex 32), TELEGRAM_BOT_TOKEN, KINOPOISK_API_KEY
```

## 2. Первый HTTPS-сертификат
Nginx не стартует без сертификата, поэтому получаем его отдельно (порт 80 должен быть свободен):
```bash
docker compose run --rm -p 80:80 --entrypoint certbot certbot certonly --standalone \
  -d "$DOMAIN" --email you@example.com --agree-tos --no-eff-email
```
(Замените `$DOMAIN` на домен или выполните `set -a; . ./.env; set +a`.)

## 3. Запуск
```bash
docker compose up -d --build
docker compose logs -f api bot
curl https://$DOMAIN/api/health        # {"status":"ok",...}
```
Миграции БД применяет сервис `migrate` при каждом запуске. Вебхук Telegram бот регистрирует сам
(`BOT_MODE=webhook`, адрес `PUBLIC_URL/telegram/webhook`, секретный заголовок из `TELEGRAM_WEBHOOK_SECRET`).

## 4. Администратор
```bash
docker compose run --rm api python -m app.cli create_superuser --email you@example.com --name Admin
```
Либо укажите `ADMIN_EMAIL` в `.env`: пользователь с этим email при регистрации получит роль admin.

## 5. Резервные копии
`crontab -e` → `15 3 * * * /opt/cinemate/deploy/backup.sh`. Восстановление:
`gunzip -c backups/cinemate_ГГГГ-ММ-ДД.sql.gz | docker compose exec -T db psql -U cinemate cinemate`

## 6. Обновление
```bash
git pull && docker compose up -d --build
```

## Перенос данных из CineVault (MySQL)
См. `backend/scripts/migrate_mysql_to_pg.py` (запускать с `--dry-run`).

## Что пока не включено
Веб-интерфейс (Next.js), AI-рекомендации (`/mood`), Celery-воркер с напоминаниями и проверкой новых серий.
