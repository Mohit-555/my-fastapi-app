import asyncio
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any
from app.services.statistics_service import statistics_service
from app.services.redis_service import redis_service
from app.services.smms_client import smms_client
from app.models.models import Station
from app.database import SessionLocal

logger = logging.getLogger("scheduler")

class TaskScheduler:
    """Background task scheduler for periodic operations"""
    
    def __init__(self):
        self.tasks = []
        self.is_running = False
        self.sync_lock = asyncio.Lock()  # Prevent overlapping syncs
    
    def start(self):
        """Start all background tasks in a non-blocking manner"""
        self.is_running = True
        logger.info("Starting task scheduler")
        
        # Daily statistics aggregation
        self.tasks.append(
            asyncio.create_task(self._daily_statistics_task())
        )
        
        # Hourly health check
        self.tasks.append(
            asyncio.create_task(self._hourly_health_check())
        )
        
        # Cleanup old Redis keys
        self.tasks.append(
            asyncio.create_task(self._cleanup_task())
        )
        
        # Asset sync (NEW)
        self.tasks.append(
            asyncio.create_task(self._asset_sync_task())
        )

        # Maintenance-mode reminder alerts (Annexure D §5.7) — must fire
        # automatically, not only when someone calls the endpoint by hand.
        self.tasks.append(
            asyncio.create_task(self._maintenance_reminder_task())
        )
    
    async def stop(self):
        """Stop all background tasks"""
        self.is_running = False
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        logger.info("Task scheduler stopped")
    
    async def _daily_statistics_task(self):
        """Aggregate daily statistics"""
        while self.is_running:
            try:
                # Run at midnight
                now = datetime.now()
                next_run = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                wait_seconds = (next_run - now).total_seconds()
                
                await asyncio.sleep(wait_seconds)
                
                # Process yesterday's data
                yesterday = now - timedelta(days=1)
                await self._aggregate_daily_stats(yesterday.date())
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in daily statistics task: {e}")
                await asyncio.sleep(60)  # Wait before retry
    
    async def _hourly_health_check(self):
        """Check health of all gateways"""
        while self.is_running:
            try:
                await asyncio.sleep(3600)  # Run every hour
                
                # Check all registered gateways
                # (Can get gateways from DB/Cache to check last_seen if needed)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check task: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_task(self):
        """Clean up old Redis keys"""
        while self.is_running:
            try:
                await asyncio.sleep(86400)  # Run daily
                
                # Clean up old alert keys (older than 7 days)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)
    
    async def _aggregate_daily_stats(self, date_val: date):
        """Aggregate statistics for a specific date"""
        logger.info(f"Aggregating daily statistics for {date_val}")

    async def _asset_sync_task(self):
        """Synchronize assets from SMMS daily at 2:00 AM"""
        while self.is_running:
            try:
                # Calculate next run (2:00 AM)
                now = datetime.now()
                next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if now >= next_run:
                    next_run = next_run + timedelta(days=1)
                
                wait_seconds = (next_run - now).total_seconds()
                logger.info(f"Asset sync scheduled in {wait_seconds/3600:.1f} hours")
                
                await asyncio.sleep(wait_seconds)
                
                # Perform sync
                async with self.sync_lock:
                    await self._perform_asset_sync()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in asset sync task: {e}")
                await asyncio.sleep(300)  # Retry after 5 minutes on error
    
    async def _maintenance_reminder_task(self):
        """
        Annexure D §5.7: if a maintainer forgets to clear maintenance mode,
        RDPMS must keep generating a regular alert every standard interval
        (60 min Track Circuit/Point Machine, 45 min Signal) advising staff
        that maintenance mode is still active. Runs the same check every
        60 seconds so no active maintenance window can silently overrun.
        """
        from app.routers.maintenance import check_maintenance_reminders

        while self.is_running:
            try:
                await asyncio.sleep(60)
                db = SessionLocal()
                try:
                    generated = check_maintenance_reminders(db=db)
                    if generated:
                        logger.info(f"Maintenance-mode reminder alerts generated: {len(generated)}")
                finally:
                    db.close()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in maintenance reminder task: {e}")
                await asyncio.sleep(60)

    async def _perform_asset_sync(self):
        """Perform asset synchronization for all active stations"""
        logger.info("Starting scheduled asset sync from SMMS")
        
        db = SessionLocal()
        try:
            # Get all active stations
            stations = db.query(Station).filter(Station.is_active == True).all()
            logger.info(f"Syncing assets for {len(stations)} stations")
            
            results = {
                "success": 0,
                "failed": 0,
                "created_total": 0,
                "updated_total": 0,
                "details": []
            }
            
            for station in stations:
                try:
                    result = await smms_client.sync_assets_for_station(
                        station.station_code, 
                        db
                    )
                    
                    if result.get("status") == "success":
                        results["success"] += 1
                        results["created_total"] += result.get("created", 0)
                        results["updated_total"] += result.get("updated", 0)
                        results["details"].append({
                            "station": station.station_code,
                            "status": "success",
                            "created": result.get("created", 0),
                            "updated": result.get("updated", 0)
                        })
                    else:
                        results["failed"] += 1
                        results["details"].append({
                            "station": station.station_code,
                            "status": "failed",
                            "error": result.get("message", "Unknown error")
                        })
                        
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({
                        "station": station.station_code,
                        "status": "failed",
                        "error": str(e)
                    })
                    logger.error(f"Error syncing station {station.station_code}: {e}")
            
            # Store sync results in Redis for monitoring
            await redis_service.store_sync_results(results)
            
            logger.info(f"Asset sync completed: {results['success']} succeeded, {results['failed']} failed")
            
        except Exception as e:
            logger.error(f"Asset sync task failed: {e}")
        finally:
            db.close()

# Singleton instance
scheduler = TaskScheduler()
