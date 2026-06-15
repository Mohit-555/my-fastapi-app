from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, ForeignKey, Text, UniqueConstraint, Enum
from sqlalchemy.orm import relationship
from datetime import datetime,UTC
from typing import Optional
from app.database import Base


MENU_PATH_OVERRIDES = {
    "admin.users": "/admin/user-role-management/users",
    "admin.roles": "/admin/user-role-management/roles",
    "admin.alert-thresholds": "/admin/alert-thresholds",
    "admin.settings": "/admin/settings",
}


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)
    zone_name = Column(String, nullable=False)
    zone_code = Column(String(10), unique=True, nullable=False)
    zone_id_hex = Column(String(2), unique=True, nullable=False)
    headquarters = Column(String, nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, default="Active", nullable=True)

    divisions = relationship("Division", back_populates="zone", cascade="all, delete-orphan")


class Division(Base):
    __tablename__ = "divisions"

    id = Column(Integer, primary_key=True, index=True)
    division_name = Column(String, nullable=False)
    division_code = Column(String(10), nullable=False)
    division_id_hex = Column(String(2), nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)
    headquarters = Column(String, nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, default="Active", nullable=True)

    zone = relationship("Zone", back_populates="divisions")
    stations = relationship("Station", back_populates="division", cascade="all, delete-orphan")


class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    station_name = Column(String, nullable=False)
    station_code = Column(String(10), nullable=False)
    station_id_hex = Column(String(2), nullable=False)
    division_id = Column(Integer, ForeignKey("divisions.id"), nullable=False)
    category = Column(String, nullable=True)
    address = Column(String, nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, default="Active", nullable=True)

    division = relationship("Division", back_populates="stations")
    gateways = relationship("Gateway", back_populates="station", cascade="all, delete-orphan")
    asset_inventory = relationship("AssetInventory", back_populates="station", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="station", cascade="all, delete-orphan")
    alert_events = relationship("AlertEvent", back_populates="station", cascade="all, delete-orphan")


class Gateway(Base):
    __tablename__ = "gateways"

    id = Column(Integer, primary_key=True, index=True)
    stngw_id = Column(String(8), unique=True, nullable=False, index=True)
    imei = Column(String(20), nullable=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now(UTC))

    station = relationship("Station", back_populates="gateways")
    telemetry = relationship("Telemetry", back_populates="gateway", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="gateway", cascade="all, delete-orphan", primaryjoin="Gateway.stngw_id == Asset.station_gateway_id")


class Telemetry(Base):
    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True, index=True)
    gateway_id = Column(Integer, ForeignKey("gateways.id"), nullable=False)
    para_id = Column(String(8), nullable=False, index=True)
    prv = Column(Float, nullable=True)
    prt = Column(String(30), nullable=True)
    raw_payload = Column(Text, nullable=True)
    received_at = Column(DateTime, default=datetime.now(UTC))

    gateway = relationship("Gateway", back_populates="telemetry")


class AssetInventory(Base):
    """
    Stores asset inventory counts for the Asset Detail screen.

    Each row represents the count of a given asset type and make at a station.
    """
    __tablename__ = "asset_inventory"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    asset_type_hex = Column(String(2), nullable=False, index=True)
    asset_make = Column(String(80), nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now(UTC))
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    station = relationship("Station", back_populates="asset_inventory")

    @property
    def asset_type(self) -> str:
        from app.constants import ASSET_TYPE_MAP
        info = ASSET_TYPE_MAP.get(self.asset_type_hex)
        return info[1] if info else self.asset_type_hex

    __table_args__ = (
        UniqueConstraint(
            "station_id", "asset_type_hex", "asset_make",
            name="uq_asset_inventory_station_type_make"
        ),
    )




class Threshold(Base):
    """
    Stores warning and critical thresholds for a given asset type + parameter type
    combination. Optionally scoped to a specific station for station-level overrides.

    Lookup priority: station-specific → asset-type default (station_id IS NULL).

    asset_type_hex  = bytes 0-1 of para_id  (e.g. "00" = Point Machine)
    parameter_type_hex = bytes 4-5 of para_id (e.g. "02" = Peak Current)
    """
    __tablename__ = "thresholds"

    id = Column(Integer, primary_key=True, index=True)
    asset_type_hex = Column(String(2), nullable=False, index=True)
    parameter_type_hex = Column(String(2), nullable=False, index=True)

    # Optional: if set, overrides the global default for this station
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True, index=True)

    warning_low  = Column(Float, nullable=True)   # lower warning bound
    warning_high = Column(Float, nullable=True)   # upper warning bound
    critical_low = Column(Float, nullable=True)   # lower critical bound
    critical_high = Column(Float, nullable=True)  # upper critical bound

    unit = Column(String(20), nullable=True)       # display unit, e.g. "A", "V", "ms"
    description = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=datetime.now(UTC))
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    station = relationship("Station")

    __table_args__ = (
        UniqueConstraint(
            "asset_type_hex", "parameter_type_hex", "station_id",
            name="uq_threshold_asset_param_station"
        ),
    )


