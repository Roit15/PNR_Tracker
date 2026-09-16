from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.singaporeair.com/en_UK/sg/plan-travel/your-booking/managebooking/")
    time.sleep(3)
    
    # Get all text inputs
    inputs = page.evaluate("""() => {
        return Array.from(document.querySelectorAll("input")).map(i => ({
            id: i.id, 
            name: i.name, 
            type: i.type,
            placeholder: i.placeholder,
            className: i.className
        }))
    }""")
    
    for i in inputs:
        print(i)
    
    browser.close()
