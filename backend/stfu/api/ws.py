import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect

_TERMINAL_DOWNLOAD_STATUSES = {"done", "error"}


async def metering_ws(websocket: WebSocket, get_metrics) -> None:
    await websocket.accept()
    try:
        while True:
            payload = await asyncio.to_thread(get_metrics)
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass


async def download_progress_ws(websocket: WebSocket, get_job_payload) -> None:
    """Transmite el progreso de un job de descarga hasta done/error y cierra.

    A diferencia de metering_ws (streaming indefinido hasta que el cliente
    corta), este WS tiene vida finita: el job siempre converge a done o
    error, así que el servidor cierra la conexión apenas llega ese estado."""
    await websocket.accept()
    try:
        while True:
            payload = await asyncio.to_thread(get_job_payload)
            await websocket.send_text(json.dumps(payload))
            if payload["status"] in _TERMINAL_DOWNLOAD_STATUSES:
                break
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return
    await websocket.close()
