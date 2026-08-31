import chrome_launcher
from playwright.sync_api import sync_playwright
import time

chrome_launcher.ensure_chrome_running()
pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp("http://localhost:9224")
context = browser.contexts[0] if browser.contexts else browser.new_context()
page = context.new_page()

print("Navigating...")
page.goto("https://www.airindia.com/in/en/manage/booking.html")
print(page.title())
time.sleep(3)

# Dump all buttons
buttons = page.evaluate("""
    Array.from(document.querySelectorAll('button')).map(b => ({
        id: b.id, 
        class: b.className, 
        text: b.innerText, 
        type: b.type
    }))
""")
print("Buttons:", buttons)

context.close()
pw.stop()
