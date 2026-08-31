from scraper_srilankan import _try_check_pnr

def test():
    try:
        # Provide real PNR and lastname
        result = _try_check_pnr("9GRW4B", "Vanigotta")
        print("Success!", result)
    except Exception as e:
        print("Failed:", e)

if __name__ == "__main__":
    test()
