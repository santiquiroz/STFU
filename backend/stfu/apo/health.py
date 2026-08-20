"""Salud del registro del APO. Windows 11 24H2 puede desactivar un APO en
silencio tras un cumulative update, y reinstalar un driver de audio borra el
endpoint. Este módulo compara los endpoints donde registramos (backups) contra
su estado real — solo lee el registro, no requiere admin."""
import logging

from stfu.apo.constants import CLSID_BY_FLOW
from stfu.apo.endpoint_finder import _device_state, _flow_key
from stfu.apo.register import _load_backups, get_apo_status

_log = logging.getLogger(__name__)


def _parse_backup_key(key: str) -> tuple[str, str]:
    guid, _, flow = key.rpartition("|")
    return guid, flow


def _endpoint_exists(endpoint_guid: str, flow: str) -> bool:
    return _device_state(_flow_key(flow), endpoint_guid) != -1


def check_registrations() -> list[dict]:
    result = []
    for key in _load_backups():
        endpoint_guid, flow = _parse_backup_key(key)
        if flow not in CLSID_BY_FLOW:
            continue
        if not _endpoint_exists(endpoint_guid, flow):
            state = "endpoint-missing"
        else:
            status = get_apo_status(endpoint_guid, flow, CLSID_BY_FLOW[flow])
            state = "ok" if status.get("registered") else "deactivated"
        result.append({"endpoint_guid": endpoint_guid, "flow": flow, "state": state})
    return result


def failing_registrations() -> list[dict]:
    """Endpoints cuyo estado no es 'ok' — el detalle que needs_repair() opaca
    detrás de un bool."""
    return [r for r in check_registrations() if r["state"] != "ok"]


def needs_repair() -> bool:
    failing = failing_registrations()
    if failing:
        _log.warning(
            "APO necesita reparación en %d endpoint(s): %s",
            len(failing),
            [(r["flow"], r["endpoint_guid"], r["state"]) for r in failing],
        )
    return bool(failing)
