"""
PDF Parser for Indigo, Air India, and VietJet booking confirmations.
Extracts PNR, passenger name, flight details from uploaded PDFs.

NOTE: Indigo PDFs render each character 4x (e.g. "PPPPNNNNRRRR" = "PNR").
We must deduplicate with deduplicate_text() before parsing.

VietJet PDFs are image-based — text is extracted via OCR (easyocr).
"""

import re
import ssl
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
    Detect which airline a PDF belongs to.
    Returns 'airindia', 'vietjet', or 'indigo'.
    """
    text_lower = text.lower()

    # VietJet indicators (check first — image OCR may garble 'vietjet' slightly)
    vj_indicators = ['vietjet', 'vietjetair', 'vj ', 'vj5', 'vj6', 'vj7', 'vj8', 'vj9',
                     'vietet', 'vieyjet', '1900 1886']
    vj_score = sum(1 for ind in vj_indicators if ind in text_lower)
    if re.search(r'VJ\s*\d{3,4}', text, re.IGNORECASE):
        vj_score += 3

    # Air India indicators
    ai_indicators = ['air india', 'airindia.com', 'maharaja', 'tata group', 'star alliance']
    ai_score = sum(1 for ind in ai_indicators if ind in text_lower)
    if re.search(r'\bAI[\s-]*\d{1,4}\b', text):
        ai_score += 3

    # IndiGo indicators
    indigo_indicators = ['indigo', 'goindigo', '6e ', '6e-', 'interglobe']
    indigo_score = sum(1 for ind in indigo_indicators if ind in text_lower)
    if re.search(r'6E\s*\d{3,4}', text):
        indigo_score += 3

    best = max(vj_score, ai_score, indigo_score)
    if best == 0:
        return 'indigo'
    if vj_score == best:
        return 'vietjet'
    if ai_score == best:
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
    elif airline == 'vietjet':
        return parse_vietjet_booking(raw_text)
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
            'passenger_count': extract_passenger_count(text),
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
            'passenger_count': extract_passenger_count(text),
        })

    return bookings


def extract_text(pdf_path):
    """Extract all text from a PDF file. Falls back to OCR for image-based PDFs."""
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
    if full_text.strip():
        return full_text.strip()

    # Fallback: image-based PDF — extract embedded images and OCR them
    return _ocr_pdf(pdf_path)


def _ocr_pdf(pdf_path):
    """Extract text from image-based PDF using easyocr via PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""

    try:
        # Fix macOS SSL so easyocr can download its models
        ssl._create_default_https_context = ssl._create_unverified_context

        import easyocr
        reader = easyocr.Reader(['en'], verbose=False)
    except Exception:
        return ""

    doc = fitz.open(pdf_path)
    all_text = []

    for page in doc:
        images = page.get_images(full=True)
        for img_info in images:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                img_bytes = base_image['image']
                results = reader.readtext(img_bytes, detail=0)
                all_text.extend(results)
            except Exception:
                continue

        # If no embedded images, render the page as an image and OCR it
        if not images:
            try:
                mat = fitz.Matrix(2, 2)  # 2x zoom for better OCR accuracy
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                results = reader.readtext(img_bytes, detail=0)
                all_text.extend(results)
            except Exception:
                continue

    return "\n".join(all_text)


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


def extract_passenger_count(text):
    """
    Extract the number of distinct passengers by counting titles.
    """
    pattern = r'\b(Mr|Mrs|Ms|Miss|Master)\.?\s+[A-Za-z]+'
    
    # Fallback for doubled chars (e.g. Firefox Print to PDF for Indigo)
    doubled_pattern = r'\b(MMrr|MMrrss|MMss|MMiissss|MMaasstteerr)\.?\s+[A-Za-z]+'
    
    count = len(re.findall(pattern, text, re.IGNORECASE))
    if count == 0:
        count = len(re.findall(doubled_pattern, text, re.IGNORECASE))
        
    # Some PDFs might just have a total passenger count directly.
    if count == 0:
        pax_match = re.search(r'(\d+)\s+(?:Pax|passenger[s]?)', text, re.IGNORECASE)
        if pax_match:
            try:
                return int(pax_match.group(1))
            except ValueError:
                pass
                
    return max(1, count)  # Default to at least 1


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


