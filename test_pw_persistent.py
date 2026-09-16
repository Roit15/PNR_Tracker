from playwright.sync_api import sync_playwright
import time

def run():
    with sync_playwright() as p:
        print("Launching persistent context...")
        # Use a real user agent
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        context = p.chromium.launch_persistent_context(
            user_data_dir="/tmp/pnr-pw-profile2",
            headless=False,
            user_agent=ua,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.new_page()
        print("Navigating to Air India...")
        page.goto("https://www.airindia.com/in/en/manage/booking.html")
        time.sleep(5)
        print("Title:", page.title())
        context.close()

if __name__ == "__main__":
    run()
