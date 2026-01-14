#!/usr/bin/env python3
import sqlite3

DB = 'bookings.db'

con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS blocked_dates (
    date TEXT PRIMARY KEY
)''')
con.commit()
print('blocked_dates table ensured')
con.close()