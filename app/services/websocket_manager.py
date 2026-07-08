import asyncio
import json
from typing import Dict, Set, Optional, List, Any
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
import logging
logger = logging.getLogger("websocket_manager")

class ConnectionManager:
    """
    WebSocket connection manager for real-time updates.
    Supports multiple clients per station and subscription filtering.
    """
    
    def __init__(self):
        # station_code -> set of WebSocket connections
        self.station_connections: Dict[str, Set[WebSocket]] = {}
        # connection_id -> {station_code, subscriptions}
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        self.connection_counter = 0
    
    async def connect(self, websocket: WebSocket, station_code: str, client_info: Dict[str, Any] = None):
        """Accept a new WebSocket connection and register it"""
        await websocket.accept()
        
        # Generate unique connection ID
        self.connection_counter += 1
        connection_id = f"conn_{self.connection_counter}"
        
        # Store connection
        if station_code not in self.station_connections:
            self.station_connections[station_code] = set()
        self.station_connections[station_code].add(websocket)
        
        # Store metadata
        self.connection_metadata[connection_id] = {
            "station_code": station_code,
            "websocket": websocket,
            "connected_at": datetime.now().isoformat(),
            "subscriptions": client_info or {},
            "last_activity": datetime.now()
        }
        
        logger.info(f"WebSocket connected: {connection_id} for station {station_code}")
        return connection_id
    
    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket"""
        for station_code, connections in self.station_connections.items():
            if websocket in connections:
                connections.remove(websocket)
                # Clean up empty station sets
                if not connections:
                    del self.station_connections[station_code]
                break
        
        # Clean up metadata
        for conn_id, meta in list(self.connection_metadata.items()):
            if meta["websocket"] == websocket:
                del self.connection_metadata[conn_id]
                logger.info(f"WebSocket disconnected: {conn_id}")
                break
    
    async def broadcast_to_station(
        self, 
        station_code: str, 
        message: Dict[str, Any],
        exclude: Optional[WebSocket] = None
    ):
        """Broadcast a message to all clients subscribed to a station"""
        if station_code not in self.station_connections:
            return
        
        message_str = json.dumps(message)
        disconnected = []
        
        for connection in self.station_connections[station_code]:
            if connection == exclude:
                continue
            
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"Error sending to WebSocket: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)
    
    async def send_to_connection(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific connection"""
        try:
            await websocket.send_text(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Error sending to connection: {e}")
            return False
    
    async def broadcast_parameter_update(
        self,
        stngw_id: str,
        station_code: str,
        para_id: str,
        value: float,
        timestamp: str,
        asset_number_code: Optional[str] = None
    ):
        """Broadcast a parameter update to all clients"""
        message = {
            "type": "telemetry_update",
            "data": {
                "stngw_id": stngw_id,
                "station_code": station_code,
                "para_id": para_id,
                "value": value,
                "timestamp": timestamp,
                "asset_number_code": asset_number_code
            }
        }
        await self.broadcast_to_station(station_code, message)
    
    async def broadcast_alert(
        self,
        alert: Dict[str, Any],
        station_code: str
    ):
        """Broadcast a new alert to all clients"""
        message = {
            "type": "new_alert",
            "data": alert
        }
        await self.broadcast_to_station(station_code, message)
    
    async def broadcast_health_update(
        self,
        station_code: str,
        device_type: str,
        device_id: str,
        status: str,
        timestamp: str
    ):
        """Broadcast a health status update"""
        message = {
            "type": "health_update",
            "data": {
                "device_type": device_type,
                "device_id": device_id,
                "status": status,
                "timestamp": timestamp
            }
        }
        await self.broadcast_to_station(station_code, message)
    
    async def broadcast_maintenance_mode(
        self,
        station_code: str,
        asset_number_code: str,
        action: str,  # "activated" or "cleared"
        from_time: Optional[str] = None,
        to_time: Optional[str] = None
    ):
        """Broadcast maintenance mode status change"""
        message = {
            "type": "maintenance_update",
            "data": {
                "asset_number_code": asset_number_code,
                "action": action,
                "from_time": from_time,
                "to_time": to_time
            }
        }
        await self.broadcast_to_station(station_code, message)
    
    def get_connection_count(self) -> int:
        """Get total active connections"""
        return sum(len(conns) for conns in self.station_connections.values())
    
    def get_station_connections(self, station_code: str) -> int:
        """Get connection count for a station"""
        return len(self.station_connections.get(station_code, set()))

# Singleton instance
websocket_manager = ConnectionManager()
