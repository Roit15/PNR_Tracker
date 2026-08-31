from scraper_airindia import check_pnr_status
import time

try:
    print("Testing Air India CDP...")
    result = check_pnr_status("ED3QVT", "GARG")
    print("Result:", result)
except Exception as e:
    print("Error:", e)
