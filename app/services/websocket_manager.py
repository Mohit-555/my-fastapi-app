import asyncio
import json
from typing import Dict, Set, Optional, List, Any
from datetime import datetime, timedelta
from fastapi import WebSocket, WebSocketDisconnect
import logging
from dataclasses import dataclass

logger = logging.getLogger("websocket_manager")

@dataclass
class ConnectionMetadata:
    connection_id: str
    station_code: str
    websocket: WebSocket
    connected_at: datetime
    last_ping: datetime
    last_pong: datetime
    subscriptions: Dict[str, Any]
    is_alive: bool = True

class ConnectionManager:
    """
    WebSocket connection manager for real-time updates.
    Supports multiple clients per station and subscription filtering.
    """
    
    def __init__(self):
        # station_code -> set of WebSocket connections
        self.station_connections: Dict[str, Set[WebSocket]] = {}
        # connection_id -> ConnectionMetadata
        self.connection_metadata: Dict[str, ConnectionMetadata] = {}
        self.connection_counter = 0
        self.heartbeat_interval = 30  # seconds
        self.heartbeat_timeout = 60  # seconds
    
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
        
        # Store metadata with heartbeat tracking
        now = datetime.now()
        self.connection_metadata[connection_id] = ConnectionMetadata(
            connection_id=connection_id,
            station_code=station_code,
            websocket=websocket,
            connected_at=now,
            last_ping=now,
            last_pong=now,
            subscriptions=client_info or {}
        )
        
        # Start heartbeat for this connection
        asyncio.create_task(self._heartbeat_loop(connection_id))
        
        logger.info(f"WebSocket connected: {connection_id} for station {station_code}")
        return connection_id
    
    async def _heartbeat_loop(self, connection_id: str):
        """Send periodic pings to keep connection alive"""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                if connection_id not in self.connection_metadata:
                    break
                
                metadata = self.connection_metadata[connection_id]
                
                # Check if connection is stale
                now = datetime.now()
                time_since_pong = (now - metadata.last_pong).total_seconds()
                
                if time_since_pong > self.heartbeat_timeout:
                    logger.warning(f"Connection {connection_id} timed out (no pong for {time_since_pong}s)")
                    await self._close_connection(connection_id)
                    break
                
                # Send ping
                await metadata.websocket.send_text(json.dumps({
                    "type": "ping",
                    "timestamp": now.isoformat()
                }))
                metadata.last_ping = now
                
            except Exception as e:
                logger.error(f"Error in heartbeat loop for {connection_id}: {e}")
                await self._close_connection(connection_id)
                break
    
    async def _close_connection(self, connection_id: str):
        """Close a connection and clean up"""
        if connection_id not in self.connection_metadata:
            return
        
        metadata = self.connection_metadata[connection_id]
        
        # Remove from station connections
        if metadata.station_code in self.station_connections:
            if metadata.websocket in self.station_connections[metadata.station_code]:
                self.station_connections[metadata.station_code].remove(metadata.websocket)
            if not self.station_connections[metadata.station_code]:
                del self.station_connections[metadata.station_code]
        
        # Close websocket
        try:
            await metadata.websocket.close()
        except Exception:
            pass
        
        # Remove metadata
        del self.connection_metadata[connection_id]
        logger.info(f"Closed connection {connection_id}")
        
    def handle_pong(self, connection_id: str):
        """Handle pong response from client"""
        if connection_id in self.connection_metadata:
            self.connection_metadata[connection_id].last_pong = datetime.now()
    
    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket"""
        for conn_id, meta in list(self.connection_metadata.items()):
            if meta.websocket == websocket:
                asyncio.create_task(self._close_connection(conn_id))
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
