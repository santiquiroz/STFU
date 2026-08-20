"""Catálogo curado + descarga verificada de modelos.

Los manifests curados viven en el repo; la descarga trae solo el binario del
modelo desde HF o una URL directa y lo registra tras validar sha256."""
import hashlib
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable
import httpx
from stfu.hub.registry import ModelManifest, ModelRegistry

_log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int | None], None]


class Sha256Mismatch(RuntimeError):
    pass


class HubManager:
    def __init__(self, registry: ModelRegistry, curated_dir: Path) -> None:
        self._registry = registry
        self._curated_dir = Path(curated_dir)

    def _curated(self) -> list[ModelManifest]:
        return [
            ModelManifest.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self._curated_dir.glob("*.json"))
        ]

    def is_curated(self, model_id: str) -> bool:
        return any(m.id == model_id for m in self._curated())

    def catalog(self) -> list[dict]:
        installed_ids = {m.id for m in self._registry.list()}
        result = []
        seen = set()
        for m in self._curated():
            seen.add(m.id)
            result.append({**m.model_dump(), "installed": m.id in installed_ids})
        for m in self._registry.list():
            if m.id not in seen:
                result.append({**m.model_dump(), "installed": True})
        return result

    def download(self, model_id: str, on_progress: ProgressCallback | None = None) -> Path:
        manifest = next((m for m in self._curated() if m.id == model_id), None)
        if manifest is None:
            raise ValueError(f"modelo {model_id!r} no está en el catálogo")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / manifest.file
            self._fetch(manifest, dest, on_progress)
            self._verify_sha256(manifest, dest)
            self._registry.register(manifest, dest)
        _log.info("modelo %s instalado", model_id)
        return self._registry.model_path(model_id)

    def _fetch(self, manifest: ModelManifest, dest: Path, on_progress: ProgressCallback | None = None) -> None:
        if manifest.source == "hf" and manifest.hf_repo:
            self._fetch_from_hf(manifest, dest, on_progress)
            return
        if manifest.url:
            self._fetch_from_url(manifest, dest, on_progress)
            return
        raise ValueError(f"manifest {manifest.id!r} sin fuente descargable")

    def _fetch_from_hf(self, manifest: ModelManifest, dest: Path, on_progress: ProgressCallback | None) -> None:
        from huggingface_hub import hf_hub_download
        # hf_hub_download no expone un callback de progreso incremental estable
        # entre versiones; se reporta indeterminado (total=None) y luego el
        # salto a completo, en vez de reimplementar su lógica de streaming.
        if on_progress:
            on_progress(0, None)
        local = hf_hub_download(repo_id=manifest.hf_repo, filename=manifest.file)
        shutil.copy2(local, dest)
        if on_progress:
            size = dest.stat().st_size
            on_progress(size, size)

    def _fetch_from_url(self, manifest: ModelManifest, dest: Path, on_progress: ProgressCallback | None) -> None:
        with httpx.stream("GET", manifest.url, follow_redirects=True, timeout=60.0) as r:
            r.raise_for_status()
            total = self._content_length(r.headers)
            downloaded = 0
            with dest.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)

    @staticmethod
    def _content_length(headers: httpx.Headers) -> int | None:
        value = headers.get("content-length")
        return int(value) if value is not None else None

    def _verify_sha256(self, manifest: ModelManifest, path: Path) -> None:
        if not manifest.sha256:
            raise ValueError(f"manifest {manifest.id!r} sin sha256 — no se instala sin verificación")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != manifest.sha256:
            raise Sha256Mismatch(
                f"{manifest.id}: sha256 esperado {manifest.sha256[:12]}…, obtenido {digest[:12]}…"
            )

    def delete(self, model_id: str, active_ids: set[str]) -> None:
        if model_id in active_ids:
            raise ValueError(f"modelo {model_id!r} está activo — desactivar antes de borrar")
        self._registry.delete(model_id)
