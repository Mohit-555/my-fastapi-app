# app/services/smms_client.py
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.database import settings
from app.models.models import Asset, Station, Division, Zone, AssetParameter, ParameterConfig, Gateway
from app.utils.logger import logger

class SMMSClient:
    """
    Client for interacting with SMMS (Signalling Maintenance Management System).
    Handles asset data fetching and telemetry data sharing.
    """
    
    def __init__(self):
        self.base_url = settings.SMMS_BASE_URL
        self.api_key = settings.SMMS_API_KEY
        self.timeout = 30.0
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError))
    )
    async def fetch_assets(
        self,
        zone_code: str,
        division_code: str,
        station_code: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch asset list from SMMS for a specific station.
        
        API: /get_asset_list/{zc}/{dc}/{sc}
        
        Returns:
            List of assets with SMMS codes and metadata
        """
        url = f"{self.base_url}/get_asset_list/{zone_code}/{division_code}/{station_code}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                headers={"X-API-Key": self.api_key}
            )
            response.raise_for_status()
            
            data = response.json()
            assets = data.get("assets", [])
            
            logger.info(f"Fetched {len(assets)} assets from SMMS for {station_code}")
            return assets
    
    async def fetch_asset_telemetry(
        self,
        zone_code: str,
        division_code: str,
        station_code: str,
        smms_asset_code: Optional[str] = None,
        para_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fetch telemetry data for assets from RDPMS.
        This is called by SMMS to get live data.
        """
        # Build URL
        url = f"{self.base_url}/get_asset_telemetry/{zone_code}/{division_code}/{station_code}"
        if smms_asset_code:
            url += f"/{smms_asset_code}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                headers={"X-API-Key": self.api_key},
                params={"para_ids": para_ids} if para_ids else None
            )
            response.raise_for_status()
            return response.json()
    
    async def sync_assets_for_station(
        self,
        station_code: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Synchronize assets from SMMS for a specific station.
        """
        # Get station details
        station = db.query(Station).filter(Station.station_code == station_code).first()
        if not station:
            return {"status": "error", "message": f"Station {station_code} not found"}
        
        # Get zone and division codes
        division = db.query(Division).filter(Division.id == station.division_id).first()
        if not division:
            return {"status": "error", "message": f"Division for station {station_code} not found"}
        
        zone = db.query(Zone).filter(Zone.id == division.zone_id).first()
        if not zone:
            return {"status": "error", "message": f"Zone for station {station_code} not found"}
        
        # Fetch assets from SMMS
        try:
            smms_assets = await self.fetch_assets(
                zone_code=zone.zone_code,
                division_code=division.division_code,
                station_code=station.station_code
            )
        except Exception as e:
            logger.error(f"Error fetching assets from SMMS: {e}")
            return {"status": "error", "message": str(e)}
        
        # Process and store assets
        created_count = 0
        updated_count = 0
        
        for smms_asset in smms_assets:
            # Map SMMS asset to RDPMS asset model
            asset_data = self._map_smms_asset_to_rdpms(smms_asset, station.id, db)
            
            if asset_data:
                # Check if asset exists
                existing = db.query(Asset).filter(
                    Asset.smms_asset_code == asset_data["smms_asset_code"],
                    Asset.station_id == station.id
                ).first()
                
                if existing:
                    # Update existing asset (avoiding parameters field update directly)
                    for key, value in asset_data.items():
                        if key != "parameters":
                            setattr(existing, key, value)
                    existing.last_sync = datetime.utcnow()
                    updated_count += 1
                else:
                    # Create new asset
                    new_asset = Asset(**asset_data)
                    new_asset.last_sync = datetime.utcnow()
                    db.add(new_asset)
                    created_count += 1
        
        db.commit()
        
        return {
            "status": "success",
            "station_code": station_code,
            "created": created_count,
            "updated": updated_count,
            "total": len(smms_assets)
        }
    
    def _map_smms_asset_to_rdpms(
        self,
        smms_asset: Dict[str, Any],
        station_id: int,
        db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Map SMMS asset to RDPMS asset model.
        """
        try:
            # Extract SMMS fields
            smms_asset_code = smms_asset.get("smms_asset_code")
            smms_asset_name = smms_asset.get("smms_asset_name", "")
            
            # Get asset type from SMMS
            asset_type_code = smms_asset.get("asset_type_code", "").upper()
            asset_type_hex = self._get_asset_type_hex(asset_type_code)
            
            if not asset_type_hex:
                logger.warning(f"Unknown asset type: {asset_type_code}")
                return None
            
            # Get or create asset number
            asset_number_code = smms_asset.get("asset_number_code", smms_asset_name)
            asset_number_id = self._generate_asset_number_id(asset_type_hex, db)
            
            # Resolve or create station gateway
            gateway = db.query(Gateway).filter(Gateway.station_id == station_id).first()
            if not gateway:
                station = db.query(Station).filter(Station.id == station_id).first()
                stngw_id = f"GW{station.station_code[:6]}" if station else f"GW{station_id:06d}"
                stngw_id = stngw_id[:8].upper()
                
                gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
                if not gateway:
                    gateway = Gateway(stngw_id=stngw_id, station_id=station_id)
                    db.add(gateway)
                    db.flush()
            
            return {
                "smms_asset_code": smms_asset_code,
                "smms_asset_name": smms_asset_name,
                "asset_number_id": asset_number_id,
                "asset_number_code": asset_number_code,
                "asset_type_hex": asset_type_hex,
                "station_gateway_id": gateway.stngw_id,
                "station_id": station_id,
                "make": smms_asset.get("make"),
                "model": smms_asset.get("model"),
                "is_active": True,
                "vendor_code": settings.VENDOR_CODE,
                "parameters": []
            }
            
        except Exception as e:
            logger.error(f"Error mapping SMMS asset: {e}")
            return None
    
    def _get_asset_type_hex(self, asset_type_code: str) -> Optional[str]:
        """
        Map SMMS asset type code to RDPMS asset type hex.
        Based on Annexure A asset_type_id mapping.
        """
        # Mapping from SMMS codes to RDPMS hex (from Annexure A)
        mapping = {
            # Point Machine
            "EOP": "00",
            "EOPMIU": "00",
            
            # Main Signal
            "LED": "10",
            "LEDM": "10",
            
            # Shunt Signal
            "LES": "11",
            
            # Calling On Signal
            "LEC": "12",
            
            # Route Signal
            "LER": "13",
            
            # DC Track Circuit
            "DCT": "20",
            
            # Axle Counters (Single Section)
            "SSE": "21",  # Eldyne
            "SSC": "22",  # CEL
            "SSG": "23",  # G.G. Tronics
            
            # Axle Counters (Multi Section)
            "MSE": "24",  # Eldyne
            "MSC": "25",  # CEL
            "MSS": "26",  # Siemens
            "ACM": "27",  # Siemens ACM200
            "MSF": "28",  # Frauscher
            "MSM": "29",  # Medha
            "MSG": "2A",  # G.G. Tronics
            "MSA": "2B",  # Sigma Altpro
            
            # High Availability Axle Counter
            "HAG": "2C",  # G.G. Tronics
            
            # Audio Frequency Track Circuit
            "AFA": "2D",  # Ansaldo/Alstom
            "AFS": "2E",  # Siemens
            "AFB": "2F",  # Bombardier
            
            # Block Proving
            "BUA": "30",  # with UAC
            "BUF": "31",  # with UFSBI
            
            # Block Instruments
            "SGE": "32",  # SGE Double Line
            "DDT": "33",  # DIODO Type
            "PBT": "34",  # Push Button
            "NLT": "35",  # Push Button - Neal's Token
            
            # Level Crossing
            "MLC": "40",  # Mechanical
            "ELC": "41",  # Electrical
            
            # IPS
            "IPS": "50",
            
            # SPD
            "SPD": "51",
            
            # Earth Leakage Detector
            "ELD": "60",
            
            # Equipment Rooms (special hex codes)
            "RR": "F0",   # Relay Room
            "IPS_R": "F1", # IPS Room
            "BATT": "F2", # Battery Room
            "MAIN": "F3", # Maintainer Room
            "GEN": "F4",  # Generator Room
            "OUT": "F5",  # Outdoor
            "LOC": "F6",  # Location Box
        }
        
        # Try exact match
        if asset_type_code.upper() in mapping:
            return mapping[asset_type_code.upper()]
        
        # Try partial match
        for code, hex_val in mapping.items():
            if asset_type_code.upper().startswith(code):
                return hex_val
        
        return None
    
    def _generate_asset_number_id(self, asset_type_hex: str, db: Session) -> str:
        """
        Generate asset number ID (one byte hex) for a new asset.
        """
        # Get max asset number ID for this asset type
        max_id = db.query(Asset.asset_number_id).filter(
            Asset.asset_type_hex == asset_type_hex
        ).order_by(Asset.asset_number_id.desc()).first()
        
        if max_id and max_id[0]:
            try:
                next_id = int(max_id[0], 16) + 1
                return f"{next_id:02X}"
            except:
                pass
        
        return "00"

# Singleton instance
smms_client = SMMSClient()
