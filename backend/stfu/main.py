from fastapi import FastAPI, WebSocket
from stfu.api.routes.devices import router as devices_router
from stfu.api.routes.pipeline import router as pipeline_router
from stfu.api.routes.models import router as models_router
from stfu.api.routes.backends import router as backends_router
from stfu.api.ws import metering_ws

_metrics: dict = {"input_db": -60.0, "output_db": -60.0, "latency_ms": 0.0}

app = FastAPI(title="STFU Audio Service", version="0.1.0")
app.include_router(devices_router)
app.include_router(pipeline_router)
app.include_router(models_router)
app.include_router(backends_router)


@app.get("/status")
def status():
    return {"status": "ok", "latency_ms": _metrics["latency_ms"]}


@app.websocket("/ws/metering")
async def ws_metering(websocket: WebSocket):
    await metering_ws(websocket, lambda: _metrics)
