"""
Flask Web Application for PNR Tracker.
Upload Indigo booking PDFs, view tracked PNRs, trigger manual checks.
"""

import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from database import init_db, add_booking, get_active_bookings, get_booking, delete_booking, deactivate_past_bookings, update_booking_status, get_completed_bookings
from pdf_parser import parse_booking
from scheduler import run_status_check, setup_scheduler
from scraper import check_pnr_status
import scraper as scraper_module

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
    return render_template('index.html', bookings=bookings, completed=completed, now=datetime.now())


@app.route('/upload', methods=['POST'])
def upload():
    """Upload and parse one or more Indigo booking confirmation PDFs."""
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
                result = add_booking(
                    pnr=booking['pnr'],
                    passenger_name=booking['passenger_name'],
                    flight_number=booking['flight_number'],
                    route=booking['route'],
                    flight_date=booking['flight_date'],
                    departure_time=booking.get('departure_time'),
                    arrival_time=booking.get('arrival_time'),
                )
                if result:
                    total_added += 1
                    logger.info(f"Added booking: PNR={booking['pnr']}, "
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


@app.route('/add_manual', methods=['POST'])
def add_manual():
    """Manually add a PNR and Last Name to track by instant-checking Indigo."""
    pnr = request.form.get('pnr', '').strip().upper()
    lastname = request.form.get('lastname', '').strip()

    if not pnr or not lastname:
        flash('Please provide both PNR and Last Name.', 'error')
        return redirect(url_for('index'))

    # Verify via scraper
    try:
        flash(f'Fetching details for {pnr} from IndiGo in the background...', 'info')
        result = check_pnr_status(pnr, lastname)
        
        if result['status'] in ('Not Found', 'Error'):
            flash(f"Could not verify PNR on IndiGo: {result['detail']}", 'error')
            return redirect(url_for('index'))
            
        flight_info = result.get('flight_info', {})
        flight_date = flight_info.get('flight_date')

        if not flight_date:
            flash(f'Verified PNR {pnr}, but failed to auto-extract the Flight Date. Cannot track properly.', 'error')
            return redirect(url_for('index'))

        # Add tracking using the extracted details
        fetched_name = flight_info.get('passenger_name') or lastname
        
        added = add_booking(
            pnr=pnr,
            passenger_name=fetched_name,
            flight_number=flight_info.get('flight_number', ''),
            route=flight_info.get('route', ''),
            flight_date=flight_date,
            departure_time=flight_info.get('departure_time', ''),
            arrival_time=flight_info.get('arrival_time', ''),
            passenger_lastname=lastname
        )
        if added:
            # Pre-set the initial status
            update_booking_status(pnr, result['status'], result['detail'])
            flash(f'✅ Auto-fetched and added PNR {pnr} for tracking!', 'success')
        else:
            flash(f'ℹ️ PNR {pnr} is already being tracked.', 'info')
            
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
    # If it's a newer database with passenger_lastname, use it. Otherwise fallback to splitting passenger_name.
    lastname = booking['passenger_lastname'] if 'passenger_lastname' in booking.keys() and booking['passenger_lastname'] else ''
    if not lastname and 'passenger_name' in booking.keys() and booking['passenger_name']:
        parts = booking['passenger_name'].strip().split()
        lastname = parts[-1] if parts else ''
        
    try:
        flash(f'🔄 Checking status for {pnr}...', 'info')
        # We process the check immediately rather than in background since user clicked specifically for this PNR.
        status_result = check_pnr_status(pnr, lastname)
        update_booking_status(pnr, status_result['status'], status_result['detail'])
        flash(f'✅ Status for PNR {pnr} updated to {status_result["status"]}', 'success')
    except Exception as e:
        flash(f'Error checking PNR {pnr}: {str(e)}', 'error')
        logger.error(f"Manual check error for {pnr}: {e}")
        
    return redirect(url_for('index'))


@app.route('/check-now', methods=['POST'])
def check_now():
    """Trigger an immediate status check for all PNRs."""
    try:
        flash('🔄 Status check started! This may take a minute...', 'info')
        run_status_check()
        flash('✅ Status check complete! Check your email.', 'success')
    except Exception as e:
        flash(f'Error during status check: {str(e)}', 'error')
        logger.error(f"Manual check error: {e}")
    return redirect(url_for('index'))


@app.route('/api/bookings')
def api_bookings():
    """API endpoint to get all active bookings as JSON."""
    bookings = get_active_bookings()
    return jsonify([dict(b) for b in bookings])


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
