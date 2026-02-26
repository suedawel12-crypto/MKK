from fastapi import WebSocket, WebSocketDisconnect
from typing import Set, Dict
import asyncio
import json
import logging

from redis_client import redis_client

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self.user_connections: Dict[int, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, room_id: int, user_id: int):
        await websocket.accept()
        
        if room_id not in self.active_connections:
            self.active_connections[room_id] = set()
        
        self.active_connections[room_id].add(websocket)
        self.user_connections[user_id] = websocket
        
        logger.info(f"User {user_id} connected to room {room_id}")
    
    def disconnect(self, websocket: WebSocket, room_id: int, user_id: int):
        if room_id in self.active_connections:
            self.active_connections[room_id].discard(websocket)
        
        if user_id in self.user_connections:
            del self.user_connections[user_id]
    
    async def broadcast_to_room(self, room_id: int, message: dict):
        """Broadcast message to all users in a room"""
        if room_id in self.active_connections:
            disconnected = []
            
            for connection in self.active_connections[room_id]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)
            
            # Clean up disconnected
            for conn in disconnected:
                self.active_connections[room_id].discard(conn)
    
    async def send_to_user(self, user_id: int, message: dict):
        """Send message to specific user"""
        if user_id in self.user_connections:
            try:
                await self.user_connections[user_id].send_json(message)
            except:
                del self.user_connections[user_id]

class WebSocketHandler:
    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self.redis = redis_client
    
    async def handle_connection(self, websocket: WebSocket, room_id: int, user_id: int):
        await self.manager.connect(websocket, room_id, user_id)
        
        # Subscribe to Redis channel for this room
        pubsub = self.redis.client.pubsub()
        await pubsub.subscribe(f"room:{room_id}")
        
        try:
            # Listen for Redis messages
            asyncio.create_task(self._redis_listener(pubsub, room_id))
            
            # Listen for client messages
            while True:
                data = await websocket.receive_json()
                await self._handle_client_message(data, user_id, room_id)
                
        except WebSocketDisconnect:
            self.manager.disconnect(websocket, room_id, user_id)
            await pubsub.unsubscribe(f"room:{room_id}")
    
    async def _redis_listener(self, pubsub, room_id: int):
        """Listen for Redis pub/sub messages and broadcast to room"""
        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    await self.manager.broadcast_to_room(room_id, data)
        except:
            pass
    
    async def _handle_client_message(self, data: dict, user_id: int, room_id: int):
        """Handle messages from client"""
        message_type = data.get('type')
        
        if message_type == 'claim':
            # Handle claim request
            card_id = data.get('card_id')
            # Process claim (will be implemented in main)
            await self.manager.send_to_user(user_id, {
                'type': 'claim_status',
                'status': 'processing'
            })
        
        elif message_type == 'buy_card':
            # Handle card purchase
            round_id = data.get('round_id')
            # Process purchase (will be implemented in main)
            pass

# Initialize managers
manager = ConnectionManager()
ws_handler = WebSocketHandler(manager)