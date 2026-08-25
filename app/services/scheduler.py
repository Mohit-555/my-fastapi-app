import asyncio
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any
from app.services.statistics_service import statistics_service
from app.services.redis_service import redis_service
from app.services.smms_client import smms_client
from app.models.models import Station, AlertEvent
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

        # Escalation SLA timers (Annexure D §13) — auto-push alerts through
        # the ESM→JE→SSE→ASTE/DSTE chain with configurable delays.
        self.tasks.append(
            asyncio.create_task(self._escalation_task())
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
                
                # Compute the date AFTER the sleep — capturing `now` before
                # sleeping aggregates the wrong day (off-by-one).
                yesterday = datetime.now().date() - timedelta(days=1)
                await self._aggregate_daily_stats(yesterday)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in daily statistics task: {e}")
                await asyncio.sleep(60)  # Wait before retry
    
    async def _hourly_health_check(self):
        """Summarize gateway/sensor/IoT health from cached snapshots."""
        from app.models.models import Gateway
        while self.is_running:
            try:
                await asyncio.sleep(3600)  # Run every hour

                db = SessionLocal()
                try:
                    gateways = db.query(Gateway).all()
                    faulty = []
                    for gw in gateways:
                        try:
                            sensors = await redis_service.get_sensor_health_summary(gw.stngw_id) or {}
                            iot = await redis_service.get_iot_health_summary(gw.stngw_id) or {}
                            if (sensors or {}).get("faulty", 0) or (iot or {}).get("faulty", 0):
                                faulty.append(gw.stngw_id)
                        except Exception:
                            logger.debug(f"No health snapshot for gateway {gw.stngw_id}")
                    if faulty:
                        logger.warning(f"Hourly health check: {len(faulty)} gateway(s) with faulty components: {faulty}")
                    else:
                        logger.info(f"Hourly health check: all {len(gateways)} gateway(s) healthy")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check task: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_task(self):
        """Daily housekeeping — evict expired entries from the in-memory
        fallback cache (real Redis expires keys by itself)."""
        while self.is_running:
            try:
                await asyncio.sleep(86400)  # Run daily
                await redis_service.purge_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)
    
    async def _aggregate_daily_stats(self, date_val: date):
        """Aggregate statistics for a specific date.

        Counts alerts raised on `date_val` grouped by type/status and stores
        the summary in Redis under daily_stats:<date> (7-day retention) so
        dashboards can show day-over-day history without re-querying.
        """
        from app.models.models import AlertEvent
        from sqlalchemy import func
        import json

        logger.info(f"Aggregating daily statistics for {date_val}")
        db = SessionLocal()
        try:
            start = datetime(date_val.year, date_val.month, date_val.day)
            end = start + timedelta(days=1)
            rows = (
                db.query(
                    AlertEvent.alert_type,
                    AlertEvent.alert_status,
                    func.count(AlertEvent.id),
                )
                .filter(AlertEvent.alert_time >= start, AlertEvent.alert_time < end)
                .group_by(AlertEvent.alert_type, AlertEvent.alert_status)
                .all()
            )
            summary = {
                f"{alert_type}:{status}": count
                for alert_type, status, count in rows
            }
            total = sum(summary.values())
            logger.info(f"Daily stats for {date_val}: {total} alert(s) — {summary}")

            key = f"daily_stats:{date_val.isoformat()}"
            payload = json.dumps(summary)
            try:
                if redis_service.is_fallback:
                    redis_service._in_memory_db[key] = {
                        "value": summary,
                        "timestamp": datetime.now(),
                        "expiry": datetime.now().timestamp() + 7 * 86400,
                    }
                else:
                    redis_service.client.setex(key, 7 * 86400, payload)
            except Exception as e:
                logger.debug(f"Could not persist daily stats to Redis: {e}")
        finally:
            db.close()

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

    async def _escalation_task(self):
        """
        Annexure D §13 — Escalation chain SLA timers.

        Chain: ESM → JE/SE → SSE → ASTE/DSTE. Every 60s, active alerts that
        have sat at their current escalation level longer than the configured
        delay are pushed to the next level. Position is tracked on the
        AlertEvent row (escalation_level / escalated_at) so the chain
        survives restarts and is visible to the API.

        Delays are read from env (ESCALATION_DELAY_<LEVEL>_MIN) with spec
        defaults of 2/3/6 minutes.
        """
        import os

        delays = {
            "ESM": int(os.getenv("ESCALATION_DELAY_ESM_MIN", "2")),
            "JE": int(os.getenv("ESCALATION_DELAY_JE_MIN", "3")),
            "SSE": int(os.getenv("ESCALATION_DELAY_SSE_MIN", "6")),
        }
        next_level = {"ESM": "JE", "JE": "SSE", "SSE": "ASTE/DSTE"}

        while self.is_running:
            try:
                await asyncio.sleep(60)

                db = SessionLocal()
                try:
                    now = datetime.now()
                    escalated = 0

                    for level, delay_min in delays.items():
                        cutoff = now - timedelta(minutes=delay_min)
                        stale = (
                            db.query(AlertEvent)
                            .filter(
                                AlertEvent.alert_status == "Active",
                                AlertEvent.acknowledged == False,  # noqa: E712
                                AlertEvent.feedback.notin_(["F"]),  # false feedback stops escalation
                                (
                                    (AlertEvent.escalation_level == level)
                                    | (AlertEvent.escalation_level.is_(None) & (level == "ESM"))
                                ),
                                AlertEvent.alert_time <= cutoff,
                            )
                            .all()
                        )
                        for alert in stale:
                            # Respect a previous manual/auto escalation time if set
                            last_change = alert.escalated_at or alert.alert_time
                            if last_change and last_change > cutoff:
                                continue
                            target = next_level[level]
                            if alert.escalation_level == "ASTE/DSTE":
                                continue  # terminal
                            alert.escalation_level = target
                            alert.escalated_at = now
                            note = f"Auto-escalated to {target} after {delay_min} min at level {level}"
                            alert.remark = f"{alert.remark} | {note}" if alert.remark else note
                            escalated += 1

                    if escalated:
                        db.commit()
                        logger.info(f"Escalated {escalated} alert(s) up the ESM→JE→SSE→ASTE chain")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in escalation task: {e}")
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
