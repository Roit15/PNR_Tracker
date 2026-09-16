"""
Bidirectional sync engine for PNR Tracker.
Syncs bookings between local (SQLite) and remote (VPS PostgreSQL) instances.

Uses (pnr, route, flight_date) as unique key.
Conflicts resolved by most recent last_checked timestamp.
"""

import os
import json
import logging
import requests
from datetime import datetime
from database import get_connection, _p, _fetchall_as_dicts, DB_BACKEND

logger = logging.getLogger('sync')

SYNC_REMOTE_URL = os.getenv('SYNC_REMOTE_URL', '').strip().rstrip('/')
SYNC_SECRET = os.getenv('SYNC_SECRET', 'pnr-sync-key-2026')


def get_all_bookings_for_sync():
    """Export all bookings as a list of dicts for the sync API."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bookings ORDER BY id')
        rows = _fetchall_as_dicts(cursor)
        # Convert sqlite3.Row to plain dicts
        return [dict(r) for r in rows]


def merge_remote_bookings(remote_bookings):
    """Merge remote bookings into the local database.
    
    Logic:
    - Key = (pnr, route, flight_date)
    - If key doesn't exist locally → INSERT
    - If key exists locally → update if remote has a more recent last_checked
    - Never delete local records based on remote
    
    Returns: (inserted_count, updated_count)
    """
    p = _p()
    inserted = 0
    updated = 0
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all local bookings keyed by (pnr, route, flight_date)
        cursor.execute('SELECT * FROM bookings')
        local_rows = _fetchall_as_dicts(cursor)
        local_map = {}
        for row in local_rows:
            r = dict(row)
            key = (r['pnr'], r.get('route', ''), r['flight_date'])
            local_map[key] = r
        
        for rb in remote_bookings:
            key = (rb['pnr'], rb.get('route', ''), rb['flight_date'])
            
            if key not in local_map:
                # INSERT new booking
                cursor.execute(f'''
                    INSERT INTO bookings (pnr, passenger_name, passenger_lastname, passenger_firstname,
                                        flight_number, route, flight_date, departure_time, arrival_time,
                                        status, last_checked, status_detail, created_at, active,
                                        airline, passenger_count)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                ''', (
                    rb['pnr'], rb.get('passenger_name', ''),
                    rb.get('passenger_lastname', ''), rb.get('passenger_firstname', ''),
                    rb.get('flight_number', ''), rb.get('route', ''),
                    rb['flight_date'], rb.get('departure_time', ''),
                    rb.get('arrival_time', ''), rb.get('status', 'Pending Check'),
                    rb.get('last_checked', ''), rb.get('status_detail', ''),
                    rb.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                    rb.get('active', 1), rb.get('airline', 'indigo'),
                    rb.get('passenger_count', 1)
                ))
                inserted += 1
            else:
                # Check if remote is more recent
                local = local_map[key]
                remote_checked = rb.get('last_checked') or ''
                local_checked = local.get('last_checked') or ''
                
                if remote_checked > local_checked:
                    # Update local with remote data
                    cursor.execute(f'''
                        UPDATE bookings
                        SET status = {p}, status_detail = {p}, last_checked = {p},
                            departure_time = {p}, arrival_time = {p},
                            flight_number = {p}, passenger_count = {p}, active = {p}
                        WHERE id = {p}
                    ''', (
                        rb.get('status', local['status']),
                        rb.get('status_detail', local.get('status_detail', '')),
                        remote_checked,
                        rb.get('departure_time', local.get('departure_time', '')),
                        rb.get('arrival_time', local.get('arrival_time', '')),
                        rb.get('flight_number', local.get('flight_number', '')),
                        rb.get('passenger_count', local.get('passenger_count', 1)),
                        rb.get('active', local.get('active', 1)),
                        local['id']
                    ))
                    updated += 1
    
    return inserted, updated


def run_sync():
    """Pull bookings from the remote instance and merge them locally.
    Also push local bookings to the remote."""
    if not SYNC_REMOTE_URL:
        return
    
    logger.info(f"Starting sync with {SYNC_REMOTE_URL}")
    
    try:
        # PULL: Get remote bookings
        resp = requests.get(
            f"{SYNC_REMOTE_URL}/api/sync",
            headers={'X-Sync-Secret': SYNC_SECRET},
            timeout=30
        )
        if resp.status_code == 200:
            remote_data = resp.json()
            remote_bookings = remote_data.get('bookings', [])
            inserted, updated = merge_remote_bookings(remote_bookings)
            logger.info(f"PULL complete: {inserted} inserted, {updated} updated from remote ({len(remote_bookings)} total)")
        else:
            logger.warning(f"PULL failed: HTTP {resp.status_code}")
        
        # PUSH: Send local bookings to remote
        local_bookings = get_all_bookings_for_sync()
        resp = requests.post(
            f"{SYNC_REMOTE_URL}/api/sync",
            json={'bookings': local_bookings},
            headers={'X-Sync-Secret': SYNC_SECRET},
            timeout=30
        )
        if resp.status_code == 200:
            result = resp.json()
            logger.info(f"PUSH complete: {result.get('inserted', 0)} inserted, {result.get('updated', 0)} updated on remote")
        else:
            logger.warning(f"PUSH failed: HTTP {resp.status_code}")
            
    except requests.exceptions.ConnectionError:
        logger.warning(f"Sync failed: cannot reach {SYNC_REMOTE_URL}")
    except Exception as e:
        logger.error(f"Sync error: {e}")
