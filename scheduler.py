"""
Scheduler module for PNR Tracker.
- Hourly: silent check — only sends URGENT email if any PNR is cancelled/rescheduled
- 8 AM & 6 PM IST: full status report email of all PNRs
"""

import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from database import get_bookings_to_check, update_booking_status, deactivate_past_bookings
from scraper import check_pnr_status
from emailer import send_status_email, send_urgent_alert

load_dotenv()
logger = logging.getLogger(__name__)

# Statuses that trigger an immediate urgent alert
ALERT_STATUSES = {'Cancelled', 'Rescheduled'}


def _check_all_pnrs():
    """
    Check status of all active PNRs. Returns list of results.
    Shared logic used by both hourly and scheduled checks.
    """
    deactivated = deactivate_past_bookings()
    if deactivated:
        logger.info(f"Deactivated {deactivated} past booking(s)")

    bookings = get_bookings_to_check()
    if not bookings:
        logger.info("No active bookings to check")
        return []

    logger.info(f"Checking {len(bookings)} active booking(s)")
    results = []

    for booking in bookings:
        pnr = booking['pnr']
        old_status = booking['status']
        # Use per-booking last name; fall back to env var, then extract from full name
        lastname = booking['passenger_lastname'] or ''
        if not lastname:
            lastname = os.getenv('PASSENGER_LASTNAME', '')
        if not lastname and booking['passenger_name']:
            parts = booking['passenger_name'].strip().split()
            lastname = parts[-1] if parts else ''
        logger.info(f"Checking PNR: {pnr} ({booking['flight_number']} {booking['route']}) lastname={lastname}")

        try:
            status_result = check_pnr_status(pnr, lastname)
            update_booking_status(pnr, status_result['status'], status_result['detail'])

            results.append({
                'pnr': pnr,
                'passenger_name': booking['passenger_name'],
                'flight_number': booking['flight_number'],
                'route': booking['route'],
                'flight_date': booking['flight_date'],
                'status': status_result['status'],
                'detail': status_result['detail'],
                'old_status': old_status,
                'status_changed': old_status != status_result['status'],
            })
            logger.info(f"PNR {pnr}: {old_status} → {status_result['status']}")

        except Exception as e:
            logger.error(f"Error checking PNR {pnr}: {e}")
            results.append({
                'pnr': pnr,
                'passenger_name': booking['passenger_name'],
                'flight_number': booking['flight_number'],
                'route': booking['route'],
                'flight_date': booking['flight_date'],
                'status': 'Error',
                'detail': str(e),
                'old_status': old_status,
                'status_changed': False,
            })

    return results


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


def setup_scheduler(app=None):
    """
    Set up APScheduler with full status reports at 8 AM & 6 PM IST only.
    """
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
    logger.info("Scheduler started — checks at 8 AM & 6 PM IST only")
    return scheduler


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_full_report()
