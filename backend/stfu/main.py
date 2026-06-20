from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from stfu.api.routes.devices import router as devices_router
from stfu.api.routes.pipeline import router as pipeline_router
from stfu.api.routes.models import router as models_router
from stfu.api.routes.backends import router as backends_router
from stfu.api.ws import metering_ws
from stfu.audio.engine import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.stop_all()


app = FastAPI(title="STFU Audio Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost", "https://tauri.localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(devices_router)
app.include_router(pipeline_router)
app.include_router(models_router)
app.include_router(backends_router)


@app.get("/status")
def status():
    return {
        "status": "ok",
        "latency_ms": engine.get_latency_ms(),
        "active": engine.active_targets(),
    }


@app.websocket("/ws/metering")
async def ws_metering(websocket: WebSocket):
    await metering_ws(websocket, lambda: {
        "latency_ms": engine.get_latency_ms(),
        "active": engine.active_targets(),
    })
