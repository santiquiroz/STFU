# v1.6 Fase B — Scene presets: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Scene presets — cadenas de plugins con nombre (Gaming/Reunión/Streaming/Podcast/Música/Accesibilidad) que el usuario carga con un click. Un preset es exactamente la lista `[{plugin_id, parameters}]` que `build_pipeline`/`feeder_start` ya consumen — sin schema nuevo.

**Architecture:** `PresetStore` espeja `ModelRegistry` (`~/.stfu/presets/<name>.json`), reusando la validación de containment `_assert_contained` (con el fix de path-traversal de F2). Seeds curados en el repo (`backend/stfu/presets/curated/*.json`) se exponen en el catálogo junto a los guardados por el usuario. Rutas `/presets` CRUD. El backend ya corre cadenas arbitrarias (FeederConfig.plugins), así que aplicar un preset = POST /feeder/start con sus plugins — sin cambios en la ruta audio.

**Tech Stack:** Python 3.11+, pydantic, FastAPI, pytest. Sin deps nuevas.

**Spec:** `docs/superpowers/specs/2026-08-19-v16-voice-studio-design.md` (Fase B)

## Global Constraints

- Base: master post Fase A (merge `8c9cd2f`). El driver v2 no se toca. Backend-only.
- Tests desde `backend/`: `.\.venv\Scripts\python.exe -m pytest`. Suite base 293 verde.
- Nombres de preset vienen del usuario → validación de containment obligatoria (reusar `_assert_contained` de `hub/registry.py` o replicar su lógica exacta: rechaza `..`, `.`, identity, escapes). Charset seguro `[A-Za-z0-9 _.\-]{1,64}`.
- Un preset persistido = `{"name": str, "plugins": [{"plugin_id": str, "parameters": {}}]}`. La forma de `plugins` es la que `build_pipeline` consume.
- Commits en español, convencional, sin `Co-Authored-By`.

---

### Task 1: `PresetStore`

**Files:**
- Create: `backend/stfu/presets/__init__.py` (vacío)
- Create: `backend/stfu/presets/store.py`
- Test: `backend/tests/test_preset_store.py`

**Interfaces:**
```python
class PresetSpec(BaseModel):
    name: str          # validado: charset seguro, no vacío, no path
    plugins: list[dict]  # [{"plugin_id": str, "parameters": dict}]

class PresetStore:
    def __init__(self, base_dir: Path) -> None
    def list(self) -> list[PresetSpec]        # los guardados en base_dir
    def get(self, name: str) -> PresetSpec | None   # containment-checked
    def save(self, preset: PresetSpec) -> None       # containment-checked
    def delete(self, name: str) -> None              # containment-checked, ValueError si no existe
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_preset_store.py
import pytest
from stfu.presets.store import PresetStore, PresetSpec


def _store(tmp_path):
    return PresetStore(tmp_path / "presets")


def test_save_and_get_roundtrip(tmp_path):
    s = _store(tmp_path)
    p = PresetSpec(name="mi-voz", plugins=[{"plugin_id": "gain", "parameters": {"gain_db": 3.0}}])
    s.save(p)
    got = s.get("mi-voz")
    assert got is not None
    assert got.plugins == p.plugins


def test_list_returns_saved(tmp_path):
    s = _store(tmp_path)
    s.save(PresetSpec(name="a", plugins=[]))
    s.save(PresetSpec(name="b", plugins=[]))
    names = {p.name for p in s.list()}
    assert names == {"a", "b"}


def test_get_missing_returns_none(tmp_path):
    assert _store(tmp_path).get("nope") is None


def test_delete_removes(tmp_path):
    s = _store(tmp_path)
    s.save(PresetSpec(name="x", plugins=[]))
    s.delete("x")
    assert s.get("x") is None


def test_delete_missing_raises(tmp_path):
    with pytest.raises(ValueError):
        _store(tmp_path).delete("nope")


def test_name_rejects_path_traversal(tmp_path):
    s = _store(tmp_path)
    for bad in ("../evil", "..", ".", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            PresetSpec(name=bad, plugins=[])


def test_name_rejects_empty_and_too_long(tmp_path):
    with pytest.raises(ValueError):
        PresetSpec(name="", plugins=[])
    with pytest.raises(ValueError):
        PresetSpec(name="x" * 65, plugins=[])
```

- [ ] **Step 2: Run to verify fail** — módulo no existe.

- [ ] **Step 3: Implement** `store.py`:
  - `PresetSpec`: field_validator sobre `name` con regex `^[A-Za-z0-9 _.\-]{1,64}$` y rechazo explícito de `name in {".", ".."}` y de `/`/`\`.
  - `_assert_contained` importado de `stfu.hub.registry` (o replicado) usado en get/save/delete sobre `base_dir` y `f"{name}.json"`.
  - `PresetStore`: `base_dir.mkdir(parents=True, exist_ok=True)`; list glob `*.json`; get lee/parsea; save escribe `model_dump_json(indent=2)`; delete `unlink` con `ValueError` si falta.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest tests/test_preset_store.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat(presets): PresetStore con validación de nombre y containment`

---

### Task 2: Seed presets curados + rutas `/presets`

