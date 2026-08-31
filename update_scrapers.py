import os
import re

files = [
    'scraper.py',
    'scraper_akasaair.py',
    'scraper_etihad.py',
    'scraper_singaporeair.py',
    'scraper_vietjet.py'
]

new_func = """import chrome_launcher

def _create_stealth_driver():
    \"\"\"Create a Chrome driver connected to the shared developer mode CDP instance.\"\"\"
    chrome_launcher.ensure_chrome_running()
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9224")
    
    # Optional: we can disable the w3c if needed, but usually debuggerAddress is enough
    driver = webdriver.Chrome(options=options)
    return driver
"""

for f in files:
    if not os.path.exists(f):
        print(f"File {f} not found!")
        continue
        
    with open(f, 'r') as file:
        content = file.read()
        
    # Replace from def _create_stealth_driver(): down to return driver
    # It might vary, so let's use regex
    pattern = re.compile(r'def _create_stealth_driver\(\).*?return driver', re.DOTALL)
    
    if 'chrome_launcher' not in content:
        # We don't want to import it twice
        pass

    # Ensure import chrome_launcher is present at top, or just insert it before def _create_stealth_driver
    new_content = pattern.sub(new_func, content)
    
    if new_content == content:
        print(f"Warning: No match found for {f}")
    else:
        with open(f, 'w') as file:
            file.write(new_content)
        print(f"Updated {f}")

