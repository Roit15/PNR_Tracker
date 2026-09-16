from scraper_airindia import check_pnr_status
import json

def test():
    print("Starting scrape with DN72VM / BANSAL...")
    result = check_pnr_status("DN72VM", "BANSAL")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test()
