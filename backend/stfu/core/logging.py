"""Logging a archivo rotativo para diagnóstico con testers."""
import logging
import logging.handlers
import os
import platform
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".stfu" / "logs"
_LOG_FILE = LOG_DIR / "backend.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = os.environ.get("STFU_LOG_LEVEL", "INFO").upper()
    handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.setLevel(level)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stderr))
    _log_environment()


def _log_environment() -> None:
    """Reporte de entorno al arrancar: primera línea que se mira en un log de tester."""
    log = logging.getLogger("stfu.startup")
    log.info("=== STFU backend start ===")
    log.info("python=%s platform=%s", sys.version.split()[0], platform.platform())
    try:
        import sounddevice as sd
        api_names = [a["name"] for a in sd.query_hostapis()]
        log.info("portaudio=%s hostapis=%s", sd.get_portaudio_version()[1], api_names)
        for d in sd.query_devices():
            if d["max_input_channels"] > 0 or d["max_output_channels"] > 0:
                log.info(
                    "device[%s] in=%d out=%d rate=%d name=%s",
                    d["index"] if "index" in d else "?",
                    d["max_input_channels"], d["max_output_channels"],
                    int(d["default_samplerate"]), d["name"],
                )
    except Exception:
        log.exception("no se pudieron enumerar dispositivos")
