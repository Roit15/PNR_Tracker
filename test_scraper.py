import re
text = """Your Itinerary
Hello Shriya Samantara
DPS
DEL
11 Jul, 26
1 Pax
PNR:
N4T3PY
Confirmed
Save / Share
Modify
Upgrade to Stretch
Split PNR
Special assistance
Edit add-ons
Cancel flight
Change flight
Change seat
Update contact
Edit IndiGo BluChip ID
Web Check-in
Exclusive Rates on Delhi Hotels unlocked!
Also earn IndiGo BluChips + get up to 30%* off with code HOTELDEAL
4.3/5(110 reviews)
Alivaa Hotel Gurugram Sohna Road City Center
Gurugram
₹ 8,041/night
+ ₹ 1,448 Taxes & fees
+ Earn 644 IndiGo BluChips
Book
4.3/5(80 reviews)
Home@F37
New Delhi
₹ 3,400/night
+ ₹ 170 Taxes & fees
+ Earn 272 IndiGo BluChips
Book
4.4/5(108 reviews)
Park Plaza Gurgaon
Gurugram
₹ 6,676/night
+ ₹ 351 Taxes & fees
+ Earn 535 IndiGo BluChips
Show more
Join IndiGo BluChip!
Book flights and earn IndiGo BluChips. Enjoy a host of Tier Benefits with simplified Tier upgrades.
Departure Flight
Flight details
CHECK FLIGHT STATUS
Sat, 11 Jul
PNR:
N4T3PY
DPS
BALI
13h 25m
1 Stop
DEL
DELHI (T1)
6E 1606 . A320
Check-in closes 10:05
11:20
DPS-Bali Airport
Travel Time 06 Hour 20 min
15:10
BLR-Kempegowda International Airport(T2)
04h 20m Layover at Bengaluru
Change of aircraft
6E 870 . A321
Check-in closes 18:30
19:30
BLR-Kempegowda International Airport(T1)
Travel Time 02 Hour 45 min
22:15
DEL-Indira Gandhi International Airport(T1)
Baggage per adult and child
7KG Cabin
20KG Check-in
Passengers and Add-ons
DPS - BLR
BLR - DEL
SS
Ms. Shriya Samantara
Female
Adult
7KG Cabin bag
20KG Check-in bag
Get 50%* Off at Delhi attractions
Enjoy Free Cancellation & Earn IndiGo BluChips with IndiGo Sightseeing.
4.9
Agra
Agra Fort
starts at
₹ 429
Explore
4.9
Agra
Fatehpur Sikri
starts at
₹ 429
Explore
4.9
Agra
Mehtab Bagh (Moonlight Garden)
starts at
₹ 440
Explore
4.9
Agra
Tomb of I'timad-ud-Daulah
starts at
₹ 429
Explore
4.9
Agra
Hall of Private Audiences (Diwan-I-Khas)
starts at
₹ 8649
Explore
4.9
Agra
Korai Village
starts at
₹ 5445
Explore
4.9
New Delhi
India Gate
starts at
₹ 396
Explore
4.9
New Delhi
Qutub Minar
starts at
₹ 429
Explore
4.9
New Delhi
Humayun's Tomb
starts at
₹ 429
Explore
4.9
New Delhi
Lotus Temple (Bahá'í House of Worship)
starts at
₹ 334
Explore
Check out other add - ons
Most popular add-ons
Get 20% off
up to 200
6E Prime
Most Popular add Ons
Get 20% off
up to 200
6E Seat And Eat
Popular
Fast Forward
6E Eats
Popular
6E Bar
Popular
Baggage
Popular
Pillow & Blanket
Popular
6E QuickBoard
Popular
Lounge
Popular
Zero Cancellation
Additional Piece
Popular
Sports Equipment
Most popular add-ons
Get 20% off
up to 200
6E Prime
Personalized Bundle
Payment Details
Fare details
Saver
AirFare Charge
€165
Fuel Charge
€45
Arrival User Development Fee
€2.93
Passenger Service Charge (International)
€12
€224.93
TOTAL FARE
€224.93
Contact Details
Number: 17****70
E - mail: a****e@gmail.com
RETRIEVE ANOTHER BOOKING
Skip the queue. 100% Confirmed Rides.
Need help with your booking?
Chat with us
About any issue related to your booking
Explore Delhi
Shriya Samantara, ready to explore Delhi?
Explore places
Explore other areas
More information
Note
Baggage Allowance : Saver fare Sector
DPS-DEL
Terms & Conditions
Terminal Information
Flight Delay or Cancellation"""

date_range_match = re.search(r"(\d{1,2})\s+([A-Za-z]{3}),?\s*(\d{2,4})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]{3}),?\s*(\d{2,4})", text)
print("date_range_match:", date_range_match)
codes = re.findall(r"^([A-Z]{3})$", text, re.MULTILINE)
print("codes:", codes)

from scraper import extract_flight_info_from_web
print("extracted:", extract_flight_info_from_web(text, "Samantara"))
