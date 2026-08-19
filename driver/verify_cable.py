"""Verificación automática del cable de audio del driver STFU (Fase 3).

Prueba que el loopback de kernel funciona SIN oídos humanos:
reproduce un seno de 1 kHz por "STFU Audio Bridge" (render) y simultáneamente
captura de "STFU Microphone" (captura); hace FFT de lo capturado y verifica
que hay un pico claro en ~1 kHz. Si el cable funciona, la señal reproducida
reaparece en la captura.

Uso (con el venv del backend):
    backend/.venv/Scripts/python.exe driver/verify_cable.py
    # opciones: --freq 1000 --seconds 2.0 --tolerance-hz 25 --min-snr-db 15

Salida: exit 0 = cable OK; exit 1 = falló la verificación; exit 2 = driver
no instalado (endpoints ausentes). numpy se importa siempre; sounddevice solo
al capturar, para que `dominant_frequency` sea testeable sin hardware.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import numpy as np

BRIDGE_RENDER_NAME = "STFU Audio Bridge"
MIC_CAPTURE_NAME = "STFU Microphone"


@dataclass(frozen=True)
class PeakResult:
    freq_hz: float
    magnitude: float
    snr_db: float


def dominant_frequency(signal: np.ndarray, sample_rate: int) -> PeakResult:
    """Frecuencia dominante de una señal mono vía FFT con ventana de Hann.

    Devuelve la frecuencia del pico, su magnitud y el SNR en dB (pico vs.
    mediana del resto del espectro). Función pura: testeable con señal
    sintética, sin hardware.
    """
    mono = _to_mono(signal)
    if mono.size == 0:
        return PeakResult(0.0, 0.0, 0.0)
    windowed = mono * np.hanning(mono.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)
    if spectrum.size < 2:
        return PeakResult(0.0, 0.0, 0.0)
    peak_idx = int(np.argmax(spectrum[1:]) + 1)  # ignora DC
    peak_mag = float(spectrum[peak_idx])
    noise_floor = _noise_floor(spectrum, peak_idx)
    snr_db = 20.0 * np.log10(peak_mag / noise_floor) if noise_floor > 0 else 0.0
    return PeakResult(freq_hz=float(freqs[peak_idx]), magnitude=peak_mag, snr_db=float(snr_db))


def _to_mono(signal: np.ndarray) -> np.ndarray:
    if signal.ndim == 1:
        return signal.astype(np.float64, copy=False)
    return signal.astype(np.float64, copy=False).mean(axis=1)


def _noise_floor(spectrum: np.ndarray, peak_idx: int) -> float:
    """Mediana del espectro excluyendo DC y una banda alrededor del pico."""
    mask = np.ones(spectrum.size, dtype=bool)
    mask[0] = False
    lo, hi = max(1, peak_idx - 2), min(spectrum.size, peak_idx + 3)
    mask[lo:hi] = False
    rest = spectrum[mask]
    return float(np.median(rest)) if rest.size else 0.0


def peak_matches_target(peak: PeakResult, target_hz: float, tol_hz: float, min_snr_db: float) -> bool:
    return abs(peak.freq_hz - target_hz) <= tol_hz and peak.snr_db >= min_snr_db


def _sine(freq_hz: float, seconds: float, sample_rate: int, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate), dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _find_device(name: str, want_input: bool):
    import sounddevice as sd

    key = "max_input_channels" if want_input else "max_output_channels"
    sub = name.lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev[key] > 0 and sub in dev["name"].lower():
            return idx, dev
    return None, None


def play_and_capture(freq_hz: float, seconds: float, sample_rate: int) -> tuple[np.ndarray, int]:
    """Reproduce el seno por el Bridge y captura del Microphone simultáneamente."""
    import sounddevice as sd

    out_idx, _ = _find_device(BRIDGE_RENDER_NAME, want_input=False)
    in_idx, _ = _find_device(MIC_CAPTURE_NAME, want_input=True)
    if out_idx is None or in_idx is None:
        missing = []
        if out_idx is None:
            missing.append(f"'{BRIDGE_RENDER_NAME}' (render)")
        if in_idx is None:
            missing.append(f"'{MIC_CAPTURE_NAME}' (captura)")
        raise LookupError("Endpoints del driver ausentes: " + ", ".join(missing))

    tone = _sine(freq_hz, seconds, sample_rate)
    captured: list[np.ndarray] = []

    def _in_cb(indata, frames, time_info, status):  # noqa: ANN001
        captured.append(indata.copy())

    with sd.InputStream(device=in_idx, samplerate=sample_rate, channels=1,
                        dtype="float32", callback=_in_cb):
        sd.play(tone, samplerate=sample_rate, device=out_idx, blocking=True)
        sd.sleep(200)

    if not captured:
        return np.zeros(0, dtype=np.float32), sample_rate
    return np.concatenate(captured, axis=0).reshape(-1), sample_rate


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verifica el cable de audio del driver STFU (loopback kernel).")
    p.add_argument("--freq", type=float, default=1000.0, help="frecuencia del seno de prueba (Hz)")
    p.add_argument("--seconds", type=float, default=2.0, help="duración de la prueba")
    p.add_argument("--sample-rate", type=int, default=48000)
    p.add_argument("--tolerance-hz", type=float, default=25.0, help="tolerancia del pico vs. objetivo")
    p.add_argument("--min-snr-db", type=float, default=15.0, help="SNR mínimo del pico para aceptar")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        signal, sr = play_and_capture(args.freq, args.seconds, args.sample_rate)
    except LookupError as exc:
        print(f"[SKIP] {exc}\nInstala el driver STFU y reintenta.", file=sys.stderr)
        return 2
    except Exception as exc:  # PortAudio u otros
        print(f"[ERROR] Fallo al reproducir/capturar: {exc}", file=sys.stderr)
        return 1

    if signal.size == 0:
        print("[FAIL] No se capturó audio (0 muestras).", file=sys.stderr)
        return 1

    peak = dominant_frequency(signal, sr)
    ok = peak_matches_target(peak, args.freq, args.tolerance_hz, args.min_snr_db)
    status = "PASS" if ok else "FAIL"
    print(
        f"[{status}] pico={peak.freq_hz:.1f} Hz (objetivo {args.freq:.0f} ±{args.tolerance_hz:.0f}), "
        f"SNR={peak.snr_db:.1f} dB (mín {args.min_snr_db:.0f})"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
