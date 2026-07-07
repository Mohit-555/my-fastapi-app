import asyncio
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any
from app.services.statistics_service import statistics_service
from app.services.redis_service import redis_service

logger = logging.getLogger("scheduler")

class TaskScheduler:
    """Background task scheduler for periodic operations"""
    
    def __init__(self):
        self.tasks = []
        self.is_running = False
    
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

# Singleton instance
scheduler = TaskScheduler()
