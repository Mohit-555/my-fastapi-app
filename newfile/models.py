from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)
    zone_name = Column(String, nullable=False)
    zone_code = Column(String(10), unique=True, nullable=False)
    zone_id_hex = Column(String(2), unique=True, nullable=False)

    divisions = relationship("Division", back_populates="zone", cascade="all, delete-orphan")


class Division(Base):
    __tablename__ = "divisions"

    id = Column(Integer, primary_key=True, index=True)
    division_name = Column(String, nullable=False)
    division_code = Column(String(10), nullable=False)
    division_id_hex = Column(String(2), nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)

    zone = relationship("Zone", back_populates="divisions")
    stations = relationship("Station", back_populates="division", cascade="all, delete-orphan")


class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    station_name = Column(String, nullable=False)
    station_code = Column(String(10), nullable=False)
    station_id_hex = Column(String(2), nullable=False)
    division_id = Column(Integer, ForeignKey("divisions.id"), nullable=False)

    division = relationship("Division", back_populates="stations")
    gateways = relationship("Gateway", back_populates="station", cascade="all, delete-orphan")


class Gateway(Base):
    __tablename__ = "gateways"

    id = Column(Integer, primary_key=True, index=True)
    stngw_id = Column(String(8), unique=True, nullable=False, index=True)
    imei = Column(String(20), nullable=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    station = relationship("Station", back_populates="gateways")
    telemetry = relationship("Telemetry", back_populates="gateway", cascade="all, delete-orphan")


class Telemetry(Base):
    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True, index=True)
    gateway_id = Column(Integer, ForeignKey("gateways.id"), nullable=False)
    para_id = Column(String(8), nullable=False, index=True)
    prv = Column(Float, nullable=True)
    prt = Column(String(30), nullable=True)
    raw_payload = Column(Text, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow)

    gateway = relationship("Gateway", back_populates="telemetry")


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

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    station = relationship("Station")

    __table_args__ = (
        UniqueConstraint(
            "asset_type_hex", "parameter_type_hex", "station_id",
            name="uq_threshold_asset_param_station"
        ),
    )
