import requests
import time

pnrs = [
    ("EJ8FPI", "Khan"), # "ur Rahman Khan" -> Khan
    ("DGAMXA", "Vaishnava"),
    ("DGEUIH", "Khan"), # "Rahman Khan" -> Khan
    ("DI5THO", "Chaudhary"),
    ("DHZWU9", "Gupta"),
    ("DPDV28", "Choudhari"),
    ("DH4U95", "Choudhari"),
    ("DI50Z9", "Dhingra"),
    ("DPAP7R", "Dhingra"),
    ("DPSKL5", "Dogra"),
    ("EJ8Y79", "Shah"),
    ("DOUM8J", "Vaishnava")
]

for pnr, lastname in pnrs:
    print(f"Adding {pnr} for {lastname}...")
    try:
        response = requests.post(
            "http://127.0.0.1:8080/add_manual",
            data={
                "pnr": pnr,
                "lastname": lastname,
                "airline": "srilankan",
                "firstname": ""
            }
        )
        print(f"Result for {pnr}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Failed {pnr}: {e}")
    
    # Wait slightly between requests
    time.sleep(2)
