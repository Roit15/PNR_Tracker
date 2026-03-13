"""
PDF Parser for Indigo Booking Confirmation.
Extracts PNR, passenger name, flight details from uploaded PDFs.

NOTE: Indigo PDFs render each character 4x (e.g. "PPPPNNNNRRRR" = "PNR").
We must deduplicate with deduplicate_text() before parsing.
"""

import re
import pdfplumber
from datetime import datetime


def deduplicate_text(text):
    """
    Indigo PDFs duplicate each character 4 times due to font rendering.
    E.g. "SSSS9999RRRRWWWWSSSSJJJJ" → "S9RWSJ"
    Only deduplicate runs of 4+ identical chars.
    """
    if not text:
        return text

    result = []
    i = 0
    while i < len(text):
        char = text[i]
        # Count consecutive identical characters
        run_len = 1
        while i + run_len < len(text) and text[i + run_len] == char:
            run_len += 1

        # If exactly 4 (or multiple of 4), collapse to 1 per group of 4
        if run_len >= 4 and run_len % 4 == 0:
            result.append(char * (run_len // 4))
        else:
            result.append(char * run_len)

        i += run_len

    return ''.join(result)


def parse_booking(pdf_path):
    """
    Parse an Indigo booking confirmation PDF and extract key fields.

    Returns a list of booking dicts (one per flight segment), each with:
    - pnr: 6-char alphanumeric booking reference
    - passenger_name: passenger's full name
    - flight_number: e.g. '6E 1081'
    - route: e.g. 'DEL-HKT'
    - flight_date: date string in YYYY-MM-DD format
    - departure_time: e.g. '15:40'
    - arrival_time: e.g. '21:50'
    """
    raw_text = extract_text(pdf_path)
    if not raw_text:
        raise ValueError("Could not extract text from PDF. File may be corrupted or image-based.")

    # Deduplicate the 4x character rendering
    text = deduplicate_text(raw_text)

    # Extract PNR
    pnr = extract_pnr(text)
    if not pnr:
        raise ValueError("Could not find PNR/Booking Reference in the PDF.")

    # Extract passenger name
    passenger_name = extract_passenger_name(text)

    # Extract flight segments
    segments = extract_flight_segments(text)

    if not segments:
        # Fallback: try to extract at least the date
        flight_date = extract_flight_date(text)
        if flight_date:
            segments = [{
                'flight_number': extract_flight_number(text) or 'Unknown',
                'route': extract_route(text) or 'Unknown',
                'flight_date': flight_date,
                'departure_time': None,
                'arrival_time': None,
            }]
        else:
            raise ValueError("Could not extract flight details from the PDF.")

    # Deduplicate segments (Indigo PDF often repeats content)
    seen = set()
    unique_segments = []
    for seg in segments:
        key = (seg.get('flight_number'), seg.get('flight_date'), seg.get('route'))
        if key not in seen:
            seen.add(key)
            unique_segments.append(seg)
    segments = unique_segments

    # Build booking records
    bookings = []
    for seg in segments:
        bookings.append({
            'pnr': pnr,
            'passenger_name': passenger_name or 'Unknown',
            'flight_number': seg.get('flight_number', 'Unknown'),
            'route': seg.get('route', 'Unknown'),
            'flight_date': seg.get('flight_date'),
            'departure_time': seg.get('departure_time'),
            'arrival_time': seg.get('arrival_time'),
        })

    return bookings


def extract_text(pdf_path):
    """Extract all text from a PDF file."""
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
    return full_text.strip()


def extract_pnr(text):
    """
    Extract PNR/Booking Reference.
    After dedup, looks like: "PNR/Booking Reference S9RWSJ"
    """
    patterns = [
        r'PNR\s*/?:?\s*Booking\s+Reference\s+([A-Z0-9]{6})',
        r'Booking\s+Reference\s*:?\s*([A-Z0-9]{6})',
        r'PNR\s*:?\s*([A-Z0-9]{6})',
        r'PNR/Booking Reference\s+([A-Z0-9]{6})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def extract_passenger_name(text):
    """
    Extract passenger name.
    After dedup: "Mr Manik Chopra" or similar
    """
    patterns = [
        r'(Mr|Mrs|Ms|Miss|Master)\s+([A-Za-z]+\s+[A-Za-z]+)\s+Adult',
        r'(Mr|Mrs|Ms|Miss|Master)\s+([A-Za-z]+\s+[A-Za-z]+)',
        r'Passenger.*?:\s*(.*?)(?:\n|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if match.lastindex >= 2:
                return match.group(2).strip()
            return match.group(1).strip()
    return None


def extract_flight_number(text):
    """
    Extract flight number.
    Indigo format: '6E 1234' or '6E1234'
    """
    match = re.search(r'6E\s*(\d{3,4})', text)
    if match:
        return f"6E {match.group(1)}"
    return None


def extract_route(text):
    """
    Extract route from sector information.
    After dedup: 'DEL-HKT' in the Sector line
    """
    patterns = [
        r'Sector.*?([A-Z]{3})\s*[-–]\s*([A-Z]{3})',
        r'([A-Z]{3})\s*[-–]\s*([A-Z]{3})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return None


def extract_flight_date(text):
    """
    Extract flight date.
    After dedup: '24 Apr 2026'
    """
    patterns = [
        r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
    ]
    dates_found = []
    for pattern in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                date_str = f"{match.group(1)} {match.group(2)} {match.group(3)}"
                parsed_date = datetime.strptime(date_str, '%d %b %Y')
                dates_found.append(parsed_date)
            except ValueError:
                continue

    if dates_found:
        # Look for flight date near time pattern "15:40 hrs, 24 Apr 2026"
        time_date_match = re.search(
            r'(\d{1,2}:\d{2})\s*hrs?,?\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
            text, re.IGNORECASE
        )
        if time_date_match:
            date_str = f"{time_date_match.group(2)} {time_date_match.group(3)} {time_date_match.group(4)}"
            parsed = datetime.strptime(date_str, '%d %b %Y')
            return parsed.strftime('%Y-%m-%d')

        # Fallback: return the latest date (likely flight date)
        dates_found.sort()
        return dates_found[-1].strftime('%Y-%m-%d')

    return None


def extract_flight_segments(text):
    """
    Extract all flight segments with full details.
    After dedup: "6E 1081 (A321)  24 Apr 2026"
    """
    segments = []

    # Pattern for flight segments
    segment_pattern = r'6E\s*(\d{3,4}).*?(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})'
    segment_matches = list(re.finditer(segment_pattern, text, re.IGNORECASE))

    # Extract departure/arrival times "HH:MM hrs"
    time_pattern = r'(\d{1,2}:\d{2})\s*hrs?,?\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})'
    time_matches = list(re.finditer(time_pattern, text, re.IGNORECASE))

    # Extract routes
    route_pattern = r'([A-Z]{3})\s*[-–]\s*([A-Z]{3})'
    route_matches = list(re.finditer(route_pattern, text))

    if segment_matches:
        for i, seg_match in enumerate(segment_matches):
            flight_num = f"6E {seg_match.group(1)}"
            date_str = f"{seg_match.group(2)} {seg_match.group(3)} {seg_match.group(4)}"
            flight_date = datetime.strptime(date_str, '%d %b %Y').strftime('%Y-%m-%d')

            dep_time = None
            arr_time = None
            time_idx = i * 2
            if time_idx < len(time_matches):
                dep_time = time_matches[time_idx].group(1)
            if time_idx + 1 < len(time_matches):
                arr_time = time_matches[time_idx + 1].group(1)

            route = 'Unknown'
            if i < len(route_matches):
                route = f"{route_matches[i].group(1)}-{route_matches[i].group(2)}"

            segments.append({
                'flight_number': flight_num,
                'route': route,
                'flight_date': flight_date,
                'departure_time': dep_time,
                'arrival_time': arr_time,
            })

    return segments


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        result = parse_booking(sys.argv[1])
        for booking in result:
            print(f"\nPNR: {booking['pnr']}")
            print(f"Passenger: {booking['passenger_name']}")
            print(f"Flight: {booking['flight_number']}")
            print(f"Route: {booking['route']}")
            print(f"Date: {booking['flight_date']}")
            print(f"Departure: {booking['departure_time']}")
            print(f"Arrival: {booking['arrival_time']}")
    else:
        print("Usage: python pdf_parser.py <path_to_pdf>")
