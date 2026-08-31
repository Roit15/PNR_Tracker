from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
try:
    browser = pw.chromium.connect_over_cdp("http://localhost:9222")
    print("Connected successfully!")
    browser.close()
except Exception as e:
    print(f"Error: {e}")
pw.stop()
