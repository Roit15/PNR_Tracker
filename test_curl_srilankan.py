import time
try:
    from curl_cffi import requests
except ImportError:
    print("curl_cffi not found")
    exit(1)

def test_curl():
    # Use the dxFlow endpoint
    url = "https://book.srilankan.com/plnext/srilankanair/Override.action"
    print(f"Posting to {url} with curl_cffi...")
    
    # We will test with the known PNR 9GRW4B and Lastname Vanigotta
    data = {
        "lastname2": "Vanigotta",
        "bookref2": "9GRW4B",
        "SITE": "CMULCMUL",  # Typical Amadeus site code, we'll try without it first
        "LANGUAGE": "GB",
    }
    
    # Actually just basic dxFlow fields first
    data_dx = {
        "lastname2": "Vanigotta",
        "bookref2": "9GRW4B",
        "idxxui": "tqbbbhuwb5kd2q4xd5xhbxzx",  # from the HTML dump
        "isredemption": "F",
        "ishsbc": "F"
    }

    try:
        session = requests.Session(impersonate="chrome120")
        # Go to homepage first to get cookies
        print("Getting homepage...")
        session.get("https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking")
        
        print("Posting form...")
        response = session.post(
            url, 
            data=data_dx,
            headers={"Referer": "https://www.srilankan.com/en_uk/plan-and-book/manage-your-booking"}
        )
        print(f"Status Code: {response.status_code}")
        print(f"Final URL: {response.url}")
        
        text = response.text
        if "Incident ID:" in text or "Access denied" in text:
            print("❌ Blocked by Imperva WAF")
        elif "Khushi" in text or "Vanigotta" in text or "143" in text or "CMB" in text:
            print("✅ Successfully loaded booking details")
        else:
            print("❓ Unknown status")
            print("="*50)
            print(text[:1000])
            print("="*50)
            with open("curl_result.html", "w") as f:
                f.write(text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test_curl()