def parse_vietjet_booking(text):
    """
    Parse a VietJet booking confirmation PDF (image-based, OCR'd text).
    Works line-by-line since OCR output is one token per line.
    """
    # Vietnamese city → IATA code map
    CITY_IATA = {
        'ha noi': 'HAN', 'hanoi': 'HAN', 'noi bai': 'HAN',
        'ho chi minh': 'SGN', 'saigon': 'SGN', 'hcmc': 'SGN',
        'da nang': 'DAD', 'danang': 'DAD',
        'phu quoc': 'PQC',
        'nha trang': 'CXR',
        'da lat': 'DLI', 'dalat': 'DLI',
        'hue': 'HUI',
        'can tho': 'VCA',
        'hai phong': 'HPH',
        'buon ma thuot': 'BMV',
        'quy nhon': 'UIH',
        'vinh': 'VII',
        'pleiku': 'PXU',
        'con dao': 'VCS',
        'phu cat': 'UIH',
        'bangkok': 'BKK', 'suvarnabhumi': 'BKK',
        'singapore': 'SIN',
        'kuala lumpur': 'KUL',
        'taipei': 'TPE',
        'seoul': 'ICN',
        'tokyo': 'NRT',
        'osaka': 'KIX',
        'hong kong': 'HKG',
        'guangzhou': 'CAN',
        'shanghai': 'PVG',
        'beijing': 'PEK',
    }

    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # ── PNR: find "RESERVATION CODE" then scan next few lines for 6-char code ──
    pnr = None
    for i, line in enumerate(lines):
        if 'reservation code' in line.lower():
            for j in range(i + 1, min(i + 8, len(lines))):
                # Must match raw (no uppercasing) — real PNR is all-caps, OCR noise is mixed case
                candidate = re.sub(r'\s+', '', lines[j])
                if re.fullmatch(r'[A-Z0-9]{6}', candidate):
                    pnr = candidate
                    break
        if pnr:
            break
    # Fallback: any all-caps 6-char alphanumeric standalone line
    if not pnr:
        for line in lines:
            m = re.fullmatch(r'[A-Z0-9]{6}', line.strip())
            if m:
                pnr = m.group(0)
                break
    if not pnr:
        raise ValueError("Could not find Reservation Code in VietJet PDF.")

    # ── Passenger name: "LASTNAME, FIRSTNAME" near Full name or passenger section ──
    passenger_name = None
    firstname = lastname = None
    for i, line in enumerate(lines):
        if 'full name' in line.lower() and i + 1 < len(lines):
            raw = lines[i + 1]
            m = re.match(r'([A-Z]+)[,\s]+([A-Z]+)', raw)
            if m:
                lastname, firstname = m.group(1).title(), m.group(2).title()
                passenger_name = f"{firstname} {lastname}"
                break
        # Passenger table: "LASTNAME FIRSTNAME" followed by "VJxxx" on next line
        m = re.match(r'^([A-Z]{2,})[,\s]+([A-Z]{2,})$', line)
        if m and i + 1 < len(lines) and re.match(r'VJ\d+', lines[i + 1], re.IGNORECASE):
            lastname, firstname = m.group(1).title(), m.group(2).title()
            passenger_name = f"{firstname} {lastname}"
            break

    # ── Flight number: first VJxxx token ──
    flight_number = None
    for line in lines:
        m = re.search(r'\b(VJ\d{3,4})\b', line, re.IGNORECASE)
        if m:
            flight_number = m.group(1).upper()
            break

    # ── Flight date: prefer date adjacent to flight number in flight section ──
    # VietJet format: "Fri, 24/04/2026" or just "24/04/2026"
    flight_date = None
    in_flight_section = False
    for line in lines:
        if '3. flight' in line.lower() or 'flight information' in line.lower():
            in_flight_section = True
        if in_flight_section:
            m = re.search(r'(\d{2})/(\d{2})/(\d{4})', line)
            if m:
                flight_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                break
    # Fallback: last DD/MM/YYYY date in text (flight date is after booking date)
    if not flight_date:
        all_dates = re.findall(r'(\d{2})/(\d{2})/(\d{4})', text)
        if all_dates:
            d = all_dates[-1]
            flight_date = f"{d[2]}-{d[1]}-{d[0]}"
    if not flight_date:
        raise ValueError("Could not extract flight date from VietJet PDF.")

    # ── Times: find the two HH.MM / HH:MM in the flight table (after flight section) ──
    dep_time = arr_time = None
    in_flight_section = False
    flight_times = []
    for line in lines:
        if '3. flight' in line.lower() or 'flight information' in line.lower():
            in_flight_section = True
        if in_flight_section:
            m = re.fullmatch(r'(\d{2})[.:](\d{2})', line)
            if m:
                flight_times.append(f"{m.group(1)}:{m.group(2)}")
    if flight_times:
        dep_time = flight_times[0]
        arr_time = flight_times[1] if len(flight_times) >= 2 else None

    # ── Route: city names after Depart/Arrive columns in flight table ──
    route = None
    dep_city = arr_city = None
    in_flight_section = False
    found_flight_row = False
    for i, line in enumerate(lines):
        if '3. flight' in line.lower() or 'flight information' in line.lower():
            in_flight_section = True
        if in_flight_section and re.match(r'VJ\d+', line, re.IGNORECASE):
            found_flight_row = True
        if found_flight_row:
            ll = line.lower().strip()
            for city, iata in CITY_IATA.items():
                if city in ll:
                    if dep_city is None:
                        dep_city = iata
                    elif arr_city is None and iata != dep_city:
                        arr_city = iata
                        break
        if dep_city and arr_city:
            break
    if dep_city and arr_city:
        route = f"{dep_city}-{arr_city}"
    else:
        # IATA code fallback
        m = re.search(r'([A-Z]{3})\s*[-–→]\s*([A-Z]{3})', text)
        if m:
            route = f"{m.group(1)}-{m.group(2)}"

    return [{
        'pnr': pnr,
        'passenger_name': passenger_name or 'Unknown',
        'passenger_firstname': firstname,
        'passenger_lastname': lastname,
        'flight_number': flight_number or 'Unknown',
        'route': route or 'Unknown',
        'flight_date': flight_date,
        'departure_time': dep_time,
        'arrival_time': arr_time,
        'airline': 'vietjet',
        'passenger_count': extract_passenger_count(text),
    }]


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
