from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        try:
            print("Connecting to Chrome on 9223...")
            browser = p.chromium.connect_over_cdp("http://localhost:9223")
            context = browser.contexts[0]
            page = context.new_page()
            
            print("Loading srilankan manage booking...")
            page.goto("https://digital.srilankan.com/srilankan-airlines/manage-booking", wait_until="commit")
            page.wait_for_selector("#lastname2refx", timeout=15000)
            print("Successfully loaded manage booking page!")
            browser.disconnect()
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test()
