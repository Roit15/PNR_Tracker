from scraper_srilankan import check_pnr_status
import time

try:
    print("Testing SriLankan CDP...")
    result = check_pnr_status("7CPJL4", "GARG")
    print("Result:", result)
except Exception as e:
    print("Error:", e)
