import re
from pathlib import Path
from pydantic import BaseModel, field_validator

from stfu.hub.registry import _assert_contained

# \w es Unicode-aware: los presets curados usan nombres en español con tildes
# (p.ej. "Reunión", "Música"); '/' y '\' ya se rechazan aparte en validate_name.
_NAME_PATTERN = re.compile(r'^[\w .\-]{1,64}$', re.UNICODE)
_DOT_ONLY_NAMES = frozenset({'.', '..'})


class PresetSpec(BaseModel):
    name: str
    plugins: list[dict] = []

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if v in _DOT_ONLY_NAMES:
            raise ValueError(f"Preset name {v!r} must not be '.' or '..'.")
        if '/' in v or '\\' in v:
            raise ValueError(f"Preset name {v!r} must not contain path separators.")
        if not _NAME_PATTERN.match(v):
            raise ValueError(
                f"Preset name {v!r} is invalid: must be 1-64 word characters, spaces, dots or hyphens."
            )
        return v


class PresetStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[PresetSpec]:
        # read_bytes (no read_text): JSON es UTF-8 por spec, pero read_text
        # usa la codificación default de la plataforma, que en Windows no
        # siempre es UTF-8 y corrompe nombres con tildes (p.ej. "Reunión").
        return [
            PresetSpec.model_validate_json(p.read_bytes())
            for p in self.base_dir.glob("*.json")
        ]

    def get(self, name: str) -> PresetSpec | None:
        _assert_contained(self.base_dir, name)
        p = self.base_dir / f"{name}.json"
        return PresetSpec.model_validate_json(p.read_bytes()) if p.exists() else None

    def save(self, preset: PresetSpec) -> None:
        _assert_contained(self.base_dir, preset.name)
        p = self.base_dir / f"{preset.name}.json"
        p.write_text(preset.model_dump_json(indent=2), encoding="utf-8")

    def delete(self, name: str) -> None:
        _assert_contained(self.base_dir, name)
        p = self.base_dir / f"{name}.json"
        if not p.exists():
            raise ValueError(f"Preset {name!r} does not exist")
        p.unlink()
