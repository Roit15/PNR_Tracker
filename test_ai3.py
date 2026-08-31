import chrome_launcher
from playwright.sync_api import sync_playwright
import time

chrome_launcher.ensure_chrome_running(port=9224, profile_dir="/tmp/pnr-chrome-profile")
pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp("http://localhost:9224")
context = browser.contexts[0] if browser.contexts else browser.new_context()
page = context.new_page()

print("Navigating...")
page.goto("https://www.airindia.com/in/en/manage/booking.html")
print(page.title())

# wait a little bit
time.sleep(3)

# Dump all input names and IDs
inputs = page.evaluate("""
    Array.from(document.querySelectorAll('input')).map(i => ({name: i.name, id: i.id, placeholder: i.placeholder}))
""")
print("Inputs:", inputs)

context.close()
pw.stop()
