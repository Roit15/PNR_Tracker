import logging
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv; load_dotenv()
from database import get_connection, _fetchall_as_dicts
from scraper_router import route_scraper

def test():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM bookings WHERE airline='indigo' LIMIT 1")
        row = dict(_fetchall_as_dicts(c)[0])
    
    print("Testing:", row['airline'], row['pnr'])
    res = route_scraper(row["airline"], row["pnr"], row["passenger_lastname"], row["route"], row["flight_date"])
    print("Result:", res)

if __name__ == '__main__':
    test()
