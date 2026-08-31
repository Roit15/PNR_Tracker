from scraper_airindia import check_pnr_status

if __name__ == "__main__":
    # Test 1: Uppercase last name
    print("Testing AH2NWZ with GARG (Uppercase)")
    res1 = check_pnr_status("AH2NWZ", "GARG")
    print(res1)
    
    # Test 2: Uppercase last name
    print("Testing AH2BX3 with RUSTAGI (Uppercase)")
    res2 = check_pnr_status("AH2BX3", "RUSTAGI")
    print(res2)
