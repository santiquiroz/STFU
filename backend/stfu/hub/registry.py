import shutil
from pathlib import Path
from pydantic import BaseModel


class ModelManifest(BaseModel):
    id: str
    name: str
    version: str
    plugin_class: str
    source: str
    file: str
    preferred_format: dict
    supported_backends: list[str]
    size_mb: float
    algorithmic_latency_ms: float
    tags: list[str] = []


class ModelRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[ModelManifest]:
        return [
            ModelManifest.model_validate_json(p.read_text())
            for p in self.base_dir.glob("*/manifest.json")
        ]

    def get(self, id: str) -> ModelManifest | None:
        p = self.base_dir / id / "manifest.json"
        return ModelManifest.model_validate_json(p.read_text()) if p.exists() else None

    def register(self, manifest: ModelManifest, model_path: Path) -> None:
        model_dir = self.base_dir / manifest.id
        model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model_path, model_dir / manifest.file)
        (model_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))

    def model_path(self, id: str) -> Path | None:
        m = self.get(id)
        return self.base_dir / id / m.file if m else None
