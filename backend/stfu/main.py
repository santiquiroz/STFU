from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from stfu.core.logging import setup_logging

setup_logging()
from stfu.api.routes.devices import router as devices_router
from stfu.api.routes.pipeline import router as pipeline_router
from stfu.api.routes.models import router as models_router
from stfu.api.routes.backends import router as backends_router
from stfu.api.routes.apo import router as apo_router
from stfu.api.routes.feeder import router as feeder_router
from stfu.api.routes.plugins import router as plugins_router
from stfu.api.routes.presets import router as presets_router
from stfu.api.ws import metering_ws
from stfu.audio.engine import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    from stfu.audio.degrade_monitor import DegradeMonitor
    from stfu.audio.device_watcher import watcher as default_device_watcher
    from stfu.apo.health_monitor import apo_health_monitor
    from stfu.api.routes.models import _hub
    monitor = DegradeMonitor(engine, lambda: _hub().catalog())
    monitor.start()
    default_device_watcher.start()
    apo_health_monitor.start()
    yield
    monitor.stop()
    default_device_watcher.stop()
    apo_health_monitor.stop()
    engine.stop_all()
    from stfu.apo.apo_engine import apo_engine
    apo_engine.stop_all()


app = FastAPI(title="STFU Audio Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "tauri://localhost",
        # Tauri 2 en Windows sirve http://tauri.localhost por defecto (useHttpsScheme=false)
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(devices_router)
app.include_router(pipeline_router)
app.include_router(models_router)
app.include_router(backends_router)
app.include_router(apo_router)
app.include_router(feeder_router)
app.include_router(plugins_router)
app.include_router(presets_router)


def _status_payload() -> dict:
    from stfu.apo.apo_engine import apo_engine
    payload = {
        "status": "ok",
        "latency_ms": engine.get_latency_ms(),
        "active": engine.active_targets(),
        "streams": engine.get_stats(),
        "apo": apo_engine.status(),
    }
    try:
        from stfu.apo.health_monitor import apo_health_monitor
        snapshot = apo_health_monitor.get_snapshot()
        payload["apo_health"] = {"needs_repair": snapshot.needs_repair, "endpoints": snapshot.endpoints}
    except Exception:
        payload["apo_health"] = {"needs_repair": False, "endpoints": []}
    return payload


@app.get("/status")
def status():
    return _status_payload()


@app.websocket("/ws/metering")
async def ws_metering(websocket: WebSocket):
    await metering_ws(websocket, _status_payload)
