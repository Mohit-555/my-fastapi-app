from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.models import Menu, Role, User, RoleMenu, Zone, Division, Station, EquipmentRoom, AssetInventory, AlertEvent, Gateway, Telemetry, MaintenanceMode
from app.auth_utils import hash_password


DEFAULT_MENUS = [
    {"name": "Dashboard", "slug": "dashboard", "parent_slug": None, "icon": "LayoutDashboard", "sort_order": 10},
    {"name": "Alerts", "slug": "alerts", "parent_slug": None, "icon": "Bell", "sort_order": 20},
    {"name": "Alert Live", "slug": "alerts.live", "parent_slug": "alerts", "icon": "Bell", "sort_order": 21},
    {"name": "Alert History", "slug": "alerts.history", "parent_slug": "alerts", "icon": "History", "sort_order": 22},
    {"name": "Alert Summary", "slug": "alerts.summary", "parent_slug": "alerts", "icon": "ListChecks", "sort_order": 23},
    {"name": "Telemetry", "slug": "telemetry", "parent_slug": None, "icon": "Radio", "sort_order": 30},
    {"name": "Live", "slug": "telemetry.live", "parent_slug": "telemetry", "icon": "Radio", "sort_order": 31},
    {"name": "History", "slug": "telemetry.history", "parent_slug": "telemetry", "icon": "History", "sort_order": 32},
    {"name": "RDPMS Health", "slug": "rdpms-health", "parent_slug": None, "icon": "Activity", "sort_order": 40},
    {"name": "Live", "slug": "rdpms-health.live", "parent_slug": "rdpms-health", "icon": "Activity", "sort_order": 41},
    {"name": "Summary", "slug": "rdpms-health.summary", "parent_slug": "rdpms-health", "icon": "ListChecks", "sort_order": 42},
    {"name": "Equipment Room", "slug": "equipment-room", "parent_slug": None, "icon": "Server", "sort_order": 50},
    {"name": "Live", "slug": "equipment-room.live", "parent_slug": "equipment-room", "icon": "Server", "sort_order": 51},
    {"name": "History", "slug": "equipment-room.history", "parent_slug": "equipment-room", "icon": "History", "sort_order": 52},
    {"name": "Maintenance", "slug": "maintenance", "parent_slug": None, "icon": "Wrench", "sort_order": 60},
    {"name": "Asset", "slug": "asset", "parent_slug": None, "icon": "Cpu", "sort_order": 70},
    {"name": "Asset Detail", "slug": "asset.detail", "parent_slug": "asset", "icon": "Cpu", "sort_order": 71},
    {"name": "Asset Utilization", "slug": "asset.utilization", "parent_slug": "asset", "icon": "Gauge", "sort_order": 72},
    {"name": "Performance", "slug": "performance", "parent_slug": None, "icon": "Gauge", "sort_order": 80},
    {"name": "Admin", "slug": "admin", "parent_slug": None, "icon": "Settings", "sort_order": 90},
    {"name": "Profile", "slug": "profile", "parent_slug": None, "icon": "User", "sort_order": 100},
]

DEFAULT_ROLES = [
    {
        "id": 1,
        "name": "HQ_ADMIN",
        "display_name": "Headquarters Administrator",
        "level": 1,
        "description": "Full system administration access across all zones, divisions, stations, and configuration modules."
    },
    {
        "id": 2,
        "name": "HQ_MONITOR",
        "display_name": "HQ Monitoring Officer",
        "level": 2,
        "description": "Monitors nationwide asset health, alerts, telemetry, and performance dashboards."
    },
    {
        "id": 3,
        "name": "DIVISION_ADMIN",
        "display_name": "Division Administrator",
        "level": 3,
        "description": "Administrative access limited to assigned division assets, users, and reports."
    },
    {
        "id": 4,
        "name": "DIVISION_ENGINEER",
        "display_name": "Division Engineer",
        "level": 4,
        "description": "Responsible for monitoring, diagnostics, maintenance planning, and alert management."
    },
    {
        "id": 5,
        "name": "STATION_MASTER",
        "display_name": "Station Master",
        "level": 5,
        "description": "Operational access for station-level monitoring and equipment status review."
    },
    {
        "id": 6,
        "name": "MAINTENANCE_ENGINEER",
        "display_name": "Maintenance Engineer",
        "level": 6,
        "description": "Maintenance operations and diagnostic checks for station assets."
    },
    {
        "id": 7,
        "name": "GUEST",
        "display_name": "Guest User",
        "level": 7,
        "description": "Read-only guest access for general system review."
    },
    {
        "id": 8,
        "name": "AUDITOR",
        "display_name": "Audit Guest User",
        "level": 8,
        "description": "Auditing and report verification access."
    },
]

