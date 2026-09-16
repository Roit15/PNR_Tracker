"""
Scheduler module for PNR Tracker.
- Hourly: silent check — only sends URGENT email if any PNR is cancelled/rescheduled
- 8 AM & 6 PM IST: full status report email of all PNRs
"""

import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

from database import get_bookings_to_check, get_bookings_to_check_grouped, update_booking_status, deactivate_past_bookings
from scraper_router import check_pnr_by_airline
from emailer import send_status_email, send_urgent_alert

load_dotenv()
logger = logging.getLogger(__name__)

# Statuses that trigger an immediate urgent alert
ALERT_STATUSES = {'Cancelled', 'Rescheduled'}

# IndiGo batch size — 10 parallel Chrome windows
INDIGO_BATCH_SIZE = 10


def _kill_zombie_chromes():
    """Kill orphaned headless Chrome processes from previous failed scrapes."""
    try:
        import subprocess
        # Kill only headless Chrome instances (won't touch user's regular Chrome)
        subprocess.run(
            ['pkill', '-f', 'Chrome.*--headless'],
            capture_output=True, timeout=5
        )
        subprocess.run(
            ['pkill', '-f', 'chromedriver'],
            capture_output=True, timeout=5
        )
    except Exception as e:
        logger.debug(f"Zombie cleanup skipped: {e}")


def _resolve_passenger_info(booking):
    """Extract lastname, firstname, airline from a booking row."""
    lastname = booking['passenger_lastname'] or ''
    if not lastname:
        lastname = os.getenv('PASSENGER_LASTNAME', '')
    if not lastname and booking['passenger_name']:
        parts = booking['passenger_name'].strip().split()
        lastname = parts[-1] if parts else ''
    airline = booking['airline'] if 'airline' in booking.keys() else 'indigo'
    firstname = booking['passenger_firstname'] if 'passenger_firstname' in booking.keys() and booking['passenger_firstname'] else ''
    return lastname, firstname, airline


def _check_single_pnr(pnr, lastname, airline, firstname):
    """Check a single PNR via the scraper router. Returns result dict or error dict."""
    try:
        status_result = check_pnr_by_airline(pnr, lastname, airline, firstname)
        return status_result
    except Exception as e:
        logger.error(f"Error checking PNR {pnr}: {e}")
        return {'status': 'Error', 'detail': str(e), 'raw_text': ''}


def _build_results_for_group(pnr, rows, status_result, old_statuses):
    """Build result dicts for every booking row that shares this PNR.

    Updates the DB once, then returns a list of result dicts (one per row).
    """
    update_booking_status(pnr, status_result['status'], status_result.get('detail', ''))
    results = []
    for row in rows:
        old_status = old_statuses.get(row['id'], row['status'])
        results.append({
            'pnr': pnr,
            'passenger_name': row['passenger_name'],
            'flight_number': row['flight_number'],
            'route': row['route'],
            'flight_date': row['flight_date'],
            'status': status_result['status'],
            'detail': status_result.get('detail', ''),
            'old_status': old_status,
            'status_changed': old_status != status_result['status'],
        })
    return results


