# scripts/seed_data_validation.py
"""
Script to validate seed data and ensure all asset types have parameter configs.
Run this during deployment to ensure data integrity.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, settings
from app.models.models import AssetTypeMaster, Asset, AlertCauseMaster
from app.constants import ASSET_TYPE_MAP
import logging
logger = logging.getLogger("seed_validation")

def validate_seed_data():
    """Validate that all required seed data exists"""
    db = SessionLocal()
    
    try:
        errors = []
        warnings = []
        
        # 1. Check asset types
        logger.info("Checking asset types...")
        db_types = db.query(AssetTypeMaster).all()
        db_type_hexes = {t.asset_type_id.upper() for t in db_types}
        
        expected_types = set(ASSET_TYPE_MAP.keys())
        missing_types = expected_types - db_type_hexes
        
        if missing_types:
            errors.append(f"Missing asset types in database: {missing_types}")
        
        # 2. Check parameter configurations
        logger.info("Checking parameter configurations...")
        from app.services.parameter_config_service import param_config_service
        param_para_ids = {p.para_id.upper() for p in param_config_service.config_cache.values()}
        
        expected_params = {
            "0001000C", "0001000D", "0001120A", "0001120B",  # Point Machine
            "DCT00201", "DCT00202", "DCT00203",  # Track Circuit
            "SIG00301", "SIG00302",  # Signal
            "RR000101", "RR000102",  # Relay Room
        }
        
        missing_params = expected_params - param_para_ids
        if missing_params:
            warnings.append(f"Missing parameter configurations: {missing_params}")
        
        # 3. Check for assets without parameter mappings
        logger.info("Checking asset parameter mappings...")
        assets = db.query(Asset).filter(Asset.is_active == True).all()
        
        orphan_assets = []
        for asset in assets:
            if not asset.parameters or len(asset.parameters) == 0:
                orphan_assets.append(asset.asset_number_code)
        
        if orphan_assets:
            warnings.append(f"Assets without parameter mappings: {orphan_assets[:10]}...")
        
        # 4. Check alert causes
        logger.info("Checking alert causes...")
        cause_count = db.query(AlertCauseMaster).count()
        if cause_count == 0:
            errors.append("No alert causes found in database")
        
        # 5. Check vendor code
        logger.info("Checking vendor configuration...")
        if not settings.VENDOR_CODE:
            errors.append("VENDOR_CODE not set in configuration")
        if not settings.VENDOR_NAME:
            errors.append("VENDOR_NAME not set in configuration")
        
        # Summary
        logger.info("=" * 50)
        logger.info("Seed Data Validation Summary")
        logger.info("=" * 50)
        logger.info(f"Asset Types: {len(db_types)} found, {len(expected_types)} expected")
        logger.info(f"Parameter Configs: {len(param_para_ids)} found")
        logger.info(f"Active Assets: {len(assets)}")
        logger.info(f"Alert Causes: {cause_count}")
        
        if errors:
            logger.error("❌ ERRORS:")
            for error in errors:
                logger.error(f"  - {error}")
        
        if warnings:
            logger.warning("⚠️ WARNINGS:")
            for warning in warnings:
                logger.warning(f"  - {warning}")
        
        if not errors and not warnings:
            logger.info("✅ All seed data validated successfully!")
        
        return {"errors": errors, "warnings": warnings}
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return {"errors": [str(e)], "warnings": []}
    finally:
        db.close()

def seed_missing_data():
    """Seed missing data if validation fails"""
    db = SessionLocal()
    
    try:
        # Seed asset types if missing
        from app.constants import ASSET_TYPE_MAP
        for hex_id, (code, name) in ASSET_TYPE_MAP.items():
            existing = db.query(AssetTypeMaster).filter(
                AssetTypeMaster.asset_type_id == hex_id
            ).first()
            if not existing:
                db.add(AssetTypeMaster(
                    asset_type_id=hex_id,
                    asset_type_code=code,
                    asset_type_name=name,
                    is_equipment_room=(hex_id in {"F0", "F1", "F2", "F3", "F4", "F5", "F6"})
                ))
                logger.info(f"Created asset type: {hex_id} - {name}")
        
        db.commit()
        logger.info("Missing data seeded successfully")
        
    except Exception as e:
        logger.error(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Validate
    results = validate_seed_data()
    
    # If errors found, ask user if they want to seed
    if results["errors"]:
        response = input("Errors found. Do you want to seed missing data? (y/n): ")
        if response.lower() == 'y':
            seed_missing_data()
            # Re-validate
            validate_seed_data()
