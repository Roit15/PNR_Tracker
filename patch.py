import re

with open("scraper.py", "r") as f:
    content = f.read()

# Replace time.sleep(15) at the end with a loop
old_wait = """        # Wait for results to load
        time.sleep(15)

        # Extract page content
        page_text = driver.find_element(By.TAG_NAME, 'body').text"""

new_wait = """        # Smart wait for results to load (wait until flight info is present, up to 20s)
        page_text = ""
        for _ in range(20):
            time.sleep(1)
            page_text = driver.find_element(By.TAG_NAME, 'body').text
            text_lower = page_text.lower()
            if 'invalid' in text_lower or 'not found' in text_lower:
                break
            # Flight info usually contains patterns like flight numbers or terminal
            # If we see terminal information, it's loaded.
            if 'terminal information' in text_lower or 'flight number' in text_lower:
                break
"""

if old_wait in content:
    content = content.replace(old_wait, new_wait)
    with open("scraper.py", "w") as f:
        f.write(content)
    print("Patched smart wait!")
else:
    print("Could not find old wait")
