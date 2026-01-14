#!/usr/bin/env python3
import sqlite3

DB = 'bookings.db'

con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS closed_weekdays (
    weekday INTEGER PRIMARY KEY
)''')
con.commit()
print('closed_weekdays table ensured')
con.close()