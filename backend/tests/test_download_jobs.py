import hashlib
import json
import time
from pathlib import Path
import pytest
from stfu.hub.download_jobs import DownloadJobRegistry, start_download_job
from stfu.hub.manager import HubManager
from stfu.hub.registry import ModelRegistry


def _curated_dir(tmp_path, model_bytes: bytes) -> Path:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest = {
        "id": "fastenhancer-tiny", "name": "FastEnhancer Tiny", "version": "1.0",
        "plugin_class": "stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        "source": "url", "file": "model.onnx",
        "url": "https://example.com/model.onnx",
        "sha256": hashlib.sha256(model_bytes).hexdigest(),
        "preferred_format": {"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        "size_mb": 0.01, "algorithmic_latency_ms": 16.0,
        "tier": "floor", "license": "MIT",
        "io_spec": {
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced", "states": [],
        },
    }
    (curated / "fastenhancer-tiny.json").write_text(json.dumps(manifest))
    return curated


@pytest.fixture()
def hub_and_bytes(tmp_path):
    model_bytes = b"0123456789" * 10
    registry = ModelRegistry(tmp_path / "models")
    manager = HubManager(registry, _curated_dir(tmp_path, model_bytes))
    return manager, model_bytes


def _fake_fetch_with_progress(model_bytes: bytes):
    def _fetch(manifest, dest, on_progress=None):
        total = len(model_bytes)
        half = total // 2
        if on_progress:
            on_progress(half, total)
            on_progress(total, total)
        dest.write_bytes(model_bytes)
    return _fetch


def _wait_for_status(registry: DownloadJobRegistry, job_id: str, status: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = registry.get(job_id)
        if job and job.status == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} nunca llegó a status {status!r}")


def test_start_download_job_advances_progress_and_registers(hub_and_bytes, monkeypatch):
    manager, model_bytes = hub_and_bytes
    monkeypatch.setattr(manager, "_fetch", _fake_fetch_with_progress(model_bytes))
    registry = DownloadJobRegistry()

    job_id = start_download_job(manager, "fastenhancer-tiny", registry)
    job = _wait_for_status(registry, job_id, "done")

    assert job.status == "done"
    assert manager.catalog()[0]["installed"] is True


def test_start_download_job_reports_error_on_sha_mismatch(hub_and_bytes, monkeypatch):
    manager, _ = hub_and_bytes
    monkeypatch.setattr(
        manager, "_fetch", lambda manifest, dest, on_progress=None: dest.write_bytes(b"tampered bytes")
    )
    registry = DownloadJobRegistry()

    job_id = start_download_job(manager, "fastenhancer-tiny", registry)
    job = _wait_for_status(registry, job_id, "error")

    assert job.status == "error"
    assert job.error is not None
    assert manager.catalog()[0]["installed"] is False


def test_download_job_registry_computes_percentage():
    registry = DownloadJobRegistry()
    job_id = registry.create()

    registry.update_progress(job_id, 50, 200)

    payload = registry.get(job_id).to_payload()
    assert payload["status"] == "downloading"
    assert payload["pct"] == 25.0


def test_download_job_registry_pct_none_when_total_unknown():
    registry = DownloadJobRegistry()
    job_id = registry.create()

    registry.update_progress(job_id, 50, None)

    assert registry.get(job_id).to_payload()["pct"] is None


def test_download_endpoint_starts_job_and_returns_202(hub_and_bytes, monkeypatch):
    import stfu.api.routes.models as models_route
    from fastapi.testclient import TestClient
    from stfu.main import app

    manager, model_bytes = hub_and_bytes
    monkeypatch.setattr(manager, "_fetch", _fake_fetch_with_progress(model_bytes))
    monkeypatch.setattr(models_route, "_hub", lambda: manager)

    client = TestClient(app)
    r = client.post("/models/fastenhancer-tiny/download")

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and body["job_id"]


def test_download_endpoint_404_for_unknown_model(hub_and_bytes, monkeypatch):
    import stfu.api.routes.models as models_route
    from fastapi.testclient import TestClient
    from stfu.main import app

    manager, _ = hub_and_bytes
    monkeypatch.setattr(models_route, "_hub", lambda: manager)

    client = TestClient(app)
    r = client.post("/models/does-not-exist/download")

    assert r.status_code == 404
