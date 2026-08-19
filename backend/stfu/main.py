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
from stfu.api.ws import metering_ws
from stfu.audio.engine import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    from stfu.audio.degrade_monitor import DegradeMonitor
    from stfu.apo.health_monitor import ApoHealthMonitor
    from stfu.apo.health import check_registrations
    from stfu.api.routes.models import _hub
    monitor = DegradeMonitor(engine, lambda: _hub().catalog())
    monitor.start()
    apo_health_monitor = ApoHealthMonitor(check_registrations)
    apo_health_monitor.start()
    yield
    monitor.stop()
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
        from stfu.apo.health import needs_repair, check_registrations
        payload["apo_health"] = {"needs_repair": needs_repair(), "endpoints": check_registrations()}
    except Exception:
        payload["apo_health"] = {"needs_repair": False, "endpoints": []}
    return payload


@app.get("/status")
def status():
    return _status_payload()


@app.websocket("/ws/metering")
async def ws_metering(websocket: WebSocket):
    await metering_ws(websocket, _status_payload)