**Files:**
- Create: `backend/stfu/presets/curated/gaming.json`, `reunion.json`, `streaming.json`, `podcast.json`, `musica.json`, `accesibilidad.json`
- Create: `backend/stfu/api/routes/presets.py`
- Modify: `backend/stfu/main.py` (montar router)
- Test: `backend/tests/test_presets_api.py`

**Interfaces:**
- `GET /presets` → lista de `{name, plugins, builtin: bool}` (curados marcados `builtin: true`, guardados `false`). `GET /presets/{name}` → el preset (busca en guardados, luego curados). `POST /presets/{name}` body `{plugins: [...]}` → guarda (nombre del path). `DELETE /presets/{name}` → borra un guardado (los curados no se borran → 400/409).

**Seed presets** (cadenas usando los plugins de Fase A; usan `model:fastenhancer-tiny`/`base` como el nodo NC — si el modelo no está instalado, aplicar el preset da 400 con mensaje claro, ya implementado en feeder_start; la UI de Fase C ofrecerá descargarlo):

- `gaming.json`: `{"name":"Gaming","plugins":[{"plugin_id":"model:fastenhancer-tiny","parameters":{"strength":1.0}},{"plugin_id":"noise_gate","parameters":{"threshold_db":-40.0,"release_ms":120.0}},{"plugin_id":"limiter","parameters":{"ceiling_db":-1.0}}]}`
- `reunion.json`: `{"name":"Reunión","plugins":[{"plugin_id":"model:fastenhancer-tiny","parameters":{"strength":1.0}},{"plugin_id":"compressor","parameters":{"agc":true,"agc_target_db":-18.0}},{"plugin_id":"limiter","parameters":{"ceiling_db":-1.0}}]}`
- `streaming.json`: cadena completa `model:fastenhancer-base` + noise_gate + compressor + eq_parametric (presencia: banda ~3kHz +3dB) + de_esser + limiter.
- `podcast.json`: `model:fastenhancer-base` + eq_parametric (warmth: banda ~200Hz +2, ~4kHz +2) + compressor + de_esser + limiter.
- `musica.json` (Music Mode): SIN suppressor agresivo — `[{"plugin_id":"model:fastenhancer-tiny","parameters":{"strength":0.3}},{"plugin_id":"limiter","parameters":{"ceiling_db":-1.0}}]` (strength bajo deja pasar instrumentos/tonos). Nota en el name/descripción: "deja pasar música e instrumentos".
- `accesibilidad.json`: `model:fastenhancer-base` + eq_parametric (boost banda de voz 1-4kHz) + compressor (realza voz suave, AGC on) + limiter.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_presets_api.py
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_list_includes_curated():
    r = client.get("/presets")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    for expected in ("Gaming", "Reunión", "Streaming", "Podcast", "Música", "Accesibilidad"):
        assert expected in names


def test_curated_marked_builtin():
    r = client.get("/presets")
    gaming = next(p for p in r.json() if p["name"] == "Gaming")
    assert gaming["builtin"] is True
    assert isinstance(gaming["plugins"], list) and len(gaming["plugins"]) >= 1


def test_save_and_get_user_preset(tmp_path, monkeypatch):
    # el store de usuario debe apuntar a un dir temporal para no ensuciar ~/.stfu
    import stfu.api.routes.presets as pr
    from stfu.presets.store import PresetStore
    monkeypatch.setattr(pr, "_user_store", PresetStore(tmp_path / "presets"))
    r = client.post("/presets/mi-preset", json={"plugins": [{"plugin_id": "gain", "parameters": {}}]})
    assert r.status_code == 200
    got = client.get("/presets/mi-preset")
    assert got.status_code == 200
    assert got.json()["plugins"][0]["plugin_id"] == "gain"


def test_delete_curated_rejected():
    r = client.delete("/presets/Gaming")
    assert r.status_code in (400, 409)
```

- [ ] **Step 2-4:** implementar rutas (`_curated_store` sobre el dir del repo `presets/curated`, `_user_store` sobre `~/.stfu/presets`; GET fusiona ambos con `builtin` flag; POST/DELETE solo sobre user; DELETE de un nombre curado → 409). Montar en main. Escribir los 6 JSON. Correr → PASS. Cuidado con `_curated_dir()` frozen (sys._MEIPASS) igual que el hub de modelos, y agregar `presets/curated` a los `datas` del PyInstaller spec.

- [ ] **Step 5: Commit** — `feat(presets): seeds de escena (Gaming/Reunión/Streaming/Podcast/Música/Accesibilidad) + rutas /presets`

---

### Task 3: PyInstaller datas + suite + smoke

**Files:**
- Modify: `backend/stfu-backend.spec` (agregar `presets/curated` a datas)

- [ ] **Step 1:** en `stfu-backend.spec`, agregar `("stfu/presets/curated", "stfu/presets/curated")` a `datas` (junto a `hub/curated`).

- [ ] **Step 2: Suite** — `.\.venv\Scripts\python.exe -m pytest -q` → todo verde (293 base + nuevos).

- [ ] **Step 3: Smoke** — arrancar uvicorn, `curl http://localhost:8765/presets` (lista los 6 curados con sus cadenas), matar. Verificar que un preset se puede aplicar: `POST /presets/Prueba {plugins:[{plugin_id:gain,parameters:{}}]}` → `GET /presets/Prueba` → el preset. Commit de cierre si quedó algo (`chore` del spec).
