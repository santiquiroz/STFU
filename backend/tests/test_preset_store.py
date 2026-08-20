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


def test_list_skips_corrupt_json_without_raising(tmp_path):
    s = _store(tmp_path)
    s.save(PresetSpec(name="ok", plugins=[]))
    (s.base_dir / "corrupt.json").write_text("{ not valid json ", encoding="utf-8")
    names = {p.name for p in s.list()}
    assert names == {"ok"}


def test_list_skips_json_failing_schema(tmp_path):
    s = _store(tmp_path)
    s.save(PresetSpec(name="ok", plugins=[]))
    # JSON válido pero que no cumple el esquema (name faltante) también se ignora.
    (s.base_dir / "bad-schema.json").write_text('{"plugins": []}', encoding="utf-8")
    names = {p.name for p in s.list()}
    assert names == {"ok"}
