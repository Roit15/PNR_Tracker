"""
Database module for PNR Tracker.
PostgreSQL database to store bookings and their status.

Supports both PostgreSQL (production/cloud) and SQLite (local dev fallback).
Set DATABASE_URL env var for PostgreSQL, or leave unset for SQLite fallback.
"""

import os
import logging
from datetime import datetime, date
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

# Detect which backend to use
if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    DB_BACKEND = 'postgresql'
else:
    import sqlite3
    DB_BACKEND = 'sqlite'
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pnr_tracker.db')


@contextmanager
def get_connection():
    """Get a database connection as a context manager."""
    if DB_BACKEND == 'postgresql':
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _fetchall_as_dicts(cursor):
    """Fetch all rows as dicts (works for both backends)."""
    if DB_BACKEND == 'postgresql':
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    return cursor.fetchall()


def _fetchone_as_dict(cursor):
    """Fetch one row as a dict."""
    if DB_BACKEND == 'postgresql':
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
    return cursor.fetchone()


def _p():
    """Return the correct placeholder for the backend."""
    return '%s' if DB_BACKEND == 'postgresql' else '?'


def init_db():
    """Initialize the database and create tables if they don't exist."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if DB_BACKEND == 'postgresql':
            cursor.execute('''
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
                    created_at TEXT DEFAULT (TO_CHAR(NOW() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS')),
                    active INTEGER DEFAULT 1,
                    airline TEXT DEFAULT 'indigo',
                    passenger_count INTEGER DEFAULT 1
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bookings_pnr ON bookings(pnr)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bookings_active ON bookings(active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bookings_flight_date ON bookings(flight_date)')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pnr TEXT NOT NULL,
                    passenger_name TEXT NOT NULL,
                    passenger_lastname TEXT,
                    flight_number TEXT,
                    route TEXT,
                    flight_date TEXT NOT NULL,
                    departure_time TEXT,
                    arrival_time TEXT,
                    status TEXT DEFAULT 'Pending Check',
                    last_checked TEXT,
                    status_detail TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    active INTEGER DEFAULT 1,
                    airline TEXT DEFAULT 'indigo',
                    passenger_count INTEGER DEFAULT 1
                )
            ''')

            # Migrations: add columns if missing (existing DBs)
            cursor.execute("PRAGMA table_info(bookings)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'passenger_lastname' not in columns:
                cursor.execute('ALTER TABLE bookings ADD COLUMN passenger_lastname TEXT')
                cursor.execute('SELECT id, passenger_name FROM bookings WHERE passenger_lastname IS NULL')
                for row in cursor.fetchall():
                    parts = row[1].strip().split()
                    lastname = parts[-1] if parts else ''
                    cursor.execute('UPDATE bookings SET passenger_lastname = ? WHERE id = ?', (lastname, row[0]))

            if 'airline' not in columns:
                cursor.execute("ALTER TABLE bookings ADD COLUMN airline TEXT DEFAULT 'indigo'")
                cursor.execute("UPDATE bookings SET airline = 'indigo' WHERE airline IS NULL")

            if 'passenger_firstname' not in columns:
                cursor.execute('ALTER TABLE bookings ADD COLUMN passenger_firstname TEXT')

            if 'passenger_count' not in columns:
                cursor.execute('ALTER TABLE bookings ADD COLUMN passenger_count INTEGER DEFAULT 1')
                cursor.execute('UPDATE bookings SET passenger_count = 1 WHERE passenger_count IS NULL')


def add_booking(pnr, passenger_name, flight_number, route, flight_date,
                departure_time=None, arrival_time=None, passenger_lastname=None,
                airline='indigo', passenger_firstname=None, passenger_count=1):
    """Add a new booking to track."""
    p = _p()

    with get_connection() as conn:
        cursor = conn.cursor()

        # Check if this exact segment already exists (same PNR + route + date)
        cursor.execute(
            f'SELECT id FROM bookings WHERE pnr = {p} AND route = {p} AND flight_date = {p}',
            (pnr, route, flight_date)
        )
        existing = _fetchone_as_dict(cursor)
        if existing:
            return None  # Already tracking this segment

        # Auto-extract last name from full name if not provided
        if not passenger_lastname and passenger_name:
            parts = passenger_name.strip().split()
            passenger_lastname = parts[-1] if parts else ''

        cursor.execute(f'''
            INSERT INTO bookings (pnr, passenger_name, passenger_lastname, passenger_firstname,
                                flight_number, route, flight_date, departure_time, arrival_time, airline, passenger_count)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        ''', (pnr, passenger_name, passenger_lastname, passenger_firstname,
              flight_number, route, flight_date, departure_time, arrival_time, airline, passenger_count))

        if DB_BACKEND == 'postgresql':
            cursor.execute('SELECT lastval()')
            booking_id = cursor.fetchone()[0]
        else:
            booking_id = cursor.lastrowid

        return booking_id


def get_active_bookings():
    """Get all active bookings (flight date >= today)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM bookings
            WHERE active = 1
            ORDER BY flight_date ASC
        ''')
        return _fetchall_as_dicts(cursor)


def get_completed_bookings():
    """Get completed/past bookings (inactive), deduplicated by PNR keeping latest."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.* FROM bookings b
            INNER JOIN (
                SELECT pnr, route, MAX(id) as max_id FROM bookings WHERE active = 0 GROUP BY pnr, route
            ) latest ON b.id = latest.max_id
            ORDER BY b.flight_date DESC
        ''')
        return _fetchall_as_dicts(cursor)


