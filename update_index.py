import re

with open("templates/index.html", "r") as f:
    content = f.read()

# 1. Add radio buttons
new_radios = """                        <label class="airline-option">
                            <input type="radio" name="airline" value="thaiairways">
                            <span class="airline-chip airline-thaiairways">Thai Airways <span class="airline-code">TG</span></span>
                        </label>
                        <label class="airline-option">
                            <input type="radio" name="airline" value="srilankan">
                            <span class="airline-chip airline-srilankan">SriLankan <span class="airline-code">UL</span></span>
                        </label>
                    </div>"""
content = content.replace("                    </div>", new_radios, 1)

# 2. Add macro at top
macro = """
{% macro airline_badge(airline) %}
{% set badge_class = 'badge-akasaair' if airline == 'akasaair' else ('badge-etihad' if airline == 'etihad' else ('badge-airindia' if airline == 'airindia' else ('badge-vietjet' if airline == 'vietjet' else ('badge-singaporeair' if airline == 'singaporeair' else ('badge-thaiairways' if airline == 'thaiairways' else ('badge-srilankan' if airline == 'srilankan' else 'badge-indigo')))))) %}
{% set airline_code = 'QP' if airline == 'akasaair' else ('EY' if airline == 'etihad' else ('AI' if airline == 'airindia' else ('VJ' if airline == 'vietjet' else ('SQ' if airline == 'singaporeair' else ('TG' if airline == 'thaiairways' else ('UL' if airline == 'srilankan' else '6E')))))) %}
<span class="airline-badge-sm {{ badge_class }}">{{ airline_code }}</span>
{% endmacro %}
"""
content = content.replace("<body>\n", f"<body>\n{macro}")

# 3. Replace all inline badges with macro call
pattern = r'<span class="airline-badge-sm \{\{.*?\</span\>'
content = re.sub(pattern, '{{ airline_badge(booking.airline) }}', content)

with open("templates/index.html", "w") as f:
    f.write(content)
print("Updated index.html")
