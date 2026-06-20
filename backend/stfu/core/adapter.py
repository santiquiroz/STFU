from math import gcd
from typing import Iterator
import numpy as np
from scipy.signal import resample_poly
from stfu.core.audio_format import AudioFormat


class FormatAdapter:
    def __init__(self, src: AudioFormat, dst: AudioFormat) -> None:
        self._src = src
        self._dst = dst
        self._buffer = np.empty((0, dst.channels), dtype=np.float32)

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
        if self._src.sample_rate == self._dst.sample_rate:
            return audio
        g = gcd(self._dst.sample_rate, self._src.sample_rate)
        resampled = resample_poly(audio, self._dst.sample_rate // g, self._src.sample_rate // g, axis=0)
        return resampled.astype(np.float32)

    def _rechunk(self, audio: np.ndarray) -> Iterator[np.ndarray]:
        self._buffer = np.concatenate([self._buffer, audio], axis=0)
        target = self._dst.chunk_samples
        while len(self._buffer) >= target:
            yield self._buffer[:target].copy()
            self._buffer = self._buffer[target:]

    @property
    def buffering_latency_ms(self) -> float:
        extra = max(0, self._dst.chunk_samples - self._src.chunk_samples)
        return extra / self._dst.sample_rate * 1000.0
