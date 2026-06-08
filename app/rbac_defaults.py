from sqlalchemy.orm import Session

from app.models.models import Menu


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
    {"name": "User Management", "slug": "admin.users", "parent_slug": "admin", "icon": "User", "sort_order": 91},
    {"name": "Role Management", "slug": "admin.roles", "parent_slug": "admin", "icon": "Shield", "sort_order": 92},
    {"name": "Alert Thresholds", "slug": "admin.alert-thresholds", "parent_slug": "admin", "icon": "SlidersHorizontal", "sort_order": 93},
    {"name": "Additional Settings", "slug": "admin.settings", "parent_slug": "admin", "icon": "Settings", "sort_order": 94},
    {"name": "Profile", "slug": "profile", "parent_slug": None, "icon": "User", "sort_order": 100},
]


def ensure_default_menus(db: Session) -> None:
    for item in DEFAULT_MENUS:
        menu = db.query(Menu).filter(Menu.slug == item["slug"]).first()
        if menu:
            for field, value in item.items():
                setattr(menu, field, value)
            menu.is_active = True
        else:
            db.add(Menu(**item, is_active=True))
    db.commit()
