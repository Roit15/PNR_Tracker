"""
Database module for PNR Tracker.
SQLite database to store bookings and their status.
"""

import sqlite3
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pnr_tracker.db')


def get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()
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
            airline TEXT DEFAULT 'indigo'
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

    conn.commit()
    conn.close()


def add_booking(pnr, passenger_name, flight_number, route, flight_date,
                departure_time=None, arrival_time=None, passenger_lastname=None,
                airline='indigo', passenger_firstname=None):
    """Add a new booking to track."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check if PNR already exists
    cursor.execute('SELECT id FROM bookings WHERE pnr = ? AND active = 1', (pnr,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return None  # Already tracking this PNR

    # Auto-extract last name from full name if not provided
    if not passenger_lastname and passenger_name:
        parts = passenger_name.strip().split()
        passenger_lastname = parts[-1] if parts else ''

    cursor.execute('''
        INSERT INTO bookings (pnr, passenger_name, passenger_lastname, passenger_firstname,
                            flight_number, route, flight_date, departure_time, arrival_time, airline)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (pnr, passenger_name, passenger_lastname, passenger_firstname,
          flight_number, route, flight_date, departure_time, arrival_time, airline))
    conn.commit()
    booking_id = cursor.lastrowid
    conn.close()
    return booking_id


def get_active_bookings():
    """Get all active bookings (flight date >= today)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM bookings
        WHERE active = 1
        ORDER BY flight_date ASC
    ''')
    bookings = cursor.fetchall()
    conn.close()
    return bookings


def get_completed_bookings():
    """Get completed/past bookings (inactive), deduplicated by PNR keeping latest."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT b.* FROM bookings b
        INNER JOIN (
            SELECT pnr, MAX(id) as max_id FROM bookings WHERE active = 0 GROUP BY pnr
        ) latest ON b.id = latest.max_id
        ORDER BY b.flight_date DESC
    ''')
    bookings = cursor.fetchall()
    conn.close()
    return bookings


def get_bookings_to_check():
    """Get bookings that need status checking (active and flight date not passed)."""
    conn = get_connection()
    cursor = conn.cursor()
    today = date.today().strftime('%Y-%m-%d')

    cursor.execute('''
        SELECT * FROM bookings
        WHERE active = 1 AND flight_date >= ?
        ORDER BY flight_date ASC
    ''', (today,))
    bookings = cursor.fetchall()
    conn.close()
    return bookings


def get_booking(booking_id):
    """Get a specific booking by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,))
    booking = cursor.fetchone()
    conn.close()
    return booking


def update_booking_status(pnr, status, status_detail=None):
    """Update the status of a booking."""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('''
        UPDATE bookings
        SET status = ?, status_detail = ?, last_checked = ?
        WHERE pnr = ? AND active = 1
    ''', (status, status_detail, now, pnr))
    conn.commit()
    conn.close()


def deactivate_booking(booking_id):
    """Deactivate a booking (stop tracking)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE bookings SET active = 0 WHERE id = ?', (booking_id,))
    conn.commit()
    conn.close()


def deactivate_past_bookings():
    """Deactivate bookings where the flight date has passed, or today's flights that have already departed."""
    conn = get_connection()
    cursor = conn.cursor()
    today = date.today().strftime('%Y-%m-%d')
    now_time = datetime.now().strftime('%H:%M')

    # Deactivate flights from past days
    cursor.execute('''
        UPDATE bookings SET active = 0, status = CASE WHEN status = 'Pending Check' THEN 'Completed' ELSE status END
        WHERE flight_date < ? AND active = 1
    ''', (today,))
    count = cursor.rowcount

    # Deactivate today's flights whose departure time has passed (3-hour buffer for flight duration)
    # Only if departure_time is set and flight has likely landed
    cursor.execute('''
        UPDATE bookings SET active = 0, status = CASE WHEN status IN ('Pending Check', 'Confirmed') THEN 'Completed' ELSE status END
        WHERE flight_date = ? AND active = 1
        AND departure_time IS NOT NULL AND departure_time != ''
        AND TIME(departure_time) < TIME(?, '-3 hours')
    ''', (today, now_time))
    count += cursor.rowcount

    conn.commit()
    conn.close()
    return count


def delete_booking(booking_id):
    """Delete a booking from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
    conn.commit()
    conn.close()
