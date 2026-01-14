import os
import sqlite3
import importlib
import pytest
from pathlib import Path
import sys

import tempfile

@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "test_bookings.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    # ensure project root is on sys.path so `src` package is importable
    proj_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(proj_root))

    # set dummy token and admin ids so module imports cleanly
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ADMIN_IDS", "")

    # import (or reload) the bot module so DB_PATH is picked up
    import src.bot as bot
    importlib.reload(bot)

    # run init_db
    await bot.init_db()

    # verify tables exist
    con = sqlite3.connect(str(db_file))
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert "bookings" in tables
    assert "reviews" in tables
    assert "blocked_dates" in tables
    assert "closed_weekdays" in tables
    con.close()