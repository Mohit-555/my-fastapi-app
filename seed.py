"""
Seed script — populates all 16 Railway Zones and their Divisions
from RDSO/SPN/257/2025 spec (Annexure A).

Run: python seed.py
"""
from app.database import engine, SessionLocal
from app.models.models import Base, Zone, Division

RDSO_DATA = [
    {"zone_name": "CENTRAL RAILWAY",          "zone_code": "CR",   "zone_id_hex": "00",
     "divisions": [
         {"division_name": "BHUSAVAL",  "division_code": "BSL",  "division_id_hex": "00"},
         {"division_name": "MUMBAI",    "division_code": "CSTM", "division_id_hex": "01"},
         {"division_name": "NAGPUR",    "division_code": "NGP",  "division_id_hex": "02"},
         {"division_name": "PUNE",      "division_code": "PUNE", "division_id_hex": "03"},
         {"division_name": "SOLAPUR",   "division_code": "SUR",  "division_id_hex": "04"},
     ]},
    {"zone_name": "EAST CENTRAL RAILWAY",     "zone_code": "ECR",  "zone_id_hex": "01",
     "divisions": [
         {"division_name": "DANAPUR",              "division_code": "DNR", "division_id_hex": "00"},
         {"division_name": "DHANBAD",              "division_code": "DHN", "division_id_hex": "01"},
         {"division_name": "PT. DEEN DAYAL UPADHYAYA", "division_code": "DDU", "division_id_hex": "02"},
         {"division_name": "SAMASTIPUR",           "division_code": "SPJ", "division_id_hex": "03"},
         {"division_name": "SONPUR",               "division_code": "SEE", "division_id_hex": "04"},
     ]},
    {"zone_name": "EAST COAST RAILWAY",       "zone_code": "ECoR", "zone_id_hex": "02",
     "divisions": [
         {"division_name": "KHURDA ROAD", "division_code": "KUR", "division_id_hex": "00"},
         {"division_name": "SAMBALPUR",   "division_code": "SBP", "division_id_hex": "01"},
         {"division_name": "WALTAIR",     "division_code": "WAT", "division_id_hex": "02"},
     ]},
    {"zone_name": "EASTERN RAILWAY",          "zone_code": "ER",   "zone_id_hex": "03",
     "divisions": [
         {"division_name": "ASANSOL", "division_code": "ASN",  "division_id_hex": "00"},
         {"division_name": "HOWRAH",  "division_code": "HWH",  "division_id_hex": "01"},
         {"division_name": "MALDA",   "division_code": "MLDT", "division_id_hex": "02"},
         {"division_name": "SEALDAH", "division_code": "SDAH", "division_id_hex": "03"},
     ]},
    {"zone_name": "NORTH CENTRAL RAILWAY",    "zone_code": "NCR",  "zone_id_hex": "04",
     "divisions": [
         {"division_name": "AGRA",       "division_code": "AGRA", "division_id_hex": "00"},
         {"division_name": "JHANSI",     "division_code": "JHS",  "division_id_hex": "01"},
         {"division_name": "PRAYAGRAJ",  "division_code": "PYRJ", "division_id_hex": "02"},
     ]},
    {"zone_name": "NORTH EASTERN RAILWAY",    "zone_code": "NER",  "zone_id_hex": "05",
     "divisions": [
         {"division_name": "IZZATNAGAR", "division_code": "IZN", "division_id_hex": "00"},
         {"division_name": "LUCKNOW",    "division_code": "LJN", "division_id_hex": "01"},
         {"division_name": "VARANASI",   "division_code": "BSB", "division_id_hex": "02"},
     ]},
    {"zone_name": "NORTH FRONTIER RAILWAY",   "zone_code": "NFR",  "zone_id_hex": "06",
     "divisions": [
         {"division_name": "ALIPURDUAR", "division_code": "APD", "division_id_hex": "00"},
         {"division_name": "KATIHAR",    "division_code": "KIR", "division_id_hex": "01"},
         {"division_name": "LUMDING",    "division_code": "LMG", "division_id_hex": "02"},
         {"division_name": "RANGIYA",    "division_code": "RNY", "division_id_hex": "03"},
         {"division_name": "TINSUKIA",   "division_code": "TSK", "division_id_hex": "04"},
     ]},
    {"zone_name": "NORTHERN RAILWAY",         "zone_code": "NR",   "zone_id_hex": "07",
     "divisions": [
         {"division_name": "AMBALA",    "division_code": "UMB", "division_id_hex": "00"},
         {"division_name": "DELHI",     "division_code": "DLI", "division_id_hex": "01"},
         {"division_name": "FEROZPUR",  "division_code": "FZP", "division_id_hex": "02"},
         {"division_name": "LUCKNOW",   "division_code": "LKO", "division_id_hex": "03"},
         {"division_name": "MORADABAD", "division_code": "MB",  "division_id_hex": "04"},
     ]},
    {"zone_name": "NORTH WESTERN RAILWAY",    "zone_code": "NWR",  "zone_id_hex": "08",
     "divisions": [
         {"division_name": "AJMER",   "division_code": "AII", "division_id_hex": "00"},
         {"division_name": "BIKANER", "division_code": "BKN", "division_id_hex": "01"},
         {"division_name": "JAIPUR",  "division_code": "JP",  "division_id_hex": "02"},
         {"division_name": "JODHPUR", "division_code": "JU",  "division_id_hex": "03"},
     ]},
    {"zone_name": "SOUTH CENTRAL RAILWAY",    "zone_code": "SCR",  "zone_id_hex": "09",
     "divisions": [
         {"division_name": "GUNTAKAL",      "division_code": "GTL", "division_id_hex": "00"},
         {"division_name": "GUNTUR",        "division_code": "JNT", "division_id_hex": "01"},
         {"division_name": "HYDERABAD",     "division_code": "HYB", "division_id_hex": "02"},
         {"division_name": "NANDED",        "division_code": "NED", "division_id_hex": "03"},
         {"division_name": "SECUNDERABAD",  "division_code": "SC",  "division_id_hex": "04"},
         {"division_name": "VIJAYAWADA",    "division_code": "BZA", "division_id_hex": "05"},
     ]},
    {"zone_name": "SOUTH EAST CENTRAL RAILWAY", "zone_code": "SECR", "zone_id_hex": "0A",
     "divisions": [
         {"division_name": "BILASPUR", "division_code": "BSP", "division_id_hex": "00"},
         {"division_name": "NAGPUR",   "division_code": "NGP", "division_id_hex": "01"},
         {"division_name": "RAIPUR",   "division_code": "R",   "division_id_hex": "02"},
     ]},
    {"zone_name": "SOUTH EASTERN RAILWAY",    "zone_code": "SER",  "zone_id_hex": "0B",
     "divisions": [
         {"division_name": "ADRA",         "division_code": "ADRA", "division_id_hex": "00"},
         {"division_name": "CHAKRADHARPUR","division_code": "CKP",  "division_id_hex": "01"},
         {"division_name": "KHARAGPUR",    "division_code": "KGP",  "division_id_hex": "02"},
         {"division_name": "RANCHI",       "division_code": "RNC",  "division_id_hex": "03"},
     ]},
    {"zone_name": "SOUTHERN RAILWAY",         "zone_code": "SR",   "zone_id_hex": "0C",
     "divisions": [
         {"division_name": "CHENNAI",            "division_code": "MAS", "division_id_hex": "00"},
         {"division_name": "MADURAI",            "division_code": "MDU", "division_id_hex": "01"},
         {"division_name": "PALAKKAD",           "division_code": "PGT", "division_id_hex": "02"},
         {"division_name": "SALEM",              "division_code": "SA",  "division_id_hex": "03"},
         {"division_name": "THIRUVANANTHAPURAM", "division_code": "TVC", "division_id_hex": "04"},
         {"division_name": "TIRUCHCHIRAPPALLI",  "division_code": "TPJ", "division_id_hex": "05"},
     ]},
    {"zone_name": "SOUTH WESTERN RAILWAY",    "zone_code": "SWR",  "zone_id_hex": "0D",
     "divisions": [
         {"division_name": "BENGALURU", "division_code": "SBC", "division_id_hex": "00"},
         {"division_name": "HUBBALLI",  "division_code": "UBL", "division_id_hex": "01"},
         {"division_name": "MYSURU",    "division_code": "MYS", "division_id_hex": "02"},
     ]},
    {"zone_name": "WEST CENTRAL RAILWAY",     "zone_code": "WCR",  "zone_id_hex": "0E",
     "divisions": [
         {"division_name": "BHOPAL",   "division_code": "BPL",  "division_id_hex": "00"},
         {"division_name": "JABALPUR", "division_code": "JBP",  "division_id_hex": "01"},
         {"division_name": "KOTA",     "division_code": "KOTA", "division_id_hex": "02"},
     ]},
    {"zone_name": "WESTERN RAILWAY",          "zone_code": "WR",   "zone_id_hex": "0F",
     "divisions": [
         {"division_name": "AHMEDABAD",     "division_code": "ADI", "division_id_hex": "00"},
         {"division_name": "BHAVNAGAR",     "division_code": "BVC", "division_id_hex": "01"},
         {"division_name": "MUMBAI CENTRAL","division_code": "BCT", "division_id_hex": "02"},
         {"division_name": "RAJKOT",        "division_code": "RJT", "division_id_hex": "03"},
         {"division_name": "RATLAM",        "division_code": "RTM", "division_id_hex": "04"},
         {"division_name": "VADODARA",      "division_code": "BRC", "division_id_hex": "05"},
     ]},
]


def seed():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if db.query(Zone).count() > 0:
            print("Database already seeded. Skipping.")
            return

        print("Seeding zones and divisions...")
        for z_data in RDSO_DATA:
            zone = Zone(
                zone_name=z_data["zone_name"],
                zone_code=z_data["zone_code"],
                zone_id_hex=z_data["zone_id_hex"],
            )
            db.add(zone)
            db.flush()  # get zone.id before commit

            for d_data in z_data["divisions"]:
                division = Division(
                    division_name=d_data["division_name"],
                    division_code=d_data["division_code"],
                    division_id_hex=d_data["division_id_hex"],
                    zone_id=zone.id,
                )
                db.add(division)

        db.commit()
        print(f"Seeded {len(RDSO_DATA)} zones and all divisions successfully.")

    except Exception as e:
        db.rollback()
        print(f"Seeding failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