# Map of menu slug to list of allowed role IDs
ROLE_MAP = {
    "dashboard": [1, 2, 3, 4, 5, 6, 7, 8],
    "alerts": [1, 2, 3, 4, 5, 6],
    "alerts.live": [1, 2, 3, 4, 5, 6],
    "alerts.history": [1, 2, 3, 4, 5, 6],
    "alerts.summary": [1, 2, 3, 4],
    "telemetry": [1, 2, 3, 4, 5, 6],
    "telemetry.live": [1, 2, 3, 4, 5, 6],
    "telemetry.history": [1, 2, 3, 4],
    "rdpms-health": [1, 2, 3, 4],
    "rdpms-health.live": [1, 2, 3, 4],
    "rdpms-health.summary": [1, 2],
    "equipment-room": [1, 2, 3, 4, 5, 6],
    "equipment-room.live": [1, 2, 3, 4, 5, 6],
    "equipment-room.history": [1, 2, 3, 4],
    "maintenance": [1, 2, 3, 4, 5, 6],
    "asset": [1, 2, 3, 4],
    "asset.detail": [1, 2, 3, 4],
    "asset.utilization": [1, 2],
    "performance": [1, 2, 3, 4],
    "admin": [1, 2],
    "profile": [1, 2, 3, 4, 5, 6, 7, 8],
}

DEFAULT_USERS = [
    {
        "employee_id": "hq_admin",
        "full_name": "HQ Administrator",
        "role_id": 1,
        "email": "hq.admin@rdpms.gov.in",
        "mobile_number": "9876543210",
        "designation": "Director Signal",
        "zone_code": None,
        "division_code": None,
        "is_active": True,
    },
    {
        "employee_id": "hq_ops",
        "full_name": "HQ Operations Manager",
        "role_id": 2,
        "email": "hq.ops@rdpms.gov.in",
        "mobile_number": "9876543216",
        "designation": "ED Signal",
        "zone_code": None,
        "division_code": None,
        "is_active": False,
    },
    {
        "employee_id": "div_north",
        "full_name": "Division Engineer - North",
        "role_id": 4,
        "email": "div.north@rdpms.gov.in",
        "mobile_number": "9876543211",
        "designation": "Sr DSTE",
        "zone_code": "NR",
        "division_code": "DLI",
        "is_active": True,
    },
    {
        "employee_id": "div_lko",
        "full_name": "Division Engineer - Lucknow",
        "role_id": 3,
        "email": "div.lko@rdpms.gov.in",
        "mobile_number": "9876543213",
        "designation": "DSTE",
        "zone_code": "NER",
        "division_code": "LJN",
        "is_active": True,
    },
    {
        "employee_id": "div_pryj",
        "full_name": "Division Engineer - Prayagraj",
        "role_id": 4,
        "email": "div.pryj@rdpms.gov.in",
        "mobile_number": "9876543217",
        "designation": "Sr DSTE",
        "zone_code": "NCR",
        "division_code": "PYRJ",
        "is_active": True,
    },
    {
        "employee_id": "sm_ndls",
        "full_name": "SM New Delhi",
        "role_id": 5,
        "email": "sm.ndls@rdpms.gov.in",
        "mobile_number": "9876543212",
        "designation": "Station Master",
        "zone_code": "NR",
        "division_code": "DLI",
        "is_active": False,
    },
    {
        "employee_id": "sm_lko",
        "full_name": "SM Lucknow",
        "role_id": 5,
        "email": "sm.lko@rdpms.gov.in",
        "mobile_number": "9876543214",
        "designation": "Station Master",
        "zone_code": "NER",
        "division_code": "LJN",
        "is_active": True,
    },
    {
        "employee_id": "sm_agc",
        "full_name": "SM Agra Cantt",
        "role_id": 5,
        "email": "sm.agc@rdpms.gov.in",
        "mobile_number": "9876543218",
        "designation": "Station Master",
        "zone_code": "NCR",
        "division_code": "AGRA",
        "is_active": True,
    },
    {
        "employee_id": "guest_user",
        "full_name": "Guest User",
        "role_id": 7,
        "email": "guest@rdpms.gov.in",
        "mobile_number": "9876543215",
        "designation": "Visitor",
        "zone_code": None,
        "division_code": None,
        "is_active": True,
    },
    {
        "employee_id": "guest_audit",
        "full_name": "Audit Guest User",
        "role_id": 8,
        "email": "guest.audit@rdpms.gov.in",
        "mobile_number": "9876543219",
        "designation": "Auditor",
        "zone_code": None,
        "division_code": None,
        "is_active": False,
    },
]


