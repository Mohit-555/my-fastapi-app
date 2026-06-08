from sqlalchemy.orm import Session

from app.models.models import Menu


DEFAULT_MENUS = [
    {"name": "Dashboard", "slug": "dashboard", "parent_slug": None, "icon": "layout-dashboard", "sort_order": 10},
    {"name": "Alerts", "slug": "alerts", "parent_slug": None, "icon": "bell", "sort_order": 20},
    {"name": "Alert Live", "slug": "alerts.live", "parent_slug": "alerts", "icon": "radio", "sort_order": 21},
    {"name": "Alert History", "slug": "alerts.history", "parent_slug": "alerts", "icon": "history", "sort_order": 22},
    {"name": "Alert Summary", "slug": "alerts.summary", "parent_slug": "alerts", "icon": "list-checks", "sort_order": 23},
    {"name": "Telemetry", "slug": "telemetry", "parent_slug": None, "icon": "activity", "sort_order": 30},
    {"name": "Live", "slug": "telemetry.live", "parent_slug": "telemetry", "icon": "radio", "sort_order": 31},
    {"name": "History", "slug": "telemetry.history", "parent_slug": "telemetry", "icon": "history", "sort_order": 32},
    {"name": "RDPMS Health", "slug": "rdpms-health", "parent_slug": None, "icon": "heart-pulse", "sort_order": 40},
    {"name": "Live", "slug": "rdpms-health.live", "parent_slug": "rdpms-health", "icon": "radio", "sort_order": 41},
    {"name": "Summary", "slug": "rdpms-health.summary", "parent_slug": "rdpms-health", "icon": "clipboard-list", "sort_order": 42},
    {"name": "Equipment Room", "slug": "equipment-room", "parent_slug": None, "icon": "warehouse", "sort_order": 50},
    {"name": "Live", "slug": "equipment-room.live", "parent_slug": "equipment-room", "icon": "radio", "sort_order": 51},
    {"name": "History", "slug": "equipment-room.history", "parent_slug": "equipment-room", "icon": "history", "sort_order": 52},
    {"name": "Maintenance", "slug": "maintenance", "parent_slug": None, "icon": "wrench", "sort_order": 60},
    {"name": "Asset", "slug": "asset", "parent_slug": None, "icon": "boxes", "sort_order": 70},
    {"name": "Asset Detail", "slug": "asset.detail", "parent_slug": "asset", "icon": "box", "sort_order": 71},
    {"name": "Asset Utilization", "slug": "asset.utilization", "parent_slug": "asset", "icon": "chart-no-axes-combined", "sort_order": 72},
    {"name": "Performance", "slug": "performance", "parent_slug": None, "icon": "chart-line", "sort_order": 80},
    {"name": "Admin", "slug": "admin", "parent_slug": None, "icon": "shield", "sort_order": 90},
    {"name": "Profile", "slug": "profile", "parent_slug": None, "icon": "user", "sort_order": 100},
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
