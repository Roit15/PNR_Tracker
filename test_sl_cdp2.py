from scraper_srilankan import check_pnr_status
import time

try:
    print("Testing SriLankan CDP...")
    result = check_pnr_status("9GRW4B", "Vanigotta")
    print("Result:", result)
except Exception as e:
    print("Error:", e)
