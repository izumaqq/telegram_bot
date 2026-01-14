import os
import importlib
import sqlite3
import pytest
from datetime import datetime, timedelta

@pytest.mark.asyncio
async def test_build_calendar_marks(tmp_path, monkeypatch):
    db_file = tmp_path / "test_bookings.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    # prepare DB
    con = sqlite3.connect(str(db_file))
    cur = con.cursor()
    cur.execute('''CREATE TABLE bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        date TEXT,
        time TEXT,
        comment TEXT
    )''')
    cur.execute('''CREATE TABLE blocked_dates (date TEXT PRIMARY KEY)''')
    cur.execute('''CREATE TABLE closed_weekdays (weekday INTEGER PRIMARY KEY)''')
    con.commit()

    today = datetime.now().date()
    # pick a date 3 days from now
    d_blocked = today + timedelta(days=3)
    d_full = today + timedelta(days=4)
    d_one = today + timedelta(days=5)

    # insert blocked date (iso format)
    cur.execute("INSERT INTO blocked_dates (date) VALUES (?)", (d_blocked.isoformat(),))
    # insert two bookings for d_full (DD.MM.YYYY format)
    d_full_display = d_full.strftime("%d.%m.%Y")
    cur.execute("INSERT INTO bookings (user_id,name,date,time) VALUES (?,?,?,?)", (1, 'A', d_full_display, '10:00'))
    cur.execute("INSERT INTO bookings (user_id,name,date,time) VALUES (?,?,?,?)", (2, 'B', d_full_display, '11:00'))
    # insert one booking for d_one
    d_one_display = d_one.strftime("%d.%m.%Y")
    cur.execute("INSERT INTO bookings (user_id,name,date,time) VALUES (?,?,?,?)", (3, 'C', d_one_display, '10:00'))

    # mark weekday of d_blocked as closed (to test closed_weekdays effect)
    wd = d_blocked.weekday()
    cur.execute("INSERT INTO closed_weekdays (weekday) VALUES (?)", (wd,))

    con.commit()
    con.close()

    # ensure project root is on sys.path so `src` package is importable
    from pathlib import Path
    import sys
    proj_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(proj_root))

    # set dummy token and admin ids so module imports cleanly
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ADMIN_IDS", "")

    # import bot and build calendar for current month
    import src.bot as bot
    importlib.reload(bot)

    markup = await bot.build_calendar(year=today.year, month=today.month, months=1, admin_mode=False)

    # gather button texts
    texts = []
    for row in markup.inline_keyboard:
        for btn in row:
            texts.append(btn.text)

    # expectations:
    # - blocked or closed weekday -> contains '⛔'
    assert any('⛔' in t for t in texts), "Expected a blocked/day-off mark (⛔)"
    # - full day -> contains '🔴'
    assert any('🔴' in t for t in texts), "Expected a full-day mark (🔴)"
    # - one-slot day -> contains '(1/2)'
    assert any('(1/2)' in t for t in texts), "Expected a (1/2) mark"
