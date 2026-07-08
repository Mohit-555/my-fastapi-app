import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

logger = logging.getLogger("redis_service")

class RedisService:
    def __init__(self):
        self.client = None
        self._in_memory_db = {}
        self.is_fallback = True
        self.connect()
    
    def connect(self):
        """Establish Redis connection, fall back to in-memory dictionary on failure"""
        try:
            import redis
            from app.database import settings
            
            # Since Redis settings might not exist in the default Settings,
            # we safely check if they are defined, otherwise we use defaults.
            host = getattr(settings, "REDIS_HOST", "localhost")
            port = getattr(settings, "REDIS_PORT", 6379)
            db = getattr(settings, "REDIS_DB", 0)
            password = getattr(settings, "REDIS_PASSWORD", None)
            
            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2
            )
            # Test connection
            self.client.ping()
            self.is_fallback = False
            logger.info("Connected to real Redis successfully.")
        except Exception as e:
            self.client = None
            self.is_fallback = True
            logger.warning(f"Could not connect to Redis: {e}. Falling back to in-memory cache.")
    
    def close(self):
        """Close connection if connected to real Redis"""
        if self.client:
            try:
                self.client.close()
                logger.info("Redis connection closed.")
            except Exception:
                pass
    
    # ============ Latest Parameter Values ============
    
    async def store_latest_parameter(
        self, 
        stngw_id: str, 
        para_id: str, 
        value: float, 
        timestamp: str,
        ttl_seconds: int = 3600
    ):
        """Store latest parameter value"""
        stngw_id = stngw_id.upper()
        para_id = para_id.upper()
        key = f"latest:{stngw_id}:{para_id}"
        data = {
            "value": str(value),
            "timestamp": timestamp
        }
        if not self.is_fallback:
            try:
                self.client.hset(key, mapping=data)
                self.client.expire(key, ttl_seconds)
                return
            except Exception as e:
                logger.error(f"Error writing to Redis key {key}: {e}")
        
        self._in_memory_db[key] = {
            "value": float(value),
            "timestamp": timestamp,
            "expiry": datetime.now().timestamp() + ttl_seconds
        }
    
    async def get_latest_parameter(
        self, 
        stngw_id: str, 
        para_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get latest parameter value"""
        stngw_id = stngw_id.upper()
        para_id = para_id.upper()
        key = f"latest:{stngw_id}:{para_id}"
        
        if not self.is_fallback:
            try:
                data = self.client.hgetall(key)
                if data:
                    return {
                        "value": float(data.get("value", 0)),
                        "timestamp": data.get("timestamp")
                    }
                return None
            except Exception as e:
                logger.error(f"Error reading from Redis key {key}: {e}")
        
        record = self._in_memory_db.get(key)
        if record:
            if datetime.now().timestamp() > record.get("expiry", 0):
                del self._in_memory_db[key]
                return None
            return {
                "value": record["value"],
                "timestamp": record["timestamp"]
            }
        return None
    
    async def get_all_latest_parameters(
        self, 
        stngw_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """Get all latest parameters for a gateway"""
        stngw_id = stngw_id.upper()
        prefix = f"latest:{stngw_id}:"
        result = {}
        
        if not self.is_fallback:
            try:
                pattern = f"latest:{stngw_id}:*"
                for key in self.client.scan_iter(pattern):
                    para_id = key.split(":")[-1]
                    data = self.client.hgetall(key)
                    if data:
                        result[para_id] = {
                            "value": float(data.get("value", 0)),
                            "timestamp": data.get("timestamp")
                        }
                return result
            except Exception as e:
                logger.error(f"Error scanning from Redis: {e}")
        
        now = datetime.now().timestamp()
        for key, record in list(self._in_memory_db.items()):
            if key.startswith(prefix):
                if now > record.get("expiry", 0):
                    del self._in_memory_db[key]
                    continue
                para_id = key.split(":")[-1]
                result[para_id] = {
                    "value": record["value"],
                    "timestamp": record["timestamp"]
                }
        return result
    
    # ============ Active Alerts ============
    
    async def store_active_alert(self, alert_key: str, alert_data: Dict[str, Any]):
        """Store active alert in cache"""
        key = f"alert:{alert_key}"
        if not self.is_fallback:
            try:
                self.client.hset(key, mapping=alert_data)
                self.client.expire(key, 86400)  # 24 hours
                return
            except Exception as e:
                logger.error(f"Error storing active alert in Redis: {e}")
        
        self._in_memory_db[key] = {
            "data": alert_data,
            "expiry": datetime.now().timestamp() + 86400
        }
    
    async def get_active_alert(self, alert_key: str) -> Optional[Dict[str, Any]]:
        """Get active alert from cache"""
        key = f"alert:{alert_key}"
        if not self.is_fallback:
            try:
                data = self.client.hgetall(key)
                return data if data else None
            except Exception as e:
                logger.error(f"Error getting active alert from Redis: {e}")
                return None
        
        record = self._in_memory_db.get(key)
        if record:
            if datetime.now().timestamp() > record.get("expiry", 0):
                del self._in_memory_db[key]
                return None
            return record["data"]
        return None
    
    async def remove_active_alert(self, alert_key: str):
        """Remove active alert from cache"""
        key = f"alert:{alert_key}"
        if not self.is_fallback:
            try:
                self.client.delete(key)
                return
            except Exception as e:
                logger.error(f"Error deleting active alert from Redis: {e}")
        
        if key in self._in_memory_db:
            del self._in_memory_db[key]
    
    # ============ Gateway Health ============
    
    async def store_gateway_health(
        self, 
        stngw_id: str, 
        is_healthy: bool, 
        timestamp: str
    ):
        """Store gateway health status"""
        stngw_id = stngw_id.upper()
        key = f"health:gateway:{stngw_id}"
        data = {
            "status": "healthy" if is_healthy else "faulty",
            "timestamp": timestamp
        }
        if not self.is_fallback:
            try:
                self.client.hset(key, mapping=data)
                self.client.expire(key, 3600)
                return
            except Exception as e:
                logger.error(f"Error storing gateway health in Redis: {e}")
        
        self._in_memory_db[key] = {
            "data": data,
            "expiry": datetime.now().timestamp() + 3600
        }
    
    async def store_sensor_health(
        self, 
        stngw_id: str, 
        para_id: str, 
        is_healthy: bool, 
        timestamp: str
    ):
        """Store sensor health status"""
        stngw_id = stngw_id.upper()
        para_id = para_id.upper()
        key = f"health:sensor:{stngw_id}:{para_id}"
        data = {
            "status": "healthy" if is_healthy else "faulty",
            "timestamp": timestamp
        }
        if not self.is_fallback:
            try:
                self.client.hset(key, mapping=data)
                self.client.expire(key, 3600)
                return
            except Exception as e:
                logger.error(f"Error storing sensor health in Redis: {e}")
        
        self._in_memory_db[key] = {
            "data": data,
            "expiry": datetime.now().timestamp() + 3600
        }
    
    # ============ Station Gateway Cache ============
    
    async def register_gateway(
        self, 
        stngw_id: str, 
        vcc: str, 
        vgc: str, 
        version: str
    ):
        """Register gateway in cache"""
        stngw_id = stngw_id.upper()
        key = f"gateway:{stngw_id}"
        data = {
            "vcc": vcc,
            "vgc": vgc,
            "version": version,
            "last_seen": datetime.now().isoformat(),
            "registered": "True"
        }
        if not self.is_fallback:
            try:
                self.client.hset(key, mapping=data)
                self.client.expire(key, 86400)
                return
            except Exception as e:
                logger.error(f"Error registering gateway in Redis: {e}")
        
        self._in_memory_db[key] = {
            "data": data,
            "expiry": datetime.now().timestamp() + 86400
        }
    
    async def get_gateway_info(self, stngw_id: str) -> Optional[Dict[str, Any]]:
        """Get gateway info from cache"""
        stngw_id = stngw_id.upper()
        key = f"gateway:{stngw_id}"
        if not self.is_fallback:
            try:
                data = self.client.hgetall(key)
                return data if data else None
            except Exception as e:
                logger.error(f"Error getting gateway info from Redis: {e}")
                return None
        
        record = self._in_memory_db.get(key)
        if record:
            if datetime.now().timestamp() > record.get("expiry", 0):
                del self._in_memory_db[key]
                return None
            return record["data"]
        return None

    async def get_sensor_health_summary(self, stngw_id: str) -> Dict[str, Any]:
        """Get summary of sensor health for a gateway"""
        stngw_id = stngw_id.upper()
        total = 0
        healthy = 0
        
        if not self.is_fallback:
            try:
                pattern = f"health:sensor:{stngw_id}:*"
                for key in self.client.scan_iter(pattern):
                    total += 1
                    data = self.client.hgetall(key)
                    if data and data.get("status") == "healthy":
                        healthy += 1
                return {
                    "total": total,
                    "healthy": healthy,
                    "faulty": total - healthy
                }
            except Exception as e:
                logger.error(f"Error getting sensor health summary: {e}")
        
        # Fallback to in-memory
        prefix = f"health:sensor:{stngw_id}:"
        now = datetime.now().timestamp()
        for key, record in list(self._in_memory_db.items()):
            if key.startswith(prefix):
                # Check expiry
                if now > record.get("expiry", 0):
                    del self._in_memory_db[key]
                    continue
                total += 1
                data = record.get("data", {})
                if data.get("status") == "healthy":
                    healthy += 1
        
        return {
            "total": total,
            "healthy": healthy,
            "faulty": total - healthy
        }

    async def get_sensor_health(self, stngw_id: str, para_id: str) -> Optional[Dict[str, Any]]:
        """Get health status for a specific sensor"""
        stngw_id = stngw_id.upper()
        para_id = para_id.upper()
        key = f"health:sensor:{stngw_id}:{para_id}"
        
        if not self.is_fallback:
            try:
                data = self.client.hgetall(key)
                return data if data else None
            except Exception as e:
                logger.error(f"Error getting sensor health: {e}")
                return None
        
        record = self._in_memory_db.get(key)
        if record:
            if datetime.now().timestamp() > record.get("expiry", 0):
                del self._in_memory_db[key]
                return None
            return record.get("data")
        return None

    async def get_iot_health_summary(self, stngw_id: str) -> Dict[str, Any]:
        """Get summary of IoT health for a gateway"""
        stngw_id = stngw_id.upper()
        total = 0
        healthy = 0
        
        if not self.is_fallback:
            try:
                pattern = f"health:iot:{stngw_id}:*"
                for key in self.client.scan_iter(pattern):
                    total += 1
                    data = self.client.hgetall(key)
                    if data and data.get("status") == "healthy":
                        healthy += 1
                return {
                    "total": total,
                    "healthy": healthy,
                    "faulty": total - healthy
                }
            except Exception as e:
                logger.error(f"Error getting IoT health summary: {e}")
        
        prefix = f"health:iot:{stngw_id}:"
        now = datetime.now().timestamp()
        for key, record in list(self._in_memory_db.items()):
            if key.startswith(prefix):
                if now > record.get("expiry", 0):
                    del self._in_memory_db[key]
                    continue
                total += 1
                data = record.get("data", {})
                if data.get("status") == "healthy":
                    healthy += 1
        
        return {
            "total": total,
            "healthy": healthy,
            "faulty": total - healthy
        }

    # ============ Asset Sync Results ============
    
    async def store_sync_results(self, results: Dict[str, Any]):
        """Store asset sync results in Redis"""
        key = f"sync:results:{datetime.now().strftime('%Y-%m-%d')}"
        data = {
            "timestamp": datetime.now().isoformat(),
            "success": str(results["success"]),
            "failed": str(results["failed"]),
            "created_total": str(results["created_total"]),
            "updated_total": str(results["updated_total"]),
            "details": json.dumps(results["details"])
        }
        if not self.is_fallback:
            try:
                self.client.hset(key, mapping=data)
                self.client.expire(key, 86400 * 7)  # Keep for 7 days
                logger.info(f"Stored sync results in Redis: {results['success']} success, {results['failed']} failed")
                return
            except Exception as e:
                logger.error(f"Error storing sync results in Redis: {e}")
        
        self._in_memory_db[key] = {
            "data": data,
            "expiry": datetime.now().timestamp() + 86400 * 7
        }
        logger.info(f"Stored sync results in in-memory cache: {results['success']} success, {results['failed']} failed")

    async def get_sync_results(self, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get sync results for a specific date"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        key = f"sync:results:{date}"
        
        if not self.is_fallback:
            try:
                data = self.client.hgetall(key)
                if data:
                    try:
                        data["details"] = json.loads(data.get("details", "[]"))
                    except Exception:
                        data["details"] = []
                    for field in ["success", "failed", "created_total", "updated_total"]:
                        if field in data:
                            try:
                                data[field] = int(data[field])
                            except ValueError:
                                data[field] = 0
                    return data
                return None
            except Exception as e:
                logger.error(f"Error getting sync results from Redis: {e}")
                return None
        
        record = self._in_memory_db.get(key)
        if record:
            if datetime.now().timestamp() > record.get("expiry", 0):
                del self._in_memory_db[key]
                return None
            data = dict(record["data"])
            try:
                data["details"] = json.loads(data.get("details", "[]"))
            except Exception:
                data["details"] = []
            for field in ["success", "failed", "created_total", "updated_total"]:
                if field in data:
                    try:
                        data[field] = int(data[field])
                    except ValueError:
                        data[field] = 0
            return data
        return None

# Singleton instance
redis_service = RedisService()
