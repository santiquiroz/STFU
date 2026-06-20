import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect


async def metering_ws(websocket: WebSocket, get_metrics) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps(get_metrics()))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
