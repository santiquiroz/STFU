"""Jobs de descarga en background con progreso consultable en memoria.

HubManager.download() bloquea en I/O de red; correrlo en un hilo separado
deja el endpoint HTTP responder de inmediato con un job_id, y el WS de
progreso puede sondear el estado del job sin bloquear el event loop."""
import logging
import threading
import uuid
from dataclasses import dataclass, replace
from typing import Literal
from stfu.hub.manager import HubManager

_log = logging.getLogger(__name__)

JobStatus = Literal["pending", "downloading", "done", "error"]


@dataclass(frozen=True)
class DownloadJob:
    status: JobStatus = "pending"
    downloaded: int = 0
    total: int | None = None
    error: str | None = None

    def to_payload(self) -> dict:
        return {
            "status": self.status,
            "downloaded": self.downloaded,
            "total": self.total,
            "pct": _percent(self.downloaded, self.total),
            "error": self.error,
        }


def _percent(downloaded: int, total: int | None) -> float | None:
    if not total:
        return None
    return round(downloaded / total * 100, 1)


class DownloadJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = DownloadJob()
        return job_id

    def get(self, job_id: str) -> DownloadJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update_progress(self, job_id: str, downloaded: int, total: int | None) -> None:
        self._replace(job_id, status="downloading", downloaded=downloaded, total=total)

    def mark_done(self, job_id: str) -> None:
        self._replace(job_id, status="done")

    def mark_error(self, job_id: str, message: str) -> None:
        self._replace(job_id, status="error", error=message)

    def _replace(self, job_id: str, **changes: object) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return
            self._jobs[job_id] = replace(current, **changes)


# Registro global usado por la app real; los tests inyectan su propia
# instancia para no compartir estado entre casos.
download_jobs = DownloadJobRegistry()


def start_download_job(
    hub: HubManager, model_id: str, registry: DownloadJobRegistry | None = None
) -> str:
    target_registry = registry or download_jobs
    job_id = target_registry.create()
    thread = threading.Thread(
        target=_run_download_job,
        args=(hub, model_id, job_id, target_registry),
        daemon=True,
        name=f"download-{job_id[:8]}",
    )
    thread.start()
    return job_id


def _run_download_job(
    hub: HubManager, model_id: str, job_id: str, registry: DownloadJobRegistry
) -> None:
    try:
        hub.download(model_id, on_progress=lambda d, t: registry.update_progress(job_id, d, t))
        registry.mark_done(job_id)
    except Exception as e:  # boundary de background thread: nunca debe morir en silencio
        _log.exception("descarga de %s falló (job %s)", model_id, job_id)
        registry.mark_error(job_id, str(e))
