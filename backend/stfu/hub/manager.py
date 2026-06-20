from pathlib import Path
from huggingface_hub import hf_hub_download, list_models
from stfu.hub.registry import ModelManifest, ModelRegistry


class HubManager:
    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def search_huggingface(self, query: str = "") -> list[dict]:
        models = list_models(tags=["stfu-compatible"], search=query, limit=20)
        return [{"repo_id": m.id, "tags": m.tags or []} for m in models]

    def download(self, repo_id: str, filename: str, manifest: ModelManifest) -> Path:
        local = hf_hub_download(repo_id=repo_id, filename=filename)
        self._registry.register(manifest, Path(local))
        return self._registry.model_path(manifest.id)
