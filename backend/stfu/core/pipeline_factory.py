"""Construcción de pipelines desde configs — compartido por AudioEngine,
ApoEngine y el feeder. Único lugar que mapea plugin_id → clase."""
import importlib.util
from pathlib import Path
from stfu.core.pipeline import Pipeline
from stfu.hub.registry import ModelRegistry
from stfu.plugins.builtin.eq_parametric import EQParametricPlugin
from stfu.plugins.builtin.gain import GainPlugin

_MODEL_PREFIX = "model:"
_registry_singleton: ModelRegistry | None = None


def default_registry() -> ModelRegistry:
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = ModelRegistry(Path.home() / ".stfu" / "models")
    return _registry_singleton


def _build_dfn3():
    if importlib.util.find_spec("df") is None:
        raise ValueError(
            "DeepFilterNet3 requiere el extra torch: pip install -r requirements-torch.txt"
        )
    from stfu.plugins.builtin.deepfilternet3 import DeepFilterNet3Plugin
    return DeepFilterNet3Plugin()


def _build_model_plugin(model_id: str, registry: ModelRegistry, device: str):
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    manifest = registry.get(model_id)
    model_path = registry.model_path(model_id)
    if manifest is None or model_path is None:
        raise ValueError(f"Plugin desconocido: model:{model_id} (modelo no instalado)")
    return OnnxStreamingPlugin(manifest, model_path, device=device)


def _make_plugin(plugin_id: str, registry: ModelRegistry | None, device: str):
    if plugin_id.startswith(_MODEL_PREFIX):
        reg = registry if registry is not None else default_registry()
        return _build_model_plugin(plugin_id[len(_MODEL_PREFIX):], reg, device)
    if plugin_id == "deepfilternet3":
        return _build_dfn3()
    builtin = {"eq_parametric": EQParametricPlugin, "gain": GainPlugin}
    cls = builtin.get(plugin_id)
    if cls is None:
        raise ValueError(f"Plugin desconocido: {plugin_id}")
    return cls()


def build_pipeline(plugin_configs: list[dict], registry: ModelRegistry | None = None,
                   device: str = "auto") -> Pipeline:
    pipeline = Pipeline()
    for cfg in plugin_configs:
        plugin = _make_plugin(cfg["plugin_id"], registry, device)
        for k, v in cfg.get("parameters", {}).items():
            plugin.set_parameter(k, v)
        pipeline.add_plugin(plugin)
    return pipeline