def ensure_default_menus(db: Session) -> None:
    # Clean up obsolete menus using ORM to trigger cascades
    active_slugs = {item["slug"] for item in DEFAULT_MENUS}
    obsolete_menus = db.query(Menu).filter(Menu.slug.not_in(list(active_slugs))).all()
    for menu in obsolete_menus:
        db.delete(menu)
    db.commit()

    for item in DEFAULT_MENUS:
        menu = db.query(Menu).filter(Menu.slug == item["slug"]).first()
        if menu:
            for field, value in item.items():
                setattr(menu, field, value)
            menu.is_active = True
        else:
            db.add(Menu(**item, is_active=True))
    db.commit()


def ensure_default_roles_users_and_permissions(db: Session) -> None:
    # 1. Ensure Roles
    for r_data in DEFAULT_ROLES:
        role = db.query(Role).filter(Role.id == r_data["id"]).first()
        if role:
            role.name = r_data["name"]
            role.display_name = r_data["display_name"]
            role.level = r_data["level"]
            role.description = r_data["description"]
            role.is_active = True
        else:
            role = Role(
                id=r_data["id"],
                name=r_data["name"],
                display_name=r_data["display_name"],
                level=r_data["level"],
                description=r_data["description"],
                is_active=True
            )
            db.add(role)
    db.commit()

    # Reset roles sequence (only on PostgreSQL)
    try:
        db.execute(text("SELECT setval('roles_id_seq', COALESCE((SELECT MAX(id) FROM roles), 1), false);"))
        db.commit()
    except Exception:
        db.rollback()

    # 2. Ensure Menu Access Permissions (RoleMenu)
    # Clear existing permissions to avoid conflicts and match Imran's map exactly
    db.query(RoleMenu).delete()
    db.commit()

    for slug, role_ids in ROLE_MAP.items():
        menu = db.query(Menu).filter(Menu.slug == slug).first()
        if not menu:
            continue
        for role_id in role_ids:
            role = db.query(Role).filter(Role.id == role_id).first()
            if not role:
                continue
            db.add(RoleMenu(role_id=role_id, menu_id=menu.id, permission="full" if role_id == 1 else "view"))
    db.commit()

    # 3. Ensure Users
    default_password_hash = hash_password("Password@123")

    for u_data in DEFAULT_USERS:
        # Resolve zone and division
        zone_id = None
        if u_data["zone_code"]:
            zone = db.query(Zone).filter(Zone.zone_code == u_data["zone_code"]).first()
            if zone:
                zone_id = zone.id

        division_id = None
        if u_data["division_code"]:
            div = db.query(Division).filter(Division.division_code == u_data["division_code"]).first()
            if div:
                division_id = div.id

        user = db.query(User).filter(User.employee_id == u_data["employee_id"]).first()
        if user:
            user.full_name = u_data["full_name"]
            user.role_id = u_data["role_id"]
            user.email = u_data["email"]
            user.mobile_number = u_data["mobile_number"]
            user.designation = u_data["designation"]
            user.zone_id = zone_id
            user.division_id = division_id
            user.is_active = u_data["is_active"]
        else:
            user = User(
                employee_id=u_data["employee_id"],
                full_name=u_data["full_name"],
                role_id=u_data["role_id"],
                email=u_data["email"],
                mobile_number=u_data["mobile_number"],
                designation=u_data["designation"],
                zone_id=zone_id,
                division_id=division_id,
                hashed_password=default_password_hash,
                is_active=u_data["is_active"]
            )
            db.add(user)
    db.commit()

    # 4. Ensure Default Stations & Equipment Rooms
    DEFAULT_STATIONS = [
        {"station_code": "LKO", "station_name": "Lucknow", "station_id_hex": "01", "division_code": "LKO"},
        {"station_code": "NDLS", "station_name": "New Delhi", "station_id_hex": "02", "division_code": "DLI"},
        {"station_code": "MJA", "station_name": "Meja Road", "station_id_hex": "03", "division_code": "PYRJ"},
        {"station_code": "HWH", "station_name": "Howrah", "station_id_hex": "04", "division_code": "HWH"},
        {"station_code": "PRYG", "station_name": "Prayagraj Ghat", "station_id_hex": "05", "division_code": "LKO"},
        {"station_code": "AGC", "station_name": "Agra Cantt", "station_id_hex": "06", "division_code": "AGRA"},
        {"station_code": "CNB", "station_name": "Kanpur Central", "station_id_hex": "07", "division_code": "LKO"},
        {"station_code": "UMB", "station_name": "Ambala Cantt", "station_id_hex": "08", "division_code": "UMB"},
    ]

    for st_data in DEFAULT_STATIONS:
        div = db.query(Division).filter(
            (Division.division_code == st_data["division_code"]) |
            (Division.division_code == "PYRJ" if st_data["division_code"] == "PRYJ" else False) |
            (Division.division_code == "AGRA" if st_data["division_code"] == "AGC" else False)
        ).first()
        if not div:
            continue
        
        station = db.query(Station).filter(Station.station_code == st_data["station_code"]).first()
        if not station:
            station = Station(
                station_code=st_data["station_code"],
                station_name=st_data["station_name"],
                station_id_hex=st_data["station_id_hex"],
                division_id=div.id
            )
            db.add(station)
            db.flush()
        
        for room_type in ["RR", "IPS", "BATT"]:
            room = db.query(EquipmentRoom).filter(
                EquipmentRoom.station_id == station.id,
                EquipmentRoom.room_type == room_type
            ).first()
            if not room:
                room = EquipmentRoom(
                    station_id=station.id,
                    room_type=room_type,
                    temperature=None,
                    humidity=None
                )
                db.add(room)
    db.commit()

    # 5. Ensure Default Asset Inventories
    DEFAULT_INVENTORIES = [
        {"station_code": "LKO", "asset_type_hex": "00", "asset_make": "Alstom", "count": 18},
        {"station_code": "LKO", "asset_type_hex": "10", "asset_make": "Siemens", "count": 24},
        {"station_code": "LKO", "asset_type_hex": "20", "asset_make": "Ansaldo", "count": 12},
        {"station_code": "NDLS", "asset_type_hex": "00", "asset_make": "Siemens", "count": 32},
        {"station_code": "NDLS", "asset_type_hex": "10", "asset_make": "Alstom", "count": 40},
        {"station_code": "NDLS", "asset_type_hex": "20", "asset_make": "Siemens", "count": 15},
        {"station_code": "MJA", "asset_type_hex": "00", "asset_make": "CEL", "count": 8},
        {"station_code": "MJA", "asset_type_hex": "10", "asset_make": "Siemens", "count": 12},
        {"station_code": "HWH", "asset_type_hex": "00", "asset_make": "Alstom", "count": 45},
        {"station_code": "HWH", "asset_type_hex": "10", "asset_make": "Siemens", "count": 50},
    ]

    for inv_data in DEFAULT_INVENTORIES:
        station = db.query(Station).filter(Station.station_code == inv_data["station_code"]).first()
        if not station:
            continue
        
        record = db.query(AssetInventory).filter(
            AssetInventory.station_id == station.id,
            AssetInventory.asset_type_hex == inv_data["asset_type_hex"],
            AssetInventory.asset_make == inv_data["asset_make"]
        ).first()
        if not record:
            record = AssetInventory(
                station_id=station.id,
                asset_type_hex=inv_data["asset_type_hex"],
                asset_make=inv_data["asset_make"],
                count=inv_data["count"]
            )
            db.add(record)
    db.commit()

    # 6. Ensure Default Alert Events
    from datetime import datetime, timezone
    
    DEFAULT_ALERTS = [
        {
            "station_code": "LKO",
            "alert_type": "Failure",
            "asset_type_hex": "00",
            "asset_no": "PT-103",
            "cause": "PT-OBS",
            "alert_status": "Active",
            "feedback": None,
            "acknowledged": False,
            "remark": None,
            "alert_time": datetime(2026, 6, 9, 10, 49, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "PRYG",
            "alert_type": "Predictive",
            "asset_type_hex": "20",
            "asset_no": "TC-12",
            "cause": "TC-SHUNT",
            "alert_status": "Acknowledged",
            "feedback": "T",
            "acknowledged": True,
            "remark": "Found stone chip",
            "alert_time": datetime(2026, 6, 9, 9, 19, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "AGC",
            "alert_type": "Failure",
            "asset_type_hex": "21",
            "asset_no": "AC-05",
            "cause": "COMM-FAIL",
            "alert_status": "Cleared",
            "feedback": None,
            "acknowledged": False,
            "remark": None,
            "alert_time": datetime(2026, 6, 9, 7, 19, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "NDLS",
            "alert_type": "Predictive",
            "asset_type_hex": "10",
            "asset_no": "MS-21",
            "cause": "TEMP-HIGH",
            "alert_status": "Active",
            "feedback": "PT",
            "acknowledged": False,
            "remark": "Partial dust issue",
            "alert_time": datetime(2026, 6, 9, 10, 19, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "MJA",
            "alert_type": "Failure",
            "asset_type_hex": "00",
            "asset_no": "PM-101",
            "cause": "MOTOR-OC",
            "alert_status": "Cleared",
            "feedback": None,
            "acknowledged": False,
            "remark": None,
            "alert_time": datetime(2026, 6, 9, 6, 19, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "HWH",
            "alert_type": "Failure",
            "asset_type_hex": "20",
            "asset_no": "TC-08",
            "cause": "TC-SHUNT",
            "alert_status": "Cleared",
            "feedback": None,
            "acknowledged": False,
            "remark": None,
            "alert_time": datetime(2026, 6, 9, 5, 19, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "CNB",
            "alert_type": "Predictive",
            "asset_type_hex": "41",
            "asset_no": "LCG-03",
            "cause": "BAT-LOW",
            "alert_status": "Active",
            "feedback": None,
            "acknowledged": False,
            "remark": None,
            "alert_time": datetime(2026, 6, 9, 8, 19, 30, tzinfo=timezone.utc),
        },
        {
            "station_code": "UMB",
            "alert_type": "Predictive",
            "asset_type_hex": "21",
            "asset_no": "AC-11",
            "cause": "COMM-FAIL",
            "alert_status": "Cleared",
            "feedback": None,
            "acknowledged": False,
            "remark": None,
            "alert_time": datetime(2026, 6, 9, 4, 19, 30, tzinfo=timezone.utc),
        },
     ]

    for alert_data in DEFAULT_ALERTS:
        station = db.query(Station).filter(Station.station_code == alert_data["station_code"]).first()
        if not station:
            continue
        
        record = db.query(AlertEvent).filter(
            AlertEvent.station_id == station.id,
            AlertEvent.asset_no == alert_data["asset_no"],
            AlertEvent.cause == alert_data["cause"]
        ).first()
        if not record:
            record = AlertEvent(
                station_id=station.id,
                alert_type=alert_data["alert_type"],
                asset_type_hex=alert_data["asset_type_hex"],
                asset_no=alert_data["asset_no"],
                cause=alert_data["cause"],
                alert_status=alert_data["alert_status"],
                feedback=alert_data["feedback"],
                acknowledged=alert_data["acknowledged"],
                remark=alert_data["remark"],
                alert_time=alert_data["alert_time"]
            )
            db.add(record)
    db.commit()

    # 7. Ensure Default Gateways & Telemetry
    gateways_by_station = {}
    for st_code, stngw_id in [
        ("LKO", "01011200"),
        ("NDLS", "02011200"),
        ("MJA", "03011200"),
        ("HWH", "04011200"),
        ("PRYG", "05011200"),
        ("AGC", "06011200"),
        ("CNB", "07011200"),
        ("UMB", "08011200"),
    ]:
        station = db.query(Station).filter(Station.station_code == st_code).first()
        if not station:
            continue
        gw = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
        if not gw:
            gw = Gateway(
                stngw_id=stngw_id,
                station_id=station.id,
                imei=f"imei_{stngw_id}"
            )
            db.add(gw)
            db.flush()
        gateways_by_station[station.id] = gw.id

    # Seed Telemetry for PT-101 and TC-12
    from datetime import datetime, timedelta

    # Define base values (reusable lists)
    pt_base = [
        (1, [4.28, 5.91, 2474.0, 11.93, 34.7]),  # offset minute, values
        (1, [3.98, 7.22, 2595.0, 12.28, 35.1]),  # note: multiple samples at same 12:05
        (1, [3.65, 7.81, 2566.0, 12.18, 36.4]),
        (1, [3.15, 7.59, 2384.0, 12.23, 38.7]),
        (1, [2.73, 6.68, 2282.0, 12.38, 43.1]),
        (2, [4.28, 5.65, 2126.0, 11.81, 36.0]),
        (3, [4.38, 6.01, 2076.0, 12.28, 35.5]),
        (4, [4.16, 6.25, 2093.0, 11.97, 34.3]),
        (5, [4.04, 6.44, 2091.0, 11.84, 35.3]),
        (6, [4.21, 6.68, 2001.0, 11.87, 34.6]),
    ]

    tc_base = [
        (2, [4.37, 5.71, 2154.0, 12.28, 36.1]),
        (3, [4.18, 5.87, 2073.0, 12.29, 35.7]),
        (4, [4.34, 6.42, 2076.0, 11.95, 35.0]),
        (5, [4.32, 6.73, 2087.0, 12.21, 34.4]),
        (6, [4.01, 6.95, 2083.0, 12.13, 35.2]),
        (7, [3.96, 6.82, 2063.0, 12.24, 36.1]),
        (8, [3.79, 7.30, 2022.0, 11.81, 35.4]),
        (9, [3.70, 7.39, 1942.0, 11.87, 35.0]),
        (10, [3.84, 7.53, 1988.0, 11.96, 36.8]),
    ]

    # Generate dates to seed
    now_utc = datetime.utcnow()
    # dynamic local time for the display string (prt) in Indian Standard Time (+5:30)
    now_local = now_utc + timedelta(hours=5, minutes=30)

    # We will build a list of tuples: (received_at, prt, vals)
    pt_final_points = []
    tc_final_points = []

    # 1. Add Dynamic relative points (re-calculates every startup so last hour query is always populated!)
    for min_offset, vals in pt_base:
        dt_utc = now_utc - timedelta(minutes=min_offset)
        dt_local = now_local - timedelta(minutes=min_offset)
        pt_final_points.append((dt_utc, dt_local.strftime("%H:%M"), vals))

    for min_offset, vals in tc_base:
        dt_utc = now_utc - timedelta(minutes=min_offset)
        dt_local = now_local - timedelta(minutes=min_offset)
        tc_final_points.append((dt_utc, dt_local.strftime("%H:%M"), vals))

    # 2. Add Static June 9, 2026 points (both naive UTC=local, and UTC-adjusted 06:35/12:05)
    # This guarantees that explicit date/time filters for 2026-06-09 will return exactly the screenshots
    for min_offset, vals in pt_base:
        # Static local time
        st_dt_local = datetime(2026, 6, 9, 12, 6, 0) - timedelta(minutes=min_offset)
        # 2a. Naive UTC = Local value (12:05 etc.)
        pt_final_points.append((st_dt_local, st_dt_local.strftime("%H:%M"), vals))
        # 2b. Naive UTC = UTC value (06:35 etc.)
        st_dt_utc = st_dt_local - timedelta(hours=5, minutes=30)
        pt_final_points.append((st_dt_utc, st_dt_local.strftime("%H:%M"), vals))

    for min_offset, vals in tc_base:
        st_dt_local = datetime(2026, 6, 9, 12, 6, 0) - timedelta(minutes=min_offset)
        tc_final_points.append((st_dt_local, st_dt_local.strftime("%H:%M"), vals))
        st_dt_utc = st_dt_local - timedelta(hours=5, minutes=30)
        tc_final_points.append((st_dt_utc, st_dt_local.strftime("%H:%M"), vals))

    # Seed
    for gw_id in gateways_by_station.values():
        # Seed PT-101
        for dt_utc, prt, vals in pt_final_points:
            for idx, p_hex in enumerate(["01", "02", "03", "04", "05"]):
                para_id = f"0001{p_hex}00"
                exists = db.query(Telemetry).filter(
                    Telemetry.gateway_id == gw_id,
                    Telemetry.para_id == para_id,
                    Telemetry.received_at == dt_utc
                ).first()
                if not exists:
                    db.add(Telemetry(
                        gateway_id=gw_id,
                        para_id=para_id,
                        prv=vals[idx],
                        prt=prt,
                        received_at=dt_utc
                    ))

        # Seed TC-12
        for dt_utc, prt, vals in tc_final_points:
            for idx, p_hex in enumerate(["01", "02", "03", "04", "05"]):
                para_id = f"200C{p_hex}00"
                exists = db.query(Telemetry).filter(
                    Telemetry.gateway_id == gw_id,
                    Telemetry.para_id == para_id,
                    Telemetry.received_at == dt_utc
                ).first()
                if not exists:
                    db.add(Telemetry(
                        gateway_id=gw_id,
                        para_id=para_id,
                        prv=vals[idx],
                        prt=prt,
                        received_at=dt_utc
                    ))
    db.commit()

    # 8. Ensure Default Maintenance Mode Records
    cnb_station = db.query(Station).filter(Station.station_code == "CNB").first()
    if cnb_station:
        exists = db.query(MaintenanceMode).filter(
            MaintenanceMode.station_id == cnb_station.id,
            MaintenanceMode.asset_type_hex == "20",
            MaintenanceMode.asset_no == "TC-12"
        ).first()
        if not exists:
            db.add(MaintenanceMode(
                station_id=cnb_station.id,
                asset_type_hex="20",
                asset_no="TC-12",
                from_time=datetime(2026, 6, 9, 9, 19, 30),
                to_time=datetime(2026, 6, 9, 11, 19, 30),
                created_at=datetime(2026, 6, 9, 9, 19, 30)
            ))
            db.commit()
