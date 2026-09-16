import os

def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    bad_block = """        try:
            if hasattr(driver, 'browser_pid'):
                pid = driver.browser_pid
                driver.quit()
                import os, signal
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
            else:
                driver.quit()
        except Exception:
            pass"""

    fixed_block = """        try:
            if hasattr(driver, 'browser_pid'):
                pid = driver.browser_pid
                driver.quit()
                try:
                    __import__('os').kill(pid, __import__('signal').SIGTERM)
                except Exception:
                    pass
            else:
                driver.quit()
        except Exception:
            pass"""

    if bad_block in content:
        content = content.replace(bad_block, fixed_block)
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed {filepath}")

if __name__ == "__main__":
    scrapers = [
        "scraper.py",
        "scraper_etihad.py",
        "scraper_airindia.py",
        "scraper_thaiairways.py",
        "scraper_akasaair.py",
        "scraper_vietjet.py",
        "scraper_singaporeair.py"
    ]
    for s in scrapers:
        if os.path.exists(s):
            patch_file(s)