class AlertEvent(Base):
    """
    Stores generated or operator-entered alert events.
    Alert Summary aggregates these rows by location, asset, alert type, and cause.
    feedback uses: T=true, PT=partially true, F=false, M=monitoring/maintenance.
    """
    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    alert_type = Column(String(20), nullable=False, index=True)
    asset_type_hex = Column(String(2), nullable=False, index=True)
    asset_no = Column(String(40), nullable=False, index=True)
    cause = Column(String(100), nullable=False, index=True)
    alert_status = Column(String(20), nullable=False, default="Active", index=True)
    feedback = Column(String(2), nullable=True, index=True)
    acknowledged = Column(Boolean, nullable=False, default=False)
    remark = Column(Text, nullable=True)
    alert_time = Column(DateTime, default=datetime.now(UTC), nullable=False, index=True)
    rectification_time = Column(DateTime, nullable=True, index=True)
    feedback_time = Column(DateTime, nullable=True, index=True)
    maintainer_name = Column(String(100), nullable=True)
    designation = Column(String(100), nullable=True)
    mobile = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.now(UTC))
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    station = relationship("Station", back_populates="alert_events")
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True, index=True)
    asset = relationship("Asset")

    # Logical relationships (no DB migrations needed)
    asset_type = relationship(
        "AssetTypeMaster",
        primaryjoin="foreign(AlertEvent.asset_type_hex) == AssetTypeMaster.asset_type_id",
        uselist=False,
        viewonly=True
    )

    cause_master = relationship(
        "AlertCauseMaster",
        primaryjoin="foreign(AlertEvent.cause) == AlertCauseMaster.cause_code",
        uselist=False,
        viewonly=True
    )

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    designation = Column(String(50), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True, index=True)  # ← NEW
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    division_id = Column(Integer, ForeignKey("divisions.id"), nullable=True)
    mobile_number = Column(String(15), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    reporting_officer_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(UTC))

    role = relationship("Role", back_populates="users")                           # ← NEW
    zone = relationship("Zone")
    division = relationship("Division")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    remember_me = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now(UTC))

    user = relationship("User", back_populates="refresh_tokens")

# ── RBAC ──────────────────────────────────────────────────────────────────────

class Menu(Base):
    """
    Represents a sidebar menu item / page in the application.
    e.g. Dashboard, Alerts > Alert Live, Telemetry > Live, etc.
    """
    __tablename__ = "menus"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)          # e.g. "Alert Live"
    slug = Column(String(100), unique=True, nullable=False)  # e.g. "alerts.live"
    parent_slug = Column(String(100), nullable=True)    # e.g. "alerts" for sub-items
    icon = Column(String(50), nullable=True)            # optional icon name
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    role_menus = relationship("RoleMenu", back_populates="menu", cascade="all, delete-orphan")

    @property
    def path(self) -> str:
        if self.slug in MENU_PATH_OVERRIDES:
            return MENU_PATH_OVERRIDES[self.slug]
        return f"/{self.slug.replace('.', '/')}"

    @property
    def href(self) -> str:
        return self.path

    @property
    def roles(self) -> list[int]:
        return [rm.role_id for rm in self.role_menus]


class Role(Base):
    """
    User role — maps to the RDPMS hierarchy:
    Technician → JE → SE → ADRM → DRM → Admin
    """
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)   # e.g. "JE"
    display_name = Column(String(100), nullable=False)       # e.g. "Junior Engineer"
    level = Column(Integer, nullable=False, default=0)       # higher = more access
    description = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(UTC))

    role_menus = relationship("RoleMenu", back_populates="role", cascade="all, delete-orphan")
    users = relationship("User", back_populates="role")

    @property
    def menus(self):
        from sqlalchemy.orm import object_session
        session = object_session(self)
        
        # 1. Fetch all active menus
        if session:
            all_menus = session.query(Menu).filter(Menu.is_active == True).all()
        else:
            all_menus = [rm.menu for rm in self.role_menus if rm.menu and rm.menu.is_active]

        assigned_ids = {rm.menu_id for rm in self.role_menus}

        # 2. Build the full tree
        children_by_parent = {}
        roots = []
        for menu in all_menus:
            if menu.parent_slug:
                children_by_parent.setdefault(menu.parent_slug, []).append(menu)
            else:
                roots.append(menu)

        def sort_key(m):
            return (m.sort_order or 0, m.name)

        def build_node(menu):
            children = sorted(children_by_parent.get(menu.slug, []), key=sort_key)
            return {
                "id": menu.id,
                "label": menu.name,
                "icon": menu.icon,
                "sort_order": menu.sort_order or 0,
                "roles": menu.roles,
                "href": None if children else menu.href,
                "children": [build_node(child) for child in children]
            }

        full_tree = [build_node(m) for m in sorted(roots, key=sort_key)]

        # 3. Filter tree branches based on role assignments
        def filter_node(node):
            filtered_children = []
            for child in node["children"]:
                f_child = filter_node(child)
                if f_child:
                    filtered_children.append(f_child)
            
            if node["id"] in assigned_ids or filtered_children:
                node_copy = dict(node)
                node_copy["children"] = filtered_children
                return node_copy
            return None

        filtered_tree = []
        for root in full_tree:
            f_root = filter_node(root)
            if f_root:
                filtered_tree.append(f_root)

        return filtered_tree


