import re

with open('templates/index.html', 'r') as f:
    html = f.read()

# Replace mobile flight card for active bookings
active_card_pattern = r'<div class="flight-card status-border-\{\{ booking\.status\|lower\|replace\(\' \', \'-\'\) \}\}"[^>]*>.*?</div>\s*</div>\s*</div>'
active_card_replacement = """<div class="compact-row status-border-{{ booking.status|lower|replace(' ', '-') }}" data-pnr="{{ booking.pnr }}" data-flight_date="{{ booking.flight_date or '' }}" data-status="{{ booking.status }}" data-last_checked="{{ booking.last_checked or '' }}">
                    <div class="cr-main">
                        <div class="cr-left">
                            {{ airline_badge(booking.airline) }}
                            <div class="cr-info">
                                <div class="cr-top-line">
                                    <span class="pnr-code">{{ booking.pnr }}</span>
                                    <span class="cr-route">{{ booking.route if booking.route else '—' }}</span>
                                    {% if booking.flight_number %}
                                    <span class="cr-flight">{{ booking.flight_number }}</span>
                                    {% endif %}
                                </div>
                                <div class="cr-bottom-line">
                                    <span class="cr-date">{{ booking.flight_date }}</span>
                                    {% if booking.departure_time %}
                                    <span class="cr-time">{{ booking.departure_time }}</span>
                                    {% endif %}
                                    <span class="cr-passenger">{{ booking.passenger_name }} · {{ booking.passenger_count }} pax</span>
                                </div>
                            </div>
                        </div>
                        <div class="cr-right">
                            <span class="status-badge status-{{ booking.status|lower|replace(' ', '-') }}">{{ booking.status }}</span>
                            <div class="cr-actions" onclick="event.stopPropagation()">
                                <form action="{{ url_for('check_single', booking_id=booking.id) }}" method="POST" class="inline-form"
                                      onsubmit="this.querySelector('button').classList.add('is-loading');">
                                    <button type="submit" class="btn-icon-action" title="Refresh status">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3"/></svg>
                                    </button>
                                </form>
                                <form action="{{ url_for('delete', booking_id=booking.id) }}" method="POST" class="inline-form"
                                      onsubmit="return confirm('Remove this booking?')">
                                    <button type="submit" class="btn-icon-action btn-icon-danger" title="Remove">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                    </button>
                                </form>
                            </div>
                        </div>
                    </div>
                    {% if booking.status_detail %}
                    <div class="cr-detail-wrap">
                        <span class="status-detail-text"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px;margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>{{ booking.status_detail }}</span>
                    </div>
                    {% endif %}
                    <span class="cr-checked">{{ booking.last_checked|time_ago }}</span>
                </div>"""

# Replace completed card
completed_card_pattern = r'<div class="flight-card completed-card"[^>]*>.*?</div>\s*</div>\s*</div>'
completed_card_replacement = """<div class="compact-row completed-card" data-pnr="{{ booking.pnr }}" data-flight_date="{{ booking.flight_date or '' }}" data-status="{{ booking.status }}" data-last_checked="{{ booking.last_checked or '' }}">
                    <div class="cr-main">
                        <div class="cr-left">
                            {{ airline_badge(booking.airline) }}
                            <div class="cr-info">
                                <div class="cr-top-line">
                                    <span class="pnr-code">{{ booking.pnr }}</span>
                                    <span class="cr-route">{{ booking.route if booking.route else '—' }}</span>
                                    {% if booking.flight_number %}
                                    <span class="cr-flight">{{ booking.flight_number }}</span>
                                    {% endif %}
                                </div>
                                <div class="cr-bottom-line">
                                    <span class="cr-date">{{ booking.flight_date }}</span>
                                    {% if booking.departure_time %}
                                    <span class="cr-time">{{ booking.departure_time }}</span>
                                    {% endif %}
                                    <span class="cr-passenger">{{ booking.passenger_name }} · {{ booking.passenger_count }} pax</span>
                                </div>
                            </div>
                        </div>
                        <div class="cr-right">
                            <span class="status-badge status-{{ booking.status|lower|replace(' ', '-') }}">{{ booking.status }}</span>
                            <div class="cr-actions" onclick="event.stopPropagation()">
                                <form action="{{ url_for('delete', booking_id=booking.id) }}" method="POST" class="inline-form"
                                      onsubmit="return confirm('Remove this booking?')">
                                    <button type="submit" class="btn-icon-action btn-icon-danger" title="Remove">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                    </button>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>"""

# Apply the regex substitution. We have to be careful with DOTALL to match the multiline flight-card divs.
import sys

# Replace active card
new_html = re.sub(
    r'<div class="flight-card status-border-\{\{ booking\.status\|lower\|replace\(\' \', \'-\'\) \}\}"[^>]*>.*?<div class="flight-card-body">.*?</div>\s*</div>',
    active_card_replacement, 
    html, 
    flags=re.DOTALL
)

# Replace completed card
new_html = re.sub(
    r'<div class="flight-card completed-card">.*?<div class="flight-card-body">.*?</div>\s*</div>',
    completed_card_replacement, 
    new_html, 
    flags=re.DOTALL
)

with open('templates/index.html', 'w') as f:
    f.write(new_html)

print("HTML patched successfully!")
