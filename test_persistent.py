from playwright.sync_api import sync_playwright
import time

pnr = "7CPJL4"
lastname = "GARG"
with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir="/tmp/pnr-chrome-profile-pw",
        channel="chrome",
        headless=False,
        ignore_default_args=["--enable-automation"],
        args=["--no-first-run", "--no-default-browser-check"]
    )
    page = context.new_page()
    page.goto("https://www.srilankan.com/en_uk/ManageYourBooking")
    print(page.title())
    time.sleep(2)
    # just see if it loads or gets blocked
    context.close()
