"""
One-time migration script: SQLite → PostgreSQL.
Usage: DATABASE_URL=postgresql://... python migrate_data.py
"""
import os
import sqlite3
import psycopg2
from psycopg2.extras import execute_values

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pnr_tracker.db')
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: Set DATABASE_URL env var to your PostgreSQL connection string")
    exit(1)

# Connect to both
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
pg_conn = psycopg2.connect(DATABASE_URL)

# Create table in Postgres
pg_cur = pg_conn.cursor()
pg_cur.execute('''
    CREATE TABLE IF NOT EXISTS bookings (
        id SERIAL PRIMARY KEY,
        pnr TEXT NOT NULL,
        passenger_name TEXT NOT NULL,
        passenger_lastname TEXT,
        passenger_firstname TEXT,
        flight_number TEXT,
        route TEXT,
        flight_date TEXT NOT NULL,
        departure_time TEXT,
        arrival_time TEXT,
        status TEXT DEFAULT 'Pending Check',
        last_checked TEXT,
        status_detail TEXT,
        created_at TEXT,
        active INTEGER DEFAULT 1,
        airline TEXT DEFAULT 'indigo',
        passenger_count INTEGER DEFAULT 1
    )
''')
pg_conn.commit()

# Read all rows from SQLite
sqlite_cur = sqlite_conn.cursor()
sqlite_cur.execute('SELECT * FROM bookings')
rows = sqlite_cur.fetchall()

if not rows:
    print("No rows to migrate.")
    exit(0)

# Get column names
columns = [desc[0] for desc in sqlite_cur.description]
print(f"Found {len(rows)} rows to migrate with columns: {columns}")

# Insert into Postgres (skip 'id' — let SERIAL auto-assign)
insert_columns = [c for c in columns if c != 'id']
placeholders = ', '.join(['%s'] * len(insert_columns))
insert_sql = f"INSERT INTO bookings ({', '.join(insert_columns)}) VALUES ({placeholders})"

migrated = 0
for row in rows:
    row_dict = dict(row)
    values = tuple(row_dict.get(c) for c in insert_columns)
    try:
        pg_cur.execute(insert_sql, values)
        migrated += 1
    except Exception as e:
        print(f"  Skip row id={row_dict.get('id')}: {e}")

pg_conn.commit()

# Verify
pg_cur.execute('SELECT COUNT(*) FROM bookings')
pg_count = pg_cur.fetchone()[0]

print(f"\nMigration complete!")
print(f"  SQLite rows: {len(rows)}")
print(f"  Postgres rows: {pg_count}")
print(f"  Migrated: {migrated}")

sqlite_conn.close()
pg_conn.close()
