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

from database import init_db, add_booking, get_active_bookings, delete_booking, deactivate_past_bookings
from pdf_parser import parse_booking
from scheduler import run_status_check, setup_scheduler

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
    return render_template('index.html', bookings=bookings, now=datetime.now())


@app.route('/upload', methods=['POST'])
def upload():
    """Upload and parse an Indigo booking confirmation PDF."""
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    if not allowed_file(file.filename):
        flash('Only PDF files are allowed', 'error')
        return redirect(url_for('index'))

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

        added_count = 0
        skipped_count = 0
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
                added_count += 1
                logger.info(f"Added booking: PNR={booking['pnr']}, "
                          f"Flight={booking['flight_number']}, "
                          f"Route={booking['route']}, "
                          f"Date={booking['flight_date']}")
            else:
                skipped_count += 1

        if added_count > 0:
            flash(f'✅ Added {added_count} booking(s) for tracking!', 'success')
        if skipped_count > 0:
            flash(f'ℹ️ Skipped {skipped_count} booking(s) — already being tracked.', 'info')

    except ValueError as e:
        flash(f'Could not parse PDF: {str(e)}', 'error')
        logger.error(f"PDF parse error: {e}")
    except Exception as e:
        flash(f'Error processing file: {str(e)}', 'error')
        logger.error(f"Upload error: {e}")

    return redirect(url_for('index'))


@app.route('/delete/<int:booking_id>', methods=['POST'])
def delete(booking_id):
    """Remove a booking from tracking."""
    delete_booking(booking_id)
    flash('Booking removed from tracking', 'success')
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
    logger.info("PNR Tracker started! Dashboard at http://localhost:5000")

    port = int(os.getenv('FLASK_PORT', 5000))
    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    finally:
        scheduler.shutdown()
