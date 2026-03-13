"""
Email notification module for PNR Tracker.
Sends styled HTML status emails via Gmail SMTP.
"""

import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def send_status_email(bookings_with_status):
    """
    Send an HTML email with the status of all active PNRs.

    Args:
        bookings_with_status: list of dicts, each with:
            - pnr, passenger_name, flight_number, route, flight_date
            - status, detail
    """
    smtp_email = os.getenv('SMTP_EMAIL')
    smtp_password = os.getenv('SMTP_PASSWORD')
    recipient = os.getenv('RECIPIENT_EMAIL', smtp_email)

    if not smtp_email or not smtp_password:
        logger.error("SMTP credentials not configured. Set SMTP_EMAIL and SMTP_PASSWORD in .env")
        return False

    # Build email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"✈️ Indigo PNR Status Update — {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
    msg['From'] = smtp_email
    msg['To'] = recipient

    html_body = build_html_email(bookings_with_status)
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, recipient, msg.as_string())
            logger.info(f"Status email sent to {recipient}")
            return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_urgent_alert(cancelled_bookings):
    """
    Send an urgent alert email when PNRs are cancelled or rescheduled.
    Red-themed email for immediate attention.
    """
    smtp_email = os.getenv('SMTP_EMAIL')
    smtp_password = os.getenv('SMTP_PASSWORD')
    recipient = os.getenv('RECIPIENT_EMAIL', smtp_email)

    if not smtp_email or not smtp_password:
        logger.error("SMTP credentials not configured")
        return False

    pnr_list = ', '.join([b['pnr'] for b in cancelled_bookings])
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🚨 URGENT: IndiGo Flight CANCELLED — PNR {pnr_list}"
    msg['From'] = smtp_email
    msg['To'] = recipient

    html_body = build_urgent_html(cancelled_bookings)
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, recipient, msg.as_string())
            logger.info(f"🚨 Urgent alert sent to {recipient} for PNRs: {pnr_list}")
            return True
    except Exception as e:
        logger.error(f"Failed to send urgent alert: {e}")
        return False


