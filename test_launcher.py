import chrome_launcher
from playwright.sync_api import sync_playwright

chrome_launcher.ensure_chrome_running(port=9225, profile_dir="/tmp/pnr-chrome-9225")

pw = sync_playwright().start()
try:
    browser = pw.chromium.connect_over_cdp("http://localhost:9225")
    print("Connected to 9225 successfully!")
    print(len(browser.contexts))
    browser.close()
except Exception as e:
    print(f"Error on 9225: {e}")
pw.stop()
