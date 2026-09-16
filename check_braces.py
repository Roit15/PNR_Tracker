import re

with open('templates/index.html', 'r') as f:
    content = f.read()

# Extract the script block
match = re.search(r'<script>([\s\S]*?)</script>', content)
if not match:
    print("No script found")
    exit(1)

js_code = match.group(1)

# Remove Jinja {{ ... }} and {% ... %}
js_code = re.sub(r'\{\{.*?\}\}', '', js_code)
js_code = re.sub(r'\{%.*?%\}', '', js_code)

open_braces = 0
for i, char in enumerate(js_code):
    if char == '{':
        open_braces += 1
    elif char == '}':
        open_braces -= 1

print(f"Net braces (should be 0): {open_braces}")
