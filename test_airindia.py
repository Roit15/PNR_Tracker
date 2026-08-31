import logging
import random
from scraper_airindia import check_pnr_status

logging.basicConfig(level=logging.INFO)

def main():
    print("Testing AH2BX3 Rustagi...")
    res = check_pnr_status("AH2BX3", "Rustagi")
    print(res)

if __name__ == "__main__":
    main()