class RoleMenu(Base):
    """
    Many-to-many: which menus a role can access.
    Also stores permission level: view / edit / full.
    """
    __tablename__ = "role_menus"

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False, index=True)
    menu_id = Column(Integer, ForeignKey("menus.id"), nullable=False, index=True)
    permission = Column(String(20), nullable=False, default="view")  # view / edit / full

    role = relationship("Role", back_populates="role_menus")
    menu = relationship("Menu", back_populates="role_menus")

    @property
    def menu_name(self) -> str:
        return self.menu.name if self.menu else ""

    @property
    def menu_slug(self) -> str:
        return self.menu.slug if self.menu else ""

    @property
    def parent_slug(self) -> Optional[str]:
        return self.menu.parent_slug if self.menu else None

    __table_args__ = (
        UniqueConstraint("role_id", "menu_id", name="uq_role_menu"),
    )


class EquipmentRoom(Base):
    """
    Represents an Equipment Room at a station.
    Stores live/latest temperature and humidity values.
    """
    __tablename__ = "equipment_rooms"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    room_type = Column(String(10), nullable=False)  # 'RR', 'IPS', 'BATT'
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    station = relationship("Station")

    __table_args__ = (
        UniqueConstraint("station_id", "room_type", name="uq_station_room_type"),
    )


class MaintenanceMode(Base):
    """
    Represents a Maintenance Mode record for an asset.
    """
    __tablename__ = "maintenance_modes"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    asset_type_hex = Column(String(2), nullable=False, index=True)
    asset_no = Column(String(40), nullable=False, index=True)
    from_time = Column(DateTime, nullable=False, index=True)
    to_time = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now(UTC), nullable=False, index=True)

    station = relationship("Station")
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True, index=True)
    asset = relationship("Asset")


class AssetTypeMaster(Base):
    """
    Represents the Asset Type Master table.
    """
    __tablename__ = "asset_type_master"

    id = Column(Integer, primary_key=True, index=True)
    asset_type_id = Column(String(2), unique=True, nullable=False)
    asset_type_code = Column(String(20), unique=True, nullable=False)
    asset_type_name = Column(String(100), nullable=False)
    is_equipment_room = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AlertCauseMaster(Base):
    """
    Represents the Alert Cause Master table.
    """
    __tablename__ = "alert_cause_master"

    cause_code = Column(String(50), primary_key=True)
    cause_detail = Column(Text, nullable=False)
    asset_type_id = Column(String(2), ForeignKey("asset_type_master.asset_type_id"), nullable=True)
    alert_category = Column(Enum("FAILURE", "PREDICTIVE", name="alert_category_enum"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    asset_type = relationship("AssetTypeMaster")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    smms_asset_code = Column(String(50), unique=True, nullable=False)
    smms_asset_name = Column(String(100), nullable=False)
    asset_number_code = Column(String(50), nullable=False)   # e.g., "PT-101"
    asset_number_id = Column(String(2), nullable=False)      # hex 00-FF (part of para_id)
    asset_type_hex = Column(String(2), ForeignKey("asset_type_master.asset_type_id"), nullable=False)
    station_gateway_id = Column(String(8), ForeignKey("gateways.stngw_id"), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    make = Column(String(80))
    model = Column(String(50))
    attr1 = Column(String(100))   # sub-asset type
    attr2 = Column(String(100))
    location = Column(String(200))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(UTC))
    updated_at = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    # Relationships
    asset_type = relationship("AssetTypeMaster")
    gateway = relationship("Gateway", back_populates="assets")
    station = relationship("Station", back_populates="assets")

    __table_args__ = (
        UniqueConstraint(
            "station_gateway_id", "asset_type_hex", "asset_number_id",
            name="uq_asset_gw_type_number"
        ),
    )

