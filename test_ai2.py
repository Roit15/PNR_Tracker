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
page.fill("input[name='pnr']", "ED3QVT")
page.fill("input[name='lastName']", "GARG")
print("Filled!")
time.sleep(2)
context.close()
pw.stop()
