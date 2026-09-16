import json
from scraper_airindia import _try_check_pnr

if __name__ == '__main__':
    try:
        res = _try_check_pnr('DN72VM', 'BANSAL')
        print(json.dumps(res, indent=2))
    except Exception as e:
        print("ERROR:", e)
