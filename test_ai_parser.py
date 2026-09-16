import json
from scraper_airindia import extract_status_detail, _keyword_near_pnr
from bs4 import BeautifulSoup

html = open('debug_ai_after_submit.html').read()
soup = BeautifulSoup(html, 'html.parser')
page_text = soup.get_text(separator=' ', strip=True)
text_lower = page_text.lower()
pnr = 'DN72VM'

result = {'status': 'Error', 'detail': ''}

if 'payment failed' in text_lower or 'payment unsuccessful' in text_lower:
    result['status'] = 'Cancelled'
    result['detail'] = 'Payment failed — booking was not completed. Flight effectively cancelled.'
elif 'payment for this booking is incomplete' in text_lower or \
     'payment is incomplete' in text_lower:
    result['status'] = 'Payment Pending'
    result['detail'] = 'Payment incomplete — ticket not confirmed. Please complete payment on Air India.'
elif any(phrase in text_lower for phrase in [
    'invalid', 'not found', 'no booking', 'cannot be found',
    'booking cannot be found', 'try again', 'no record'
]):
    result['status'] = 'Cancelled'
    result['detail'] = 'Booking not found on Air India — ticket likely cancelled.'
elif 'access denied' in text_lower or 'incapsula' in text_lower:
    result['status'] = 'Error'
    result['detail'] = 'Air India website blocked the request. Will retry later.'
elif _keyword_near_pnr('cancelled', pnr, page_text, window=300) or \
     'cancelled' in text_lower and text_lower.count('cancelled') > 1:
    result['status'] = 'Cancelled'
    result['detail'] = extract_status_detail(page_text, 'cancelled')
elif _keyword_near_pnr('rescheduled', pnr, page_text, window=300):
    result['status'] = 'Rescheduled'
    result['detail'] = extract_status_detail(page_text, 'rescheduled')
elif _keyword_near_pnr('delayed', pnr, page_text, window=300):
    result['status'] = 'Delayed'
    result['detail'] = extract_status_detail(page_text, 'delayed')
elif _keyword_near_pnr('confirmed', pnr, page_text, window=300):
    result['status'] = 'Confirmed'
    result['detail'] = 'extract_booking_detail'
elif _keyword_near_pnr('completed', pnr, page_text, window=300) or \
     _keyword_near_pnr('flown', pnr, page_text, window=300):
    result['status'] = 'Completed'
    result['detail'] = 'Flight has been completed.'
elif any(kw in text_lower for kw in [
    'confirmed', 'booked', 'itinerary', 'e-ticket',
    'seat selection', 'add-ons', 'check-in', 'checkin'
]):
    result['status'] = 'Confirmed'
    result['detail'] = 'extract_booking_detail'
elif 'check-in' in text_lower or 'checkin' in text_lower:
    result['status'] = 'Check-in Open'
    result['detail'] = 'extract_booking_detail'
else:
    if 'search for a booking' in text_lower and 'booking reference' in text_lower and 'continue' in text_lower:
        result['status'] = 'Soft Blocked'
    else:
        result['status'] = 'Checked'
        result['detail'] = page_text[:500] if page_text else 'Could not parse status'

print(json.dumps(result, indent=2))
