import re
import shutil
from pathlib import Path
from pydantic import BaseModel, field_validator

_ID_PATTERN = re.compile(r'^[A-Za-z0-9_.\-]{1,64}$')
_DANGEROUS_TOKENS = frozenset({
    '__builtins__', 'builtins', 'os', 'subprocess', 'sys', 'importlib', 'eval', 'exec',
})


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

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _ID_PATTERN.match(v):
            raise ValueError(
                f"Model id {v!r} is invalid: must match [A-Za-z0-9_.-]{{1,64}} "
                "and must not contain path separators or '..'."
            )
        return v

    @field_validator('file')
    @classmethod
    def validate_file(cls, v: str) -> str:
        if not v or v in ('.', '..'):
            raise ValueError(f"Model file {v!r} is invalid: must be a non-empty bare filename.")
        if '/' in v or '\\' in v:
            raise ValueError(
                f"Model file {v!r} is invalid: must be a bare filename with no path separators."
            )
        if '..' in v:
            raise ValueError(
                f"Model file {v!r} is invalid: must not contain '..'."
            )
        return v

    @field_validator('plugin_class')
    @classmethod
    def validate_plugin_class(cls, v: str) -> str:
        if v.startswith('stfu.plugins.'):
            return v
        parts = set(re.split(r'[.\s]', v))
        dangerous = parts & _DANGEROUS_TOKENS
        if dangerous:
            raise ValueError(
                f"plugin_class {v!r} contains dangerous token(s): {dangerous}. "
                "External plugin classes must not reference dangerous namespaces."
            )
        return v


def _assert_contained(base_dir: Path, id: str) -> None:
    resolved = (base_dir / id).resolve()
    if not resolved.is_relative_to(base_dir.resolve()):
        raise ValueError(f"Model id {id!r} escapes base directory")


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
        _assert_contained(self.base_dir, id)
        p = self.base_dir / id / "manifest.json"
        return ModelManifest.model_validate_json(p.read_text()) if p.exists() else None

    def register(self, manifest: ModelManifest, model_path: Path) -> None:
        _assert_contained(self.base_dir, manifest.id)
        model_dir = self.base_dir / manifest.id
        model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model_path, model_dir / manifest.file)
        (model_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))

    def model_path(self, id: str) -> Path | None:
        _assert_contained(self.base_dir, id)
        m = self.get(id)
        return self.base_dir / id / m.file if m else None
