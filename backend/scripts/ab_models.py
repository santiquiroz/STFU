"""Procesa un WAV ruidoso con cada modelo instalado: escribe un WAV por modelo
y reporta RTF (tiempo de proceso / duración del audio) en CPU.

Uso: python scripts/ab_models.py ruido.wav [--device cpu|gpu]
"""
import argparse
import time
from pathlib import Path

import numpy as np
import soundfile as sf  # scipy.io.wavfile como fallback si soundfile no está

from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline_factory import build_pipeline, default_registry


def process_wav(model_id: str, wav_path: Path, device: str) -> tuple[Path, float]:
    audio, rate = sf.read(wav_path, dtype="float32", always_2d=True)
    fmt = AudioFormat(sample_rate=rate, channels=audio.shape[1], chunk_samples=int(rate * 0.02))
    pipeline = build_pipeline([{"plugin_id": f"model:{model_id}"}], device=device)
    pipeline.compile(fmt)
    chunks = [
        audio[i:i + fmt.chunk_samples]
        for i in range(0, len(audio) - fmt.chunk_samples, fmt.chunk_samples)
    ]
    out = []
    t0 = time.perf_counter()
    for c in chunks:
        out.append(pipeline.process(c))
    elapsed = time.perf_counter() - t0
    rtf = elapsed / (len(audio) / rate)
    dest = wav_path.with_name(f"{wav_path.stem}__{model_id}.wav")
    sf.write(dest, np.concatenate(out), rate)
    return dest, rtf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    installed = [m.id for m in default_registry().list()]
    if not installed:
        raise SystemExit("no hay modelos instalados — POST /models/<id>/download primero")
    print(f"{'modelo':<24} {'RTF':>8}  salida")
    for model_id in installed:
        dest, rtf = process_wav(model_id, args.wav, args.device)
        print(f"{model_id:<24} {rtf:>8.4f}  {dest.name}")


if __name__ == "__main__":
    main()
