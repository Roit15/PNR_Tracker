from scraper_airindia import _create_stealth_driver, _dismiss_popups, By, time

def test():
    driver = _create_stealth_driver()
    driver.get("https://www.airindia.com/in/en/manage/manage-booking.html")
    time.sleep(10)
    
    # Try to find all inputs
    inputs = driver.find_elements(By.TAG_NAME, 'input')
    print(f"Found {len(inputs)} inputs")
    for idx, inp in enumerate(inputs):
        try:
            print(f"Input {idx}: id={inp.get_attribute('id')}, name={inp.get_attribute('name')}, placeholder={inp.get_attribute('placeholder')}, type={inp.get_attribute('type')}, displayed={inp.is_displayed()}")
        except Exception as e:
            print(f"Input {idx} error: {e}")
            
    driver.quit()
    
test()
