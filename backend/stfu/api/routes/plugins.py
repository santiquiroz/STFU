import dataclasses
from fastapi import APIRouter
from stfu.core.pipeline_factory import BUILTIN_PLUGINS

router = APIRouter()


def _plugin_catalog_entry(plugin_id: str, cls) -> dict:
    plugin = cls()
    return {
        "plugin_id": plugin_id,
        "name": plugin.name,
        "version": plugin.version,
        "parameters": [dataclasses.asdict(p) for p in plugin.parameters],
    }


@router.get("/plugins")
def get_plugins():
    return [_plugin_catalog_entry(plugin_id, cls) for plugin_id, cls in BUILTIN_PLUGINS.items()]
