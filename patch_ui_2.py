import re

with open('templates/index.html', 'r') as f:
    html = f.read()

# 1. Remove AI Insights Section HTML
html = re.sub(r'<!-- AI Insights Section -->.*?</section>', '', html, flags=re.DOTALL)

# 2. Remove AI Insights Fetch JS
html = re.sub(r'// AI Insights Fetch.*?\}\);', '', html, flags=re.DOTALL)

# 3. Add checkboxes to compact-row active bookings
# Specifically, we want to inject it inside cr-left before the airline badge
html = re.sub(
    r'<div class="cr-left">\s*\{\{ airline_badge\(booking\.airline\) \}\}',
    r'''<div class="cr-left" onclick="event.stopPropagation()">
                            <label class="custom-checkbox cr-checkbox">
                                <input type="checkbox" class="booking-checkbox" value="{{ booking.id }}" onchange="updateCheckSelectedBtn()">
                                <span class="checkmark"></span>
                            </label>
                        </div>
                        <div class="cr-left">
                            {{ airline_badge(booking.airline) }}''',
    html
)

# 4. Replace Check All form with the one from vps_index.html
check_all_replacement = """                <form action="{{ url_for('check_all') }}" method="POST" class="inline-form" id="check-all-form"
                      style="{{ 'display:none' if check_running else '' }}">
                    <button type="button" class="btn btn-outline" id="check-selected-btn" onclick="checkSelectedPnrs()" disabled style="margin-right:8px;">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                        <span>Check Selected</span>
                    </button>
                    <button type="button" class="btn btn-glow" id="check-now-btn" onclick="confirmCheckAll()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3"/></svg>
                        <span>Check All</span>
                    </button>
                </form>"""

html = re.sub(
    r'<form action="\{\{ url_for\(\'check_all\'\) \}\}" method="POST" class="inline-form" id="check-all-form".*?</form>',
    check_all_replacement,
    html,
    flags=re.DOTALL
)

# 5. Inject the JS functions for Check Selected
js_injection = """
        function updateCheckSelectedBtn() {
            const checkedCount = document.querySelectorAll('.booking-checkbox:checked').length;
            const btn = document.getElementById('check-selected-btn');
            if(btn) {
                if (checkedCount > 0) {
                    btn.disabled = false;
                    btn.querySelector('span').innerText = `Check Selected (${checkedCount})`;
                } else {
                    btn.disabled = true;
                    btn.querySelector('span').innerText = `Check Selected`;
                }
            }
        }

        function checkSelectedPnrs() {
            const checked = document.querySelectorAll('.booking-checkbox:checked');
            if (checked.length === 0) return;
            
            const ids = Array.from(checked).map(cb => cb.value);
            
            if (confirm(`Check ${ids.length} selected bookings?`)) {
                // Submit via form with hidden input
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = "{{ url_for('check_selected') }}";
                
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'booking_ids';
                input.value = ids.join(',');
                
                form.appendChild(input);
                document.body.appendChild(form);
                form.submit();
            }
        }
        
        function confirmCheckAll() {
            if (confirm('Are you sure you want to refresh all active bookings? This might take a few minutes.')) {
                document.getElementById('check-all-form').submit();
            }
        }
"""

html = html.replace('// Sort functionality', js_injection + '\n        // Sort functionality')

with open('templates/index.html', 'w') as f:
    f.write(html)

print("Patch 2 applied.")
