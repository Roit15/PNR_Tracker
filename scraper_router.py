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
        airline: 'indigo', 'airindia', 'vietjet', 'singaporeair', 'akasaair', or 'etihad'
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

    else:
        # Default: IndiGo
        from scraper import check_pnr_status
        logger.info(f"Routing PNR {pnr} to IndiGo scraper")
        return check_pnr_status(pnr, lastname)
