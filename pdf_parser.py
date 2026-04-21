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


def detect_airline(text):
    """
    Detect which airline a PDF belongs to based on content.
    Returns 'airindia' or 'indigo'.
    """
    text_lower = text.lower()

    # Air India indicators
    ai_indicators = [
        'air india', 'airindia.com', 'ai ', 'maharaja',
        'tata group', 'star alliance',
    ]
    # IndiGo indicators
    indigo_indicators = [
        'indigo', 'goindigo', '6e ', '6e-', 'interglobe',
    ]

    ai_score = sum(1 for ind in ai_indicators if ind in text_lower)
    indigo_score = sum(1 for ind in indigo_indicators if ind in text_lower)

    # Also check flight number pattern
    if re.search(r'AI[\s-]*\d{1,4}', text):
        ai_score += 3
    if re.search(r'6E\s*\d{3,4}', text):
        indigo_score += 3

    if ai_score > indigo_score:
        return 'airindia'
    return 'indigo'


def parse_booking(pdf_path):
    """
    Parse a booking confirmation PDF — auto-detects airline (IndiGo or Air India).

    Returns a list of booking dicts (one per flight segment), each with:
    - pnr, passenger_name, flight_number, route, flight_date,
      departure_time, arrival_time, airline
    """
    raw_text = extract_text(pdf_path)
    if not raw_text:
        raise ValueError("Could not extract text from PDF. File may be corrupted or image-based.")

    # Detect airline before dedup (Air India PDFs don't need dedup)
    airline = detect_airline(raw_text)

    if airline == 'airindia':
        return parse_airindia_booking(raw_text)
    else:
        return parse_indigo_booking(raw_text)


def parse_airindia_booking(raw_text):
    """
    Parse an Air India booking confirmation PDF.
    Air India PDFs don't have the 4x character duplication.
    """
    text = raw_text  # No deduplication needed

    # Extract PNR
    pnr = extract_pnr(text)
    if not pnr:
        raise ValueError("Could not find PNR/Booking Reference in the Air India PDF.")

    # Extract passenger name
    passenger_name = extract_passenger_name_airindia(text)

    # Extract flight segments
    segments = extract_flight_segments_airindia(text)

    if not segments:
        # Fallback: try basic extraction
        flight_date = extract_flight_date(text)
        flight_number = extract_airindia_flight_number(text)
        route = extract_route(text)
        if flight_date:
            segments = [{
                'flight_number': flight_number or 'Unknown',
                'route': route or 'Unknown',
                'flight_date': flight_date,
                'departure_time': None,
                'arrival_time': None,
            }]
        else:
            raise ValueError("Could not extract flight details from the Air India PDF.")

    # Deduplicate
    seen = set()
    unique_segments = []
    for seg in segments:
        key = (seg.get('flight_number'), seg.get('flight_date'), seg.get('route'))
        if key not in seen:
            seen.add(key)
            unique_segments.append(seg)
    segments = unique_segments

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
            'airline': 'airindia',
        })

    return bookings


def parse_indigo_booking(raw_text):
    """
    Parse an IndiGo booking confirmation PDF.
    Handles the 4x character duplication in IndiGo PDFs.
    """
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
            'airline': 'indigo',
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
        r'\b(Mr|Mrs|Ms|Miss|Master)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)\s+Adult',
        r'\b(Mr|Mrs|Ms|Miss|Master)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)',
        r'Passenger.*?:\s*(.*?)(?:\n|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if match.lastindex >= 2:
                return match.group(2).strip()
            return match.group(1).strip()
            
    # Fallback for Firefox Print to PDF (2x duplicated characters)
    doubled_patterns = [
        r'\b(MMrr|MMrrss|MMss|MMiissss|MMaasstteerr)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)\s+AAdduulltt',
        r'\b(MMrr|MMrrss|MMss|MMiissss|MMaasstteerr)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)\s+Adult',
        r'\b(MMrr|MMrrss|MMss|MMiissss|MMaasstteerr)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)'
    ]
    for pattern in doubled_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_name = match.group(2).strip()
            return raw_name[::2]
            
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


def extract_passenger_name_airindia(text):
    """
    Extract passenger name from Air India PDF.
    Air India PDFs use standard text (no character duplication).
    """
    patterns = [
        r'\b(Mr|Mrs|Ms|Miss|Master)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)\s+(?:Adult|Child|Infant)',
        r'\b(Mr|Mrs|Ms|Miss|Master)\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)',
        r'Passenger.*?:\s*(.*?)(?:\n|$)',
        r'Name.*?:\s*(.*?)(?:\n|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if match.lastindex >= 2:
                return match.group(2).strip()
            return match.group(1).strip()
    return None


def extract_airindia_flight_number(text):
    """
    Extract Air India flight number.
    Format: 'AI 123' or 'AI-123' or 'AI123'
    """
    match = re.search(r'AI[\s-]*(\d{1,4})', text)
    if match:
        return f"AI {match.group(1)}"
    return None


def extract_flight_segments_airindia(text):
    """
    Extract all flight segments from an Air India PDF.
    """
    segments = []

    # Pattern: AI followed by number and a date
    segment_pattern = r'AI[\s-]*(\d{1,4}).*?(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})'
    segment_matches = list(re.finditer(segment_pattern, text, re.IGNORECASE))

    # Times: HH:MM
    time_pattern = r'\b(\d{2}:\d{2})\b'
    all_times = re.findall(time_pattern, text)

    # Routes
    route_pattern = r'([A-Z]{3})\s*[-–→]\s*([A-Z]{3})'
    route_matches = list(re.finditer(route_pattern, text))

    if segment_matches:
        for i, seg_match in enumerate(segment_matches):
            flight_num = f"AI {seg_match.group(1)}"
            date_str = f"{seg_match.group(2)} {seg_match.group(3)} {seg_match.group(4)}"
            try:
                flight_date = datetime.strptime(date_str, '%d %b %Y').strftime('%Y-%m-%d')
            except ValueError:
                continue

            dep_time = None
            arr_time = None
            time_idx = i * 2
            if time_idx < len(all_times):
                dep_time = all_times[time_idx]
            if time_idx + 1 < len(all_times):
                arr_time = all_times[time_idx + 1]

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
            print(f"\nAirline: {booking.get('airline', 'unknown')}")
            print(f"PNR: {booking['pnr']}")
            print(f"Passenger: {booking['passenger_name']}")
            print(f"Flight: {booking['flight_number']}")
            print(f"Route: {booking['route']}")
            print(f"Date: {booking['flight_date']}")
            print(f"Departure: {booking['departure_time']}")
            print(f"Arrival: {booking['arrival_time']}")
    else:
        print("Usage: python pdf_parser.py <path_to_pdf>")
