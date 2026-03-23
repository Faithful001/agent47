from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from redis.asyncio import Redis
from src.infra.websocket.manager import WebSocketManager
from src.domain.user.service import UserService
from src.config.database import get_db
from src.config.redis import get_redis
from sqlalchemy.orm import Session
from src.infra.pubsub.manager import PubSubManager

router = APIRouter(prefix="/ws", tags=["websockets"])

ws_manager = WebSocketManager()


@router.websocket("/users/{user_id}")
async def websocket_user(
    websocket: WebSocket,
    user_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    # Optional: validate user exists
    user = UserService(db).get_user(user_id)
    if not user:
        await websocket.close(code=4001)  # custom code
        return

    await ws_manager.connect(websocket, user_id)

    pubsub = PubSubManager(redis)
    
    async def on_message(data: dict):
        await ws_manager.broadcast_to_user(user_id, data)

    channel = f"contract:user:{user_id}"
    await pubsub.subscribe(channel, on_message)

    try:
        while True:
            # Keep connection alive - optional ping/pong
            await websocket.receive_text()  # or just await asyncio.sleep(30)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)
        await pubsub.unsubscribe(channel, on_message)