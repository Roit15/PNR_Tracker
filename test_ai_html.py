from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, time

def test():
    driver = _create_stealth_driver()
    driver.get("https://www.airindia.com/in/en/manage/booking.html")
    time.sleep(10)
    
    _dismiss_popups(driver, None)
    
    print("Inputs found:")
    inputs = driver.find_elements(By.TAG_NAME, 'input')
    for i, inp in enumerate(inputs):
        try:
            print(f"[{i}] type={inp.get_attribute('type')} id={inp.get_attribute('id')} name={inp.get_attribute('name')} placeholder={inp.get_attribute('placeholder')} visible={inp.is_displayed()}")
        except Exception as e:
            pass
            
    driver.quit()
    
test()
