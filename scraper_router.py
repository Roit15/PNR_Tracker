"""
Scraper Router — dispatches PNR checks to the correct airline scraper.
"""

import logging

logger = logging.getLogger(__name__)


def check_pnr_by_airline(pnr, lastname, airline='indigo', firstname=''):
    """
    Route PNR check to the correct airline scraper.

    Args:
        pnr: booking reference
        lastname: passenger's last name
        airline: 'indigo', 'airindia', 'vietjet', 'singaporeair', 'akasaair', 'etihad', 'thaiairways', or 'srilankan'
        firstname: passenger's first name (required for VietJet)

    Returns:
        dict with status, detail, raw_text, and optionally flight_info
    """
    airline = (airline or 'indigo').lower().strip()

    if airline == 'airindia':
        from scraper_airindia import check_pnr_status
        logger.info(f"Routing PNR {pnr} to Air India scraper")
        return check_pnr_status(pnr, lastname)

    elif airline == 'vietjet':
        from scraper_vietjet import check_pnr_status
        logger.info(f"Routing PNR {pnr} to VietJet scraper (firstname={firstname})")
        return check_pnr_status(pnr, lastname, firstname)

    elif airline == 'singaporeair':
        from scraper_singaporeair import check_pnr_status
        logger.info(f"Routing PNR {pnr} to Singapore Airlines scraper")
        return check_pnr_status(pnr, lastname)

    elif airline == 'akasaair':
        from scraper_akasaair import check_pnr_status
        logger.info(f"Routing PNR {pnr} to Akasa Air scraper")
        return check_pnr_status(pnr, lastname)

    elif airline == 'etihad':
        from scraper_etihad import check_pnr_status
        logger.info(f"Routing PNR {pnr} to Etihad Airways scraper")
        return check_pnr_status(pnr, lastname)

    elif airline == 'thaiairways':
        from scraper_thaiairways import check_pnr_status
        logger.info(f"Routing PNR {pnr} to Thai Airways scraper")
        return check_pnr_status(pnr, lastname)

    elif airline == 'srilankan':
        from scraper_srilankan import check_pnr_status
        logger.info(f"Routing PNR {pnr} to SriLankan Airlines scraper")
        return check_pnr_status(pnr, lastname)

    else:
        # Default: IndiGo — uses single-session scraper (no Akamai blocks)
        from scraper_indigo import check_pnr_status
        logger.info(f"Routing PNR {pnr} to IndiGo scraper (single-session)")
        return check_pnr_status(pnr, lastname)


def check_indigo_batch(pnr_list, on_progress=None, stop_requested_fn=None, max_workers=1):
    """
    Check multiple IndiGo PNRs in a single browser session (default: 1 worker).
    Loads the page once and checks assigned PNRs in-place.

    Args:
        pnr_list: List of (pnr, last_name) tuples
        on_progress: Optional callback fn(pnr, last_name, result, index, total)
        stop_requested_fn: Optional fn() -> bool
        max_workers: Maximum parallel workers (default: 1)

    Returns:
        List of result dicts (same order as input)
    """
    from scraper_indigo import check_multiple_pnrs
    logger.info(f"Batch-checking {len(pnr_list)} IndiGo PNR(s) with {max_workers} worker(s)")
    return check_multiple_pnrs(
        pnr_list,
        on_progress=on_progress,
        stop_requested_fn=stop_requested_fn,
        max_workers=max_workers
    )

