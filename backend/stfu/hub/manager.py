"""Catálogo curado + descarga verificada de modelos.

Los manifests curados viven en el repo; la descarga trae solo el binario del
modelo desde HF o una URL directa y lo registra tras validar sha256."""
import hashlib
import logging
import shutil
import tempfile
from pathlib import Path
import httpx
from stfu.hub.registry import ModelManifest, ModelRegistry

_log = logging.getLogger(__name__)


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

    def download(self, model_id: str) -> Path:
        manifest = next((m for m in self._curated() if m.id == model_id), None)
        if manifest is None:
            raise ValueError(f"modelo {model_id!r} no está en el catálogo")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / manifest.file
            self._fetch(manifest, dest)
            self._verify_sha256(manifest, dest)
            self._registry.register(manifest, dest)
        _log.info("modelo %s instalado", model_id)
        return self._registry.model_path(model_id)

    def _fetch(self, manifest: ModelManifest, dest: Path) -> None:
        if manifest.source == "hf" and manifest.hf_repo:
            from huggingface_hub import hf_hub_download
            local = hf_hub_download(repo_id=manifest.hf_repo, filename=manifest.file)
            shutil.copy2(local, dest)
            return
        if manifest.url:
            with httpx.stream("GET", manifest.url, follow_redirects=True, timeout=60.0) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            return
        raise ValueError(f"manifest {manifest.id!r} sin fuente descargable")

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
