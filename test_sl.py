from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://www.srilankan.com/en_uk/plan-and-book/manage-booking')
    try:
        ln = page.get_attribute('#lastname2refx', 'placeholder')
        pnr = page.get_attribute('#bookref2refx', 'placeholder')
        print("lastname2refx:", ln)
        print("bookref2refx:", pnr)
    except Exception as e:
        print(e)
    browser.close()
