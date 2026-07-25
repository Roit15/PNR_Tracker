"""
Flask Web Application for PNR Tracker.
Upload Indigo booking PDFs, view tracked PNRs, trigger manual checks.
"""

import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from database import init_db, add_booking, get_active_bookings, get_booking, delete_booking, deactivate_past_bookings, update_booking_status, get_completed_bookings
from pdf_parser import parse_booking
from scheduler import run_status_check, setup_scheduler
from scraper_router import check_pnr_by_airline
import scraper as scraper_module
import threading
import concurrent.futures

# Global check state — tracks whether a bulk check is running
check_state = {
    'running': False,
    'stop_requested': False,
    'current_pnr': None,
    'checked': 0,
    'total': 0,
    'started_at': None,
    'thread': None,
}

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'pnr-tracker-secret-key-change-me')

from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=0)

# Strip /pnr prefix so the app works at BOTH localhost:8080/ and balireserve.com/pnr/
class PathPrefixMiddleware:
    """If the request path starts with /pnr, strip it before Flask sees it."""
    def __init__(self, app):
        self.app = app
    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '/')
        if path.startswith('/pnr'):
            environ['PATH_INFO'] = path[4:] or '/'
            environ['SCRIPT_NAME'] = '/pnr'
        return self.app(environ, start_response)

app.wsgi_app = PathPrefixMiddleware(app.wsgi_app)

# Disable browser caching so updates are always visible
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ---------- Jinja Template Filters ----------
@app.template_filter('format_date')
def format_date_filter(value):
    """Convert ISO date (2026-04-24) to human format (24 Apr 2026)."""
    if not value:
        return '—'
    try:
        dt = datetime.strptime(str(value).strip(), '%Y-%m-%d')
        return dt.strftime('%-d %b %Y')
    except (ValueError, AttributeError):
        return value


