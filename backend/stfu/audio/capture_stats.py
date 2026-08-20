"""Métricas de audio (RMS pre/post, espectro) y estado de inferencia.

Responsabilidad única: acumular y exponer telemetría de audio. No conoce
threads, streams ni el pipeline en sí — solo transforma arrays de audio en
números/listas para la UI.
"""
import logging
import numpy as np

_log = logging.getLogger(__name__)

_SPECTRUM_UPDATE_EVERY_CHUNKS = 5  # rfft es caro: no correrlo cada chunk
_SPECTRUM_BINS = 48
_SPECTRUM_MIN_HZ = 20.0
_SPECTRUM_MAX_HZ = 20000.0
_DB_FLOOR = -120.0
_EPS = 1e-9


def _first_inference_status(plugins) -> dict | None:
    """runtime_status del primer plugin de inferencia en el pipeline (duck
    typing: solo el plugin ONNX NC lo expone hoy), o None si no hay ninguno."""
    for plugin in plugins:
        status = getattr(plugin, "runtime_status", None)
        if status is not None:
            return status
    return None


def _rms_db(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    return max(_DB_FLOOR, 20.0 * np.log10(rms + _EPS))


def _mono_mix(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio
    return audio.mean(axis=1)


def _log_spaced_spectrum_db(mono: np.ndarray, sample_rate: int) -> list:
    """Magnitud del rfft agrupada en bins log-espaciados (20Hz..20kHz), en dB."""
    magnitudes = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sample_rate)
    edges = np.geomspace(_SPECTRUM_MIN_HZ, _SPECTRUM_MAX_HZ, _SPECTRUM_BINS + 1)
    bins_db = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (freqs >= lo) & (freqs < hi)
        if np.any(mask):
            magnitude = float(magnitudes[mask].mean())
            bins_db.append(max(_DB_FLOOR, 20.0 * np.log10(magnitude + _EPS)))
        else:
            bins_db.append(_DB_FLOOR)
    return bins_db


class AudioTelemetry:
    """Acumula dB pre/post y espectro log-espaciado a partir de chunks.

    RMS pre/post es barato y corre cada chunk; el rfft del espectro es caro y
    solo corre cada _SPECTRUM_UPDATE_EVERY_CHUNKS para no comerse el
    presupuesto de 20ms del worker de audio. Es observabilidad, nunca debe
    tumbar al llamador: un chunk malformado (p.ej. un plugin que devuelve un
    array vacío sin lanzar excepción) degrada la telemetría de este tick en
    vez de propagar. Por eso record() calcula todo en variables locales y
    solo confirma en self si nada explotó.
    """

    def __init__(self) -> None:
        self.pre_db: float = _DB_FLOOR
        self.post_db: float = _DB_FLOOR
        self.spectrum_pre: list = []
        self.spectrum_post: list = []
        self._chunks_since_spectrum: int = 0

    def record(self, pre: np.ndarray, post: np.ndarray, sample_rate: int) -> None:
        try:
            pre_db = _rms_db(pre)
            post_db = _rms_db(post)
            chunks_since_spectrum = self._chunks_since_spectrum + 1
            spectrum_pre = self.spectrum_pre
            spectrum_post = self.spectrum_post
            if chunks_since_spectrum >= _SPECTRUM_UPDATE_EVERY_CHUNKS:
                chunks_since_spectrum = 0
                spectrum_pre = _log_spaced_spectrum_db(_mono_mix(pre), sample_rate)
                spectrum_post = _log_spaced_spectrum_db(_mono_mix(post), sample_rate)
        except Exception:
            _log.exception("telemetría de audio falló para este chunk; se mantienen valores previos")
            return
        self.pre_db = pre_db
        self.post_db = post_db
        self._chunks_since_spectrum = chunks_since_spectrum
        self.spectrum_pre = spectrum_pre
        self.spectrum_post = spectrum_post

    def snapshot(self) -> dict:
        return {
            "pre_db": round(self.pre_db, 1),
            "post_db": round(self.post_db, 1),
            "reduction_db": round(self.pre_db - self.post_db, 1),
            "spectrum_pre": self.spectrum_pre,
            "spectrum_post": self.spectrum_post,
        }
