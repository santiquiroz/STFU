from typing import Iterator
import numpy as np
import soxr
from stfu.core.audio_format import AudioFormat


class FormatAdapter:
    """Convierte entre AudioFormats: canales, sample rate y rechunking.

    El resampler mantiene estado FIR entre llamadas (soxr.ResampleStream):
    resamplear chunk a chunk sin estado produce clicks en cada borde.
    """

    def __init__(self, src: AudioFormat, dst: AudioFormat) -> None:
        self._src = src
        self._dst = dst
        self._buffer = np.empty((0, dst.channels), dtype=np.float32)
        self._resampler: soxr.ResampleStream | None = None
        if src.sample_rate != dst.sample_rate:
            self._resampler = soxr.ResampleStream(
                src.sample_rate, dst.sample_rate, dst.channels, dtype="float32"
            )

    def convert(self, audio: np.ndarray) -> Iterator[np.ndarray]:
        chunk = self._convert_channels(audio)
        chunk = self._resample(chunk)
        yield from self._rechunk(chunk)

    def _convert_channels(self, audio: np.ndarray) -> np.ndarray:
        if self._src.channels == self._dst.channels:
            return audio
        if self._src.channels == 1 and self._dst.channels == 2:
            return np.repeat(audio, 2, axis=1)
        if self._src.channels == 2 and self._dst.channels == 1:
            return np.mean(audio, axis=1, keepdims=True).astype(np.float32)
        raise ValueError(f"Unsupported channel conversion: {self._src.channels}→{self._dst.channels}")

    def _resample(self, audio: np.ndarray) -> np.ndarray:
        if self._resampler is None:
            return audio
        out = self._resampler.resample_chunk(np.ascontiguousarray(audio))
        return out.reshape(-1, self._dst.channels)

    def _rechunk(self, audio: np.ndarray) -> Iterator[np.ndarray]:
        self._buffer = np.concatenate([self._buffer, audio], axis=0)
        target = self._dst.chunk_samples
        while len(self._buffer) >= target:
            yield self._buffer[:target].copy()
            self._buffer = self._buffer[target:]

    @property
    def buffering_latency_ms(self) -> float:
        src_ms = self._src.chunk_samples / self._src.sample_rate * 1000.0
        dst_ms = self._dst.chunk_samples / self._dst.sample_rate * 1000.0
        return max(0.0, dst_ms - src_ms)