@app.template_filter('time_ago')
def time_ago_filter(value):
    """Convert timestamp to relative time (2h ago, Yesterday 3:14 PM, etc.)."""
    if not value:
        return 'Not yet'
    try:
        dt = datetime.strptime(str(value).strip(), '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        diff = now - dt

        if diff.total_seconds() < 60:
            return 'Just now'
        elif diff.total_seconds() < 3600:
            mins = int(diff.total_seconds() / 60)
            return f'{mins}m ago'
        elif diff.total_seconds() < 86400 and dt.date() == now.date():
            return f'Today, {dt.strftime("%-I:%M %p")}'
        elif diff.total_seconds() < 172800 and dt.date() == (now - timedelta(days=1)).date():
            return f'Yesterday, {dt.strftime("%-I:%M %p")}'
        else:
            return dt.strftime('%-d %b, %-I:%M %p')
    except (ValueError, AttributeError):
        return value


@app.template_filter('format_time')
def format_time_filter(value):
    """Format departure/arrival time for display."""
    if not value or value == '—':
        return '—'
    return value


# Upload config
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

ALLOWED_EXTENSIONS = {'pdf'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    """Dashboard showing all tracked PNRs."""
    deactivate_past_bookings()
    bookings = get_active_bookings()
    completed = get_completed_bookings()

    # Calculate next auto-check time
    now = datetime.now()
    check_times_str = os.getenv('CHECK_TIMES', '08:00,18:00')
    check_times = sorted([t.strip() for t in check_times_str.split(',')])
    next_check = None
    for t in check_times:
        try:
            h, m = t.split(':')
            candidate = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            if candidate > now:
                next_check = candidate.strftime('%-I:%M %p IST')
                break
        except ValueError:
            pass
    if not next_check and check_times:
        next_check = f'{check_times[0]} IST (tomorrow)'

    # Detect round-trip pairs: same passenger full name + reversed route
    all_bookings = list(bookings) + list(completed)
    trip_links = {}  # pnr -> { 'paired_pnr': ..., 'paired_route': ..., 'paired_date': ..., 'direction': 'outbound'|'return' }
    for i, b1 in enumerate(all_bookings):
        if b1['pnr'] in trip_links:
            continue
        route1 = (b1['route'] or '').strip()
        name1 = (b1['passenger_name'] or '').strip().lower()
        if not route1 or '-' not in route1 or not name1:
            continue
        parts1 = route1.split('-')
        if len(parts1) != 2:
            continue
        reverse_route = f"{parts1[1]}-{parts1[0]}"
        for j, b2 in enumerate(all_bookings):
            if i == j or b2['pnr'] == b1['pnr'] or b2['pnr'] in trip_links:
                continue
            route2 = (b2['route'] or '').strip()
            name2 = (b2['passenger_name'] or '').strip().lower()
            if route2 == reverse_route and name1 == name2:
                # Determine which is outbound (earlier date) and which is return
                date1 = b1['flight_date'] or ''
                date2 = b2['flight_date'] or ''
                if date1 <= date2:
                    trip_links[b1['pnr']] = {'paired_pnr': b2['pnr'], 'paired_route': route2, 'paired_date': date2, 'direction': 'outbound'}
                    trip_links[b2['pnr']] = {'paired_pnr': b1['pnr'], 'paired_route': route1, 'paired_date': date1, 'direction': 'return'}
                else:
                    trip_links[b1['pnr']] = {'paired_pnr': b2['pnr'], 'paired_route': route2, 'paired_date': date2, 'direction': 'return'}
                    trip_links[b2['pnr']] = {'paired_pnr': b1['pnr'], 'paired_route': route1, 'paired_date': date1, 'direction': 'outbound'}
                break

    return render_template('index.html', bookings=bookings, completed=completed,
                           now=datetime.now(), next_check=next_check,
                           check_running=check_state['running'],
                           check_progress=check_state,
                           trip_links=trip_links)


@app.route('/upload', methods=['POST'])
def upload():
    """Upload and parse booking confirmation PDFs (IndiGo or Air India — auto-detected)."""
    files = request.files.getlist('files[]')

    if not files or all(f.filename == '' for f in files):
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    total_added = 0
    total_skipped = 0
    errors = []

    for file in files:
        if file.filename == '':
            continue
        if not allowed_file(file.filename):
            errors.append(f'{file.filename}: not a PDF')
            continue

        try:
            # Save the uploaded file
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File uploaded: {filepath}")

            # Parse the PDF
            bookings = parse_booking(filepath)

            for booking in bookings:
                airline = booking.get('airline', 'indigo')
                result = add_booking(
                    pnr=booking['pnr'],
                    passenger_name=booking['passenger_name'],
                    flight_number=booking['flight_number'],
                    route=booking['route'],
                    flight_date=booking['flight_date'],
                    departure_time=booking.get('departure_time'),
                    arrival_time=booking.get('arrival_time'),
                    passenger_lastname=booking.get('passenger_lastname'),
                    passenger_firstname=booking.get('passenger_firstname'),
                    airline=airline,
                    passenger_count=booking.get('passenger_count', 1),
                )
                if result:
                    total_added += 1
                    logger.info(f"Added {_airline_label(airline)} booking: PNR={booking['pnr']}, "
                              f"Flight={booking['flight_number']}, "
                              f"Route={booking['route']}, "
                              f"Date={booking['flight_date']}")
                else:
                    total_skipped += 1

        except ValueError as e:
            errors.append(f'{file.filename}: {str(e)}')
            logger.error(f"PDF parse error ({file.filename}): {e}")
        except Exception as e:
            errors.append(f'{file.filename}: {str(e)}')
            logger.error(f"Upload error ({file.filename}): {e}")

    if total_added > 0:
        flash(f'✅ Added {total_added} booking(s) for tracking!', 'success')
    if total_skipped > 0:
        flash(f'ℹ️ Skipped {total_skipped} booking(s) — already being tracked.', 'info')
    for err in errors:
        flash(f'⚠️ {err}', 'error')

    return redirect(url_for('index'))


def _airline_label(airline):
    return {'airindia': 'Air India', 'vietjet': 'VietJet Air', 'singaporeair': 'Singapore Airlines', 'akasaair': 'Akasa Air', 'etihad': 'Etihad Airways'}.get(airline, 'IndiGo')


@app.route('/add_manual', methods=['POST'])
def add_manual():
    """Manually add a PNR to track (IndiGo, Air India, or VietJet)."""
    pnr = request.form.get('pnr', '').strip().upper()
    lastname = request.form.get('lastname', '').strip()
    firstname = request.form.get('firstname', '').strip()
    airline = request.form.get('airline', 'indigo').strip().lower()

    if not pnr or not lastname:
        flash('Please provide both PNR and Last Name.', 'error')
        return redirect(url_for('index'))

    label = _airline_label(airline)

    try:
        flash(f'Fetching details for {pnr} from {label}...', 'info')
        result = check_pnr_by_airline(pnr, lastname, airline, firstname)

        if result['status'] in ('Not Found', 'Error'):
            flash(f"Could not verify PNR on {label}: {result['detail']}", 'error')
            return redirect(url_for('index'))

        # flight_info is now a list of segments (1 for one-way, 2 for round-trip)
        segments = result.get('flight_info', [{}])
        if isinstance(segments, dict):  # backward compat
            segments = [segments]

        total_added = 0
        for seg in segments:
            flight_date = seg.get('flight_date')
            if not flight_date:
                if result['status'] in ('Cancelled', 'Payment Pending'):
                    flight_date = datetime.now().strftime('%Y-%m-%d')
                    logger.info(f"No flight date found for cancelled PNR {pnr}, using today's date as fallback")
                else:
                    continue  # skip segment without date

            fetched_name = seg.get('passenger_name') or f"{firstname} {lastname}".strip() or lastname

            added = add_booking(
                pnr=pnr,
                passenger_name=fetched_name,
                flight_number=seg.get('flight_number', ''),
                route=seg.get('route', ''),
                flight_date=flight_date,
                departure_time=seg.get('departure_time', ''),
                arrival_time=seg.get('arrival_time', ''),
                passenger_lastname=lastname,
                passenger_firstname=firstname or None,
                airline=airline,
                passenger_count=seg.get('passenger_count', 1)
            )
            if added:
                total_added += 1

        pax = segments[0].get('passenger_count') if segments else None
        if total_added > 0:
            update_booking_status(pnr, result['status'], result['detail'], pax)
            seg_label = f'{total_added} segment(s)' if total_added > 1 else 'PNR'
            flash(f'✅ Auto-fetched and added {label} {seg_label} {pnr} for tracking!', 'success')
        else:
            if segments and any(s.get('flight_date') for s in segments):
                update_booking_status(pnr, result['status'], result['detail'], pax)
                flash(f'ℹ️ PNR {pnr} is already being tracked. Status synced.', 'info')
            else:
                flash(f'Verified PNR {pnr}, but failed to auto-extract flight details.', 'error')

    except Exception as e:
        flash(f'Error adding PNR manually: {str(e)}', 'error')
        logger.error(f"Manual auto-add error: {e}")

    return redirect(url_for('index'))

@app.route('/delete/<int:booking_id>', methods=['POST'])
def delete(booking_id):
    """Remove a booking from tracking."""
    delete_booking(booking_id)
    flash('Booking removed from tracking', 'success')
    return redirect(url_for('index'))


@app.route('/check/<int:booking_id>', methods=['POST'])
def check_single(booking_id):
    """Trigger an immediate status check for a single PNR."""
    from database import update_booking_status
    
    booking = get_booking(booking_id)
    if not booking:
        flash('Booking not found', 'error')
        return redirect(url_for('index'))

    pnr = booking['pnr']
    lastname = booking['passenger_lastname'] if 'passenger_lastname' in booking.keys() and booking['passenger_lastname'] else ''
    if not lastname and 'passenger_name' in booking.keys() and booking['passenger_name']:
        parts = booking['passenger_name'].strip().split()
        lastname = parts[-1] if parts else ''

    airline = booking['airline'] if 'airline' in booking.keys() else 'indigo'
    firstname = booking['passenger_firstname'] if 'passenger_firstname' in booking.keys() else ''
    label = _airline_label(airline)

    try:
        flash(f'🔄 Checking status for {pnr} on {label}...', 'info')
        status_result = check_pnr_by_airline(pnr, lastname, airline, firstname or '')

        # Discover and add any missing segments (e.g., return leg of a round-trip)
        segments = status_result.get('flight_info', [])
        if isinstance(segments, dict):
            segments = [segments]

        pax = segments[0].get('passenger_count') if segments else None
        update_booking_status(pnr, status_result['status'], status_result['detail'], pax)
        for seg in segments:
            if seg.get('flight_date') and seg.get('route'):
                fetched_name = seg.get('passenger_name') or booking['passenger_name']
                add_booking(
                    pnr=pnr,
                    passenger_name=fetched_name,
                    flight_number=seg.get('flight_number', ''),
                    route=seg.get('route', ''),
                    flight_date=seg.get('flight_date'),
                    departure_time=seg.get('departure_time', ''),
                    arrival_time=seg.get('arrival_time', ''),
                    passenger_lastname=lastname,
                    passenger_firstname=firstname or None,
                    airline=airline,
                    passenger_count=seg.get('passenger_count', 1)
                )

        flash(f'✅ Status for PNR {pnr} updated to {status_result["status"]}', 'success')
    except Exception as e:
        flash(f'Error checking PNR {pnr}: {str(e)}', 'error')
        logger.error(f"Manual check error for {pnr}: {e}")

        
    return redirect(url_for('index'))


@app.route('/check-now', methods=['POST'])
def check_now():
    """Trigger an immediate status check for all PNRs in a background thread."""
    if check_state['running']:
        flash('⏳ A check is already in progress...', 'info')
        return redirect(url_for('index'))

    bookings = get_active_bookings()
    if not bookings:
        flash('No active bookings to check.', 'info')
        return redirect(url_for('index'))

    check_state['running'] = True
    check_state['stop_requested'] = False
    check_state['checked'] = 0
    check_state['total'] = len(bookings)
    check_state['started_at'] = datetime.now().strftime('%H:%M:%S')
    check_state['current_pnr'] = None

    def _run_check():
        try:
            def _check_single(booking):
                if check_state['stop_requested']:
                    return
                pnr = booking['pnr']
                check_state['current_pnr'] = pnr
                
                lastname = booking['passenger_lastname'] if 'passenger_lastname' in booking.keys() and booking['passenger_lastname'] else ''
                if not lastname and booking['passenger_name']:
                    parts = booking['passenger_name'].strip().split()
                    lastname = parts[-1] if parts else ''
                airline = booking['airline'] if 'airline' in booking.keys() else 'indigo'
                firstname = booking['passenger_firstname'] if 'passenger_firstname' in booking.keys() and booking['passenger_firstname'] else ''

                try:
                    status_result = check_pnr_by_airline(pnr, lastname, airline, firstname or '')

                    # Discover and add any missing segments (e.g., return leg)
                    segments = status_result.get('flight_info', [])
                    if isinstance(segments, dict):
                        segments = [segments]

                    pax = segments[0].get('passenger_count') if segments else None
                    update_booking_status(pnr, status_result['status'], status_result['detail'], pax)
                    for seg in segments:
                        if seg.get('flight_date') and seg.get('route'):
                            fetched_name = seg.get('passenger_name') or booking['passenger_name']
                            add_booking(
                                pnr=pnr,
                                passenger_name=fetched_name,
                                flight_number=seg.get('flight_number', ''),
                                route=seg.get('route', ''),
                                flight_date=seg.get('flight_date'),
                                departure_time=seg.get('departure_time', ''),
                                arrival_time=seg.get('arrival_time', ''),
                                passenger_lastname=booking['passenger_lastname'] if 'passenger_lastname' in booking.keys() else '',
                                passenger_firstname=booking['passenger_firstname'] if 'passenger_firstname' in booking.keys() else None,
                                airline=airline,
                                passenger_count=seg.get('passenger_count', 1)
                            )

                    logger.info(f"Checked {pnr}: {status_result['status']}")
                except Exception as e:
                    logger.error(f"Error checking {pnr}: {e}")
                finally:
                    check_state['checked'] += 1

            # Run checks sequentially (or low concurrency) to prevent Chrome from crashing
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(_check_single, b) for b in bookings]
                concurrent.futures.wait(futures)

            if check_state['stop_requested']:
                logger.info("Check stopped by user")
        except Exception as e:
            logger.error(f"Bulk check error: {e}")
        finally:
            check_state['running'] = False
            check_state['current_pnr'] = None

    t = threading.Thread(target=_run_check, daemon=True)
    check_state['thread'] = t
    t.start()

    flash(f'🔄 Checking {len(bookings)} PNRs in the background...', 'info')
    return redirect(url_for('index'))


@app.route('/stop-check', methods=['POST'])
def stop_check():
    """Request cancellation of the current bulk check."""
    if check_state['running']:
        check_state['stop_requested'] = True
        flash(f'🛑 Stopping check... ({check_state["checked"]}/{check_state["total"]} completed)', 'info')
    else:
        flash('No check is currently running.', 'info')
    return redirect(url_for('index'))


@app.route('/api/check-status')
def api_check_status():
    """API endpoint for the UI to poll check progress."""
    return jsonify({
        'running': check_state['running'],
        'stop_requested': check_state['stop_requested'],
        'current_pnr': check_state['current_pnr'],
        'checked': check_state['checked'],
        'total': check_state['total'],
        'started_at': check_state['started_at'],
    })


@app.route('/api/bookings')
def api_bookings():
    """API endpoint to get all active bookings as JSON."""
    bookings = get_active_bookings()
    return jsonify([dict(b) for b in bookings])

from ai_insights import generate_flight_insights

# Simple in-memory cache for insights
insights_cache = {'data': None, 'timestamp': None}

@app.route('/api/insights')
def api_insights():
    """API endpoint to get AI insights for the active bookings with caching."""
    global insights_cache
    now = datetime.now()
    
    # Return cached insights if they are less than 10 minutes old
    if insights_cache['data'] and insights_cache['timestamp'] and (now - insights_cache['timestamp']) < timedelta(minutes=10):
        return jsonify({'insights': insights_cache['data']})
        
    bookings = get_active_bookings()
    insights = generate_flight_insights([dict(b) for b in bookings])
    
    # Only cache if it didn't fail
    if not insights.startswith("Could not generate") and not insights.startswith("✨ **AI"):
        insights_cache['data'] = insights
        insights_cache['timestamp'] = now
        
    return jsonify({'insights': insights})


# Initialize
init_db()

if __name__ == '__main__':
    # Start the scheduler
    scheduler = setup_scheduler()

    # Render sets PORT; fallback to FLASK_PORT or 8080
    port = int(os.getenv('PORT', os.getenv('FLASK_PORT', 8080)))
    logger.info(f"PNR Tracker started! Listening on port {port}")

    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    finally:
        scheduler.shutdown()
