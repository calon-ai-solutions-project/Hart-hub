"""Made-up records in the shape each scraper produces. No real vehicles, registrations or VINs."""

CARWOW = {
    "listing_id": "10000001",
    "url": "https://dealers.carwow.co.uk/dealers/listings/10000001",
    "registration": "XX20 TST",
    "vin": "TESTVIN0000000001",
    "make_model": "Land Rover Discovery Sport",
    "derivative": "2.0 D180 R-Dynamic SE 5dr Auto",
    "mileage": 41000,
    "autotrader_retail_valuation": 24500,
    "cap_clean": 20100,
    "cap_below": 17900,
    "cap_average": 19000,
    "cap_retail": 23750,
    "year_of_manufacture": "2020",
    "colour": "Black",
    "transmission": "Automatic",
    "fuel": "Diesel",
    "location": "Leeds (12 m) Exact location provided after sale is confirmed",
    "grade": "2",
    "auction_ends": "2026-10-13T14:30:00Z",
    "selling_timeframe": "Available immediately",
    "features": "Heated seats | Sat nav",
    "photo_urls": "https://img.example.test/a1 | https://img.example.test/a2",
}

MANHEIM = {
    "vehicle_id": "2000002",
    "url": "https://www.manheim.co.uk/vehicle-detail/TESTMAKE/TM?id=2000002",
    "title": "TESTMAKE TM 250d AMG Line 5dr Auto",
    "summary": "Automatic - Diesel - 2.2L - 5 Door Estate GRADE 3",
    "vehicle_information": "Make TESTMAKE Model TM Reg no XX16TST Reg date Mar 2016 Odometer 70561 Miles",
    "registration": "XX16TST",
    "mileage": 70561,
    "year": 2016,
    "colour": "Grey",
    "grade": "3",
    "cap_clean": 12800,
    "cap_average": 11650,
    "cap_retail": 15250,
    "vehicle_location": "Colchester",
    "sale_status": "In-lane / Simulcast auction",
    "sale_channel_name": "Simulcast",
    "sale_start_utc": "2026-10-13T09:00:00Z",
    "sale_end_utc": "2026-10-13T22:59:00Z",
    "lot_number": 3184,
    "is_buy_now": False,
    "buy_now_price": None,
    "current_bid": 9500,
    "specification": "Leather | Navigation",
    "photo_urls": "https://img.example.test/m1",
}

BCA = {
    "registration": "XX16 TSU",
    "vin": "TESTVIN0000000003",
    "make": "TESTMAKE",
    "model": "595",
    "derivative": "T-JET 140",
    "description": "TESTMAKE 595 1.4 T-JET 140 Hatchback",
    "plate": "2016 (16 reg)",
    "year": 2016,
    "mileage": 47828,
    "cap_clean": 4100.0,
    "price_capclean": 4100,
    "price_capaverage": 3475,
    "price_capbelowaverage": 2850,
    "price_capretail": 5795,
    "grade": "3",
    "fuel": "Petrol",
    "transmission": "Manual Transmission",
    "body_type": "Hatchback",
    "colour": "WHITE",
    "sale_channel": "InternetAuction",
    "sale_type": "Low Mileage",
    "sale_date": "2026-10-13T11:30:00Z",
    "sale_end_date": "2026-10-13T23:59:00Z",
    "vehicle_location": "Preston",
    "lot_number": "U209PR",
    "url": "https://www.bca.co.uk/lot/XX16TSU",
    "equipment": "Air Conditioning, Parking Sensor(s)",
    "photo_urls": "https://img.example.test/b1 | https://img.example.test/b2 | https://img.example.test/b3",
}

MOTORWAY = {
    "vehicle_id": 30000004,
    "registration": "XX69 TSV",
    "vin": "TESTVIN0000000004",
    "make": "Testmake",
    "model": "Transit Custom",
    "year": 2019,
    "mileage": 52000,
    "fuel": "Diesel",
    "transmission": "Manual",
    "body_type": "Commercial vehicle",
    "spec_body": "Panel van",
    "colour": "White",
    "grade": "Good",
    "price_reserve": 13890,
    "price_retail": 11995,
    "display_price": 13890,
    "highest_bid": None,
    "sale_channel": "Live sale",
    "sale_status": "For sale - Sale active",
    "sale_start_utc": "2026-10-12T15:30:00Z",
    "sale_end_utc": "2026-10-13T14:30:00Z",
    "vehicle_location": "Swansea",
    "url": "https://pro.motorway.co.uk/vehicles/30000004",
    "photo_urls": "https://img.example.test/w1 | https://img.example.test/w2",
    "photo_labels": "exterior_front_driver | photo",
}

MOTORWAY_ALERT = """\
<html><body>
<p>3 new vehicles match your saved search</p>
<a href="https://pro.motorway.co.uk/vehicles/30000004?utm_source=alert">Testmake Transit Custom</a>
<a href="https://pro.motorway.co.uk/vehicles/30000005">Another</a>
<a href="https://pro.motorway.co.uk/vehicles/30000004">Same car again</a>
<a href="https://pro.motorway.co.uk/account/settings">Manage alerts</a>
<a href="https://pro.motorway.co.uk.evil.test/vehicles/666">Not Motorway</a>
<a href="http://pro.motorway.co.uk/vehicles/777">Not https</a>
</body></html>
"""
