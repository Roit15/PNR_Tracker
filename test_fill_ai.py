import sys
from scraper_airindia import check_pnr_status

def main():
    pnr = "JD7T7C"
    lastname = "GUPTA"
    print(f"Testing Air India PNR check with PNR={pnr}, Lastname={lastname}")
    try:
        result = check_pnr_status(pnr, lastname)
        print("Result:", result)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