def get_bookings_to_check():
    """Get bookings that need status checking (active and flight date not passed)."""
    p = _p()
    today = date.today().strftime('%Y-%m-%d')

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT * FROM bookings
            WHERE active = 1 AND flight_date >= {p}
            ORDER BY flight_date ASC
        ''', (today,))
        return _fetchall_as_dicts(cursor)


def get_bookings_to_check_grouped():
    """Get bookings grouped by (pnr, airline) for deduplicated checking.

    Returns a dict mapping (pnr, airline) -> list[dict].
    """
    bookings = get_bookings_to_check()
    grouped = {}
    for b in bookings:
        airline = b.get('airline', 'indigo') if isinstance(b, dict) else (b['airline'] if 'airline' in b.keys() else 'indigo')
        key = (b['pnr'], airline)
        grouped.setdefault(key, []).append(b)
    return grouped


def get_booking(booking_id):
    """Get a specific booking by ID."""
    p = _p()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM bookings WHERE id = {p}', (booking_id,))
        return _fetchone_as_dict(cursor)


def update_booking_status(pnr, status, status_detail=None, passenger_count=None):
    """Update the status of a booking."""
    p = _p()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        cursor = conn.cursor()

        if passenger_count is not None:
            cursor.execute(f'''
                UPDATE bookings
                SET status = {p}, status_detail = {p}, last_checked = {p}, passenger_count = {p}
                WHERE pnr = {p} AND active = 1
            ''', (status, status_detail, now, passenger_count, pnr))
        else:
            cursor.execute(f'''
                UPDATE bookings
                SET status = {p}, status_detail = {p}, last_checked = {p}
                WHERE pnr = {p} AND active = 1
            ''', (status, status_detail, now, pnr))


def deactivate_booking(booking_id):
    """Deactivate a booking (stop tracking)."""
    p = _p()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'UPDATE bookings SET active = 0 WHERE id = {p}', (booking_id,))


def deactivate_past_bookings():
    """Deactivate bookings where the flight date has passed, or today's flights that have already departed."""
    p = _p()
    today = date.today().strftime('%Y-%m-%d')
    now_dt = datetime.now().strftime('%Y-%m-%d %H:%M')

    with get_connection() as conn:
        cursor = conn.cursor()

        if DB_BACKEND == 'postgresql':
            cursor.execute(f'''
                UPDATE bookings SET active = 0, status = CASE WHEN status = 'Pending Check' THEN 'Completed' ELSE status END
                WHERE flight_date < {p} AND active = 1
            ''', (today,))
            count = cursor.rowcount

            cursor.execute(f'''
                UPDATE bookings SET active = 0, status = CASE WHEN status IN ('Pending Check', 'Confirmed') THEN 'Completed' ELSE status END
                WHERE flight_date = {p} AND active = 1
                AND departure_time IS NOT NULL AND departure_time != ''
                AND (flight_date || ' ' || departure_time)::timestamp < ({p}::timestamp - INTERVAL '3 hours')
            ''', (today, now_dt))
            count += cursor.rowcount
        else:
            cursor.execute(f'''
                UPDATE bookings SET active = 0, status = CASE WHEN status = 'Pending Check' THEN 'Completed' ELSE status END
                WHERE flight_date < {p} AND active = 1
            ''', (today,))
            count = cursor.rowcount

            cursor.execute(f'''
                UPDATE bookings SET active = 0, status = CASE WHEN status IN ('Pending Check', 'Confirmed') THEN 'Completed' ELSE status END
                WHERE flight_date = {p} AND active = 1
                AND departure_time IS NOT NULL AND departure_time != ''
                AND DATETIME(flight_date || ' ' || departure_time) < DATETIME({p}, '-3 hours')
            ''', (today, now_dt))
            count += cursor.rowcount

        return count


def delete_booking(booking_id):
    """Delete a booking from the database."""
    p = _p()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'DELETE FROM bookings WHERE id = {p}', (booking_id,))

