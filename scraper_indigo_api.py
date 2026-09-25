from curl_cffi import requests
import json
import time

def check_pnr_indigo_api(pnr, lastname):
    session = requests.Session(impersonate='chrome110')
    
    # 1. Fetch landing page to get Akamai cookies
    session.get('https://www.goindigo.in/account/my-bookings.html')
    time.sleep(1)
    
    # 2. Get Guest Token
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.goindigo.in/',
        'Origin': 'https://www.goindigo.in',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
    }
    res2 = session.post('https://6ewai.goindigo.in/sse/api/auth/guest', headers=headers, json={})
    token = session.cookies.get('token')
    
    if not token:
        raise Exception("Failed to get guest token from IndiGo API")
        
    # 3. Fetch PNR Data
    url = 'https://api-prod-itinerary-skyplus6e.goindigo.in/v2/Booking/retrieve'
    payload = {
        'retrieveBookingRequest': {
            'RecordLocator': pnr,
            'Name': {'Last': lastname}
        }
    }
    api_headers = {
        'user_key': '2dbf6e57bb2e2047697712d144b1518b',
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.goindigo.in/',
        'Origin': 'https://www.goindigo.in',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
    }
    res3 = session.post(url, json=payload, headers=api_headers)
    
    if res3.status_code != 200:
        err = res3.text
        try:
            err = res3.json().get('errors', {}).get('message', res3.text)
        except:
            pass
            
        if res3.status_code == 400 or res3.status_code == 404:
            return {
                'status': 'Not Found',
                'detail': err,
                'raw_text': err
            }
        raise Exception(f"API Error {res3.status_code}: {err}")
        
    data = res3.json()
    
    # 4. Extract data
    return _parse_indigo_json(data, pnr, lastname)

def _parse_indigo_json(data, pnr, lastname):
    segments = []
    
    def _find_flights(obj):
        if isinstance(obj, dict):
            if 'designator' in obj and 'boardPoint' in obj:
                segments.append(obj)
            elif 'carrierCode' in obj and 'flightNumber' in obj:
                segments.append(obj)
            elif 'departure' in obj and 'arrival' in obj:
                segments.append(obj)
            else:
                for k, v in obj.items():
                    _find_flights(v)
        elif isinstance(obj, list):
            for i in obj:
                _find_flights(i)
                
    _find_flights(data)
    
    flights = []
    for s in segments:
        f = {
            'flight_date': '',
            'route': '',
            'flight_number': '',
            'departure_time': '',
            'arrival_time': '',
            'passenger_name': lastname,
            'passenger_count': 1
        }
        
        try: f['flight_number'] = str(s.get('carrierCode', '6E')) + ' ' + str(s.get('flightNumber', ''))
        except: pass
        
        try: f['route'] = str(s.get('boardPoint', s.get('departure', ''))) + '-' + str(s.get('offPoint', s.get('arrival', '')))
        except: pass
        
        try: 
            dep = s.get('scheduledDeparture', '')
            if dep:
                f['flight_date'] = dep.split('T')[0]
                f['departure_time'] = dep.split('T')[1][:5]
        except: pass
        
        try:
            arr = s.get('scheduledArrival', '')
            if arr:
                f['arrival_time'] = arr.split('T')[1][:5]
        except: pass
        
        flights.append(f)
        
    raw_text = json.dumps(data, indent=2)
    return {
        'status': 'Success' if flights else 'Needs Manual Parse',
        'data': flights,
        'raw_text': raw_text
    }
