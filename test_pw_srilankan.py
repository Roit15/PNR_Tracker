import time
from playwright.sync_api import sync_playwright

def test_playwright():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        
        url = "https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking"
        print(f"Loading {url} with Playwright...")
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            
            content = page.content()
            if "Incident ID:" in content or "Access denied" in content:
                print("❌ Blocked by Imperva WAF")
            elif "manage-your-booking" in page.url or "srilankan.com" in content:
                print("✅ Successfully loaded SriLankan manage booking page")
            else:
                print("❓ Unknown status")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    test_playwright()
