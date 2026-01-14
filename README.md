# telegram_bot

## Docker deployment 🐳

1. Copy `.env.example` to `.env` and fill in your `BOT_TOKEN` and `ADMIN_IDS` (do NOT commit `.env`).

2. Build and run with Docker Compose:

```bash
docker compose build
docker compose up -d
```

3. The SQLite DB file `bookings.db` is mounted from the repository root so data is persistent. To view logs:

```bash
docker compose logs -f
```

4. If you need to rebuild after code changes:

```bash
docker compose build --no-cache
docker compose up -d
```

---

## Quick local test (1 command) 🧪

I added helper scripts and a Makefile so you can start the bot for testing with one command.

1. Prepare `.env` (only once):

```bash
make setup
# then edit .env and add BOT_TOKEN and ADMIN_IDS
```

2. Start locally (uses a virtualenv and installs deps if needed):

```bash
make run
# or: ./run_local.sh
```

3. Or test with Docker (one command to build+start):

```bash
./docker-run.sh
# follow logs: docker compose logs -f
```

4. After testing, check data:

```bash
sqlite3 bookings.db "SELECT id, name, date, time, comment FROM bookings ORDER BY id DESC LIMIT 5;"
```

Notes:
- `make setup` will copy `.env.example` → `.env` and set secure permissions; edit `.env` to add your token.
- Scripts are for development/testing. For 24/7 production deployment, we will prepare deployment steps (Docker / cloud).

Booking rules & admin date management (new):
- Maximum **2 bookings per day** are enforced automatically. If a date already has 2 bookings it will be shown as **🔴** in the calendar and cannot be selected.
- Dates with 1 booking show **(1/2)**; available dates show the day number.
- Admins can block/unblock specific dates: open `/admin` → **🛑 Управление датами** → click a date to toggle block (blocked dates marked with **⛔**).
- Admins can also mark weekdays as non-working (recurring): open `/admin` → **📆 Управление днями недели**, then toggle any weekday (⛔ = non-working, ✅ = working). Non-working weekdays are shown as **⛔** in all months and users cannot book on those days.
- The calendar now supports choosing any month: click the month header or **Выбрать месяц** to jump to a specific month and year.

To apply database migration (if your DB was created before these changes):

```bash
python3 scripts/migrate_add_blocked_dates.py
```

This will add the `blocked_dates` table used by admin date management.
---

## Systemd example (if you don't use Docker)

Create `/etc/systemd/system/telegram_bot.service` with:

```ini
[Unit]
Description=Telegram Bot
After=network.target

[Service]
User=botuser
WorkingDirectory=/home/bot/telegram_bot
EnvironmentFile=/home/bot/telegram_bot/.env
ExecStart=/home/bot/telegram_bot/venv/bin/python /home/bot/telegram_bot/src/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram_bot
sudo journalctl -u telegram_bot -f
```

---

### Notes
- Secrets: keep `BOT_TOKEN` and `ADMIN_IDS` only in `.env` or Docker secrets in production.
- If you want, I can add a GitHub Actions workflow to deploy via SSH automatically. Tell me if you want that and whether you have an SSH user/key on the server.