def build_urgent_html(bookings):
    """Build red/urgent HTML email for cancellations."""
    now = datetime.now().strftime('%d %b %Y at %I:%M %p IST')

    rows = ""
    for b in bookings:
        rows += f"""
        <tr>
            <td style="padding: 14px 16px; border-bottom: 1px solid #fecaca; font-weight: 700; color: #991b1b; font-size: 16px;">{b.get('pnr', 'N/A')}</td>
            <td style="padding: 14px 16px; border-bottom: 1px solid #fecaca;">{b.get('passenger_name', 'N/A')}</td>
            <td style="padding: 14px 16px; border-bottom: 1px solid #fecaca;">{b.get('flight_number', 'N/A')}</td>
            <td style="padding: 14px 16px; border-bottom: 1px solid #fecaca;">{b.get('route', 'N/A')}</td>
            <td style="padding: 14px 16px; border-bottom: 1px solid #fecaca;">{b.get('flight_date', 'N/A')}</td>
            <td style="padding: 14px 16px; border-bottom: 1px solid #fecaca;">
                <span style="background: #dc2626; color: white; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 700;">{b.get('status', 'Cancelled')}</span>
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fef2f2;">
        <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
            <div style="background: linear-gradient(135deg, #991b1b 0%, #dc2626 100%); padding: 32px 24px; border-radius: 16px 16px 0 0; text-align: center;">
                <h1 style="margin: 0; color: white; font-size: 28px; font-weight: 800;">🚨 FLIGHT CANCELLED</h1>
                <p style="margin: 12px 0 0; color: rgba(255,255,255,0.9); font-size: 15px;">Detected at {now}</p>
                <p style="margin: 8px 0 0; color: rgba(255,255,255,0.7); font-size: 13px;">This is an automated urgent alert from PNR Tracker</p>
            </div>

            <div style="background: white; padding: 0; border-radius: 0 0 16px 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.12);">
                <div style="padding: 20px 24px; background: #fef2f2; border-bottom: 2px solid #fecaca;">
                    <p style="margin: 0; color: #991b1b; font-weight: 600; font-size: 15px;">
                        ⚠️ {len(bookings)} booking(s) has been cancelled or rescheduled. Please check your IndiGo account immediately.
                    </p>
                </div>

                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: #fff5f5;">
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #991b1b; letter-spacing: 0.5px;">PNR</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #991b1b; letter-spacing: 0.5px;">Passenger</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #991b1b; letter-spacing: 0.5px;">Flight</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #991b1b; letter-spacing: 0.5px;">Route</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #991b1b; letter-spacing: 0.5px;">Date</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #991b1b; letter-spacing: 0.5px;">Status</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>

                <div style="padding: 20px 24px; border-top: 1px solid #fecaca; text-align: center;">
                    <a href="https://www.goindigo.in/account/my-bookings.html" style="display: inline-block; background: #dc2626; color: white; padding: 12px 32px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px;">Check on IndiGo Website →</a>
                </div>

                <div style="padding: 16px 24px; border-top: 1px solid #f1f5f9; text-align: center;">
                    <p style="margin: 0; color: #94a3b8; font-size: 12px;">PNR Tracker • Hourly monitoring active</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


def build_html_email(bookings):
    """Build a styled HTML email body."""
    now = datetime.now().strftime('%d %b %Y at %I:%M %p IST')

    status_colors = {
        'Confirmed': '#22c55e',
        'Check-in Open': '#3b82f6',
        'Delayed': '#f59e0b',
        'Rescheduled': '#f97316',
        'Cancelled': '#ef4444',
        'Not Found': '#6b7280',
        'Error': '#ef4444',
        'Completed': '#8b5cf6',
        'Checked': '#6b7280',
        'Pending Check': '#9ca3af',
    }

    rows_html = ""
    for b in bookings:
        status = b.get('status', 'Unknown')
        color = status_colors.get(status, '#6b7280')
        detail = b.get('detail', '')
        if len(detail) > 100:
            detail = detail[:100] + '...'

        rows_html += f"""
        <tr>
            <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb; font-weight: 600; color: #1e3a5f;">{b.get('pnr', 'N/A')}</td>
            <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">{b.get('passenger_name', 'N/A')}</td>
            <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">{b.get('flight_number', 'N/A')}</td>
            <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">{b.get('route', 'N/A')}</td>
            <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">{b.get('flight_date', 'N/A')}</td>
            <td style="padding: 12px 16px; border-bottom: 1px solid #e5e7eb;">
                <span style="background: {color}; color: white; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 600;">{status}</span>
            </td>
        </tr>
        """
        if detail and detail != 'Booking confirmed':
            rows_html += f"""
            <tr>
                <td colspan="6" style="padding: 4px 16px 12px 16px; border-bottom: 1px solid #e5e7eb; color: #6b7280; font-size: 13px;">📋 {detail}</td>
            </tr>
            """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f4f8;">
        <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%); padding: 32px 24px; border-radius: 16px 16px 0 0; text-align: center;">
                <h1 style="margin: 0; color: white; font-size: 24px; font-weight: 700;">✈️ IndiGo PNR Status</h1>
                <p style="margin: 8px 0 0; color: rgba(255,255,255,0.8); font-size: 14px;">Checked on {now}</p>
            </div>

            <!-- Content -->
            <div style="background: white; padding: 0; border-radius: 0 0 16px 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: #f8fafc;">
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">PNR</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Passenger</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Flight</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Route</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Date</th>
                            <th style="padding: 14px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>

                {f'<p style="padding: 24px; text-align: center; color: #9ca3af; font-size: 14px;">No active bookings to track.</p>' if not bookings else ''}

                <!-- Footer -->
                <div style="padding: 20px 24px; border-top: 1px solid #f1f5f9; text-align: center;">
                    <p style="margin: 0; color: #94a3b8; font-size: 12px;">
                        PNR Tracker • Auto-checked at 8 AM & 6 PM IST
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html


if __name__ == '__main__':
    # Test email
    test_bookings = [
        {
            'pnr': 'S9RWSJ',
            'passenger_name': 'Manik Chopra',
            'flight_number': '6E 1081',
            'route': 'DEL-HKT',
            'flight_date': '2026-04-24',
            'status': 'Confirmed',
            'detail': 'Booking confirmed. Departure at 15:40 hrs from Terminal 3.',
        }
    ]
    success = send_status_email(test_bookings)
    print(f"Email sent: {success}")