def _check_all_pnrs():
    """
    Check status of all active PNRs using a 3-phase pipeline:
      Phase 1: IndiGo PNRs — batched in groups of 5 parallel browser windows
      Phase 2: SriLankan PNRs — one by one (CDP shared Chrome constraint)
      Phase 3: Remaining airlines — one by one

    Returns list of results.
    """
    # Clean up any zombie Chrome processes from prior failed runs
    _kill_zombie_chromes()

    deactivated = deactivate_past_bookings()
    if deactivated:
        logger.info(f"Deactivated {deactivated} past booking(s)")

    grouped = get_bookings_to_check_grouped()
    if not grouped:
        logger.info("No active bookings to check")
        return []

    total_unique = len(grouped)
    total_rows = sum(len(rows) for rows in grouped.values())
    logger.info(f"Checking {total_rows} booking row(s) across {total_unique} unique PNR(s)")

    # Partition into airline groups
    indigo_pnrs = {}    # (pnr, airline) -> rows
    srilankan_pnrs = {}
    other_pnrs = {}

    for (pnr, airline), rows in grouped.items():
        if airline == 'indigo':
            indigo_pnrs[(pnr, airline)] = rows
        elif airline == 'srilankan':
            srilankan_pnrs[(pnr, airline)] = rows
        else:
            other_pnrs[(pnr, airline)] = rows

    all_results = []

    # ── Phase 1: IndiGo — batched parallel (5 at a time) ──────────────
    if indigo_pnrs:
        logger.info(f"═══ Phase 1: IndiGo — {len(indigo_pnrs)} unique PNR(s) in batches of {INDIGO_BATCH_SIZE} ═══")
        indigo_keys = list(indigo_pnrs.keys())

        for batch_start in range(0, len(indigo_keys), INDIGO_BATCH_SIZE):
            batch = indigo_keys[batch_start:batch_start + INDIGO_BATCH_SIZE]
            batch_num = (batch_start // INDIGO_BATCH_SIZE) + 1
            total_batches = (len(indigo_keys) + INDIGO_BATCH_SIZE - 1) // INDIGO_BATCH_SIZE
            logger.info(f"── IndiGo batch {batch_num}/{total_batches}: {len(batch)} PNR(s) ──")

            # Capture old statuses before the parallel check
            old_statuses = {}
            for (pnr, airline) in batch:
                for row in indigo_pnrs[(pnr, airline)]:
                    old_statuses[row['id']] = row['status']

            # Launch parallel checks
            futures = {}
            with ThreadPoolExecutor(max_workers=INDIGO_BATCH_SIZE) as executor:
                for (pnr, airline) in batch:
                    rows = indigo_pnrs[(pnr, airline)]
                    # Use info from first row for the check
                    lastname, firstname, _ = _resolve_passenger_info(rows[0])
                    logger.info(f"  Launching IndiGo check: PNR={pnr}")
                    future = executor.submit(_check_single_pnr, pnr, lastname, airline, firstname)
                    futures[future] = (pnr, airline)

                for future in as_completed(futures):
                    pnr, airline = futures[future]
                    rows = indigo_pnrs[(pnr, airline)]
                    status_result = future.result()
                    logger.info(f"  IndiGo PNR {pnr}: {status_result['status']}")
                    results = _build_results_for_group(pnr, rows, status_result, old_statuses)
                    all_results.extend(results)

            logger.info(f"── IndiGo batch {batch_num} complete ──")

    # ── Phase 2: SriLankan — sequential (one by one) ──────────────────
    if srilankan_pnrs:
        logger.info(f"═══ Phase 2: SriLankan — {len(srilankan_pnrs)} unique PNR(s), one by one ═══")
        for i, ((pnr, airline), rows) in enumerate(srilankan_pnrs.items(), 1):
            lastname, firstname, _ = _resolve_passenger_info(rows[0])
            old_statuses = {row['id']: row['status'] for row in rows}
            logger.info(f"  [{i}/{len(srilankan_pnrs)}] SriLankan PNR={pnr}")

            status_result = _check_single_pnr(pnr, lastname, airline, firstname)
            logger.info(f"  SriLankan PNR {pnr}: {status_result['status']}")
            results = _build_results_for_group(pnr, rows, status_result, old_statuses)
            all_results.extend(results)

    # ── Phase 3: Remaining airlines — sequential (one by one) ─────────
    if other_pnrs:
        logger.info(f"═══ Phase 3: Other airlines — {len(other_pnrs)} unique PNR(s), one by one ═══")
        for i, ((pnr, airline), rows) in enumerate(other_pnrs.items(), 1):
            lastname, firstname, _ = _resolve_passenger_info(rows[0])
            old_statuses = {row['id']: row['status'] for row in rows}
            logger.info(f"  [{i}/{len(other_pnrs)}] {airline.upper()} PNR={pnr}")

            status_result = _check_single_pnr(pnr, lastname, airline, firstname)
            logger.info(f"  {airline.upper()} PNR {pnr}: {status_result['status']}")
            results = _build_results_for_group(pnr, rows, status_result, old_statuses)
            all_results.extend(results)

    logger.info(f"All phases complete — {len(all_results)} result(s) from {total_unique} unique PNR(s)")
    return all_results


def run_hourly_check():
    """
    Hourly silent check. Only sends an URGENT email if any PNR
    is Cancelled or Rescheduled.
    """
    logger.info(f"=== Hourly silent check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    results = _check_all_pnrs()
    if not results:
        return

    # Filter for urgent alerts (cancelled/rescheduled)
    urgent = [r for r in results if r['status'] in ALERT_STATUSES and r['status_changed']]

    if urgent:
        logger.warning(f"🚨 URGENT: {len(urgent)} PNR(s) cancelled/rescheduled!")
        success = send_urgent_alert(urgent)
        if success:
            logger.info("Urgent alert email sent!")
        else:
            logger.error("Failed to send urgent alert email")
    else:
        logger.info("Hourly check complete — no cancellations detected")


def run_full_report():
    """
    Scheduled full report (8 AM & 6 PM). Sends status of ALL active PNRs.
    Also sends urgent alert immediately if any cancellations found.
    """
    logger.info(f"=== Full status report at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    results = _check_all_pnrs()
    if not results:
        return

    # Check for urgent items first
    urgent = [r for r in results if r['status'] in ALERT_STATUSES and r['status_changed']]
    if urgent:
        logger.warning(f"🚨 URGENT: {len(urgent)} PNR(s) cancelled/rescheduled!")
        send_urgent_alert(urgent)

    # Send full report
    success = send_status_email(results)
    if success:
        logger.info(f"Full status email sent with {len(results)} booking(s)")
    else:
        logger.error("Failed to send full status email")

    logger.info("=== Full status report complete ===")


def run_status_check():
    """Backward-compatible wrapper — runs full report."""
    run_full_report()


# Module-level singleton — prevents duplicate schedulers if setup is called twice
_scheduler_instance = None


def setup_scheduler(app=None):
    """
    Set up APScheduler with full status reports at 8 AM & 6 PM IST only.
    Idempotent — calling twice returns the same instance (no duplicate jobs).
    """
    global _scheduler_instance
    if _scheduler_instance is not None and _scheduler_instance.running:
        logger.warning("Scheduler already running — returning existing instance (no duplicate jobs)")
        return _scheduler_instance

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    ist = pytz.timezone('Asia/Kolkata')
    scheduler = BackgroundScheduler(timezone=ist)

    # Full reports at 8 AM and 6 PM IST
    check_times = os.getenv('CHECK_TIMES', '08:00,18:00')
    times = [t.strip() for t in check_times.split(',')]

    for time_str in times:
        try:
            hour, minute = time_str.split(':')
            trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=ist)
            scheduler.add_job(
                run_full_report, trigger,
                id=f'full_report_{time_str}',
                name=f'Full Status Report at {time_str} IST',
                replace_existing=True,
            )
            logger.info(f"Scheduled full report at {time_str} IST")
        except ValueError as e:
            logger.error(f"Invalid time format '{time_str}': {e}")

    scheduler.start()
    _scheduler_instance = scheduler
    logger.info("Scheduler started — checks at 8 AM & 6 PM IST only")
    return scheduler


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_full_report()
