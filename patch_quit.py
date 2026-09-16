import os
import glob

def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # We want to replace driver.quit() inside a finally block
    # Note: we need to handle the exact indentation. 
    # Usually it's 8 spaces: "        driver.quit()"
    
    robust_quit = """        try:
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

    if '        driver.quit()' in content:
        content = content.replace('        driver.quit()', robust_quit)
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Patched {filepath}")

if __name__ == "__main__":
    scrapers = [
        "scraper.py",
        "scraper_etihad.py",
        "scraper_airindia.py",
        "scraper_thaiairways.py",
        "scraper_akasaair.py",
        "scraper_vietjet.py",
        "scraper_singaporeair.py",
        "scraper_srilankan.py"
    ]
    for s in scrapers:
        if os.path.exists(s):
            patch_file(s)
