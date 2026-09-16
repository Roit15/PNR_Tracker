from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, time

def test():
    driver = _create_stealth_driver()
    driver.get("https://www.airindia.com/in/en/manage/booking.html")
    time.sleep(10)
    _dismiss_popups(driver, None)
    
    html = driver.execute_script("return document.querySelector('.manage-booking-form, form, #manage-booking-component').innerHTML;")
    print("Form HTML:", html[:2000])
    
    driver.quit()
    
test()
