import logging
import queue
import threading
import time
import numpy as np
import samplerate
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.transport import RingBuffer, DriftServo

_log = logging.getLogger(__name__)

_INPUT_QUEUE_CHUNKS = 8
_RING_CHUNKS = 8
_TARGET_FILL_CHUNKS = 2
_SERVO_UPDATE_EVERY_CHUNKS = 250  # ~5s con chunks de 20ms


def _wasapi_auto_convert() -> "sd.WasapiSettings | None":
    """AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM: Windows resamplea cualquier
    dispositivo al formato canónico del engine (requiere sounddevice >= 0.4.7)."""
    if not hasattr(sd, "WasapiSettings"):
        return None
    try:
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


class CaptureThread:
    """Captura → pipeline (worker thread) → ring → reproducción.

    Los callbacks de PortAudio solo copian memoria: el pipeline (incluida la
    inferencia) corre en un worker propio. Entre worker y salida hay un ring
    con servo de drift: dos dispositivos tienen relojes independientes y sin
    corrección ppm el buffer se vacía/llena cada pocos minutos.
    """

    def __init__(
        self,
        input_device_id: int,
        output_device_id: int,
        fmt: AudioFormat,
        pipeline: Pipeline,
        out_channels: int | None = None,
    ) -> None:
        self._in = input_device_id
        self._out = output_device_id
        self._fmt = fmt
        self._pipeline = pipeline
        self._out_channels = out_channels if out_channels is not None else fmt.channels
        self._input_stream: sd.InputStream | None = None
        self._output_stream: sd.OutputStream | None = None
        self._in_queue: queue.Queue = queue.Queue(maxsize=_INPUT_QUEUE_CHUNKS)
        self._ring: RingBuffer | None = None
        self._servo: DriftServo | None = None
        self._resampler: samplerate.Resampler | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._latency_ms: float = 0.0
        self._input_overflows: int = 0
        self._output_underflows: int = 0
        self._queue_drops: int = 0

    def start(self) -> None:
        self._pipeline.compile(self._fmt)
        chunk = self._fmt.chunk_samples
        self._ring = RingBuffer(capacity=_RING_CHUNKS * chunk, channels=self._out_channels)
        self._ring.write(np.zeros((_TARGET_FILL_CHUNKS * chunk, self._out_channels), dtype=np.float32))
        self._servo = DriftServo(target_fill=_TARGET_FILL_CHUNKS * chunk)
        self._resampler = samplerate.Resampler("sinc_fastest", channels=self._out_channels)
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        try:
            self._output_stream = sd.OutputStream(
                device=self._out,
                samplerate=self._fmt.sample_rate,
                channels=self._out_channels,
                dtype=self._fmt.dtype,
                blocksize=chunk,
                latency="low",
                extra_settings=_wasapi_auto_convert(),
                callback=self._output_callback,
            )
            self._output_stream.start()
        except sd.PortAudioError:
            _log.warning("output stream failed to open (device %s); playback disabled", self._out, exc_info=True)
            self._output_stream = None

        try:
            self._input_stream = sd.InputStream(
                device=self._in,
                samplerate=self._fmt.sample_rate,
                channels=self._fmt.channels,
                dtype=self._fmt.dtype,
                blocksize=chunk,
                latency="low",
                extra_settings=_wasapi_auto_convert(),
                callback=self._input_callback,
            )
            self._input_stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)
            self._worker = None

    def _worker_loop(self) -> None:
        chunks_since_update = 0
        while not self._stop_event.is_set():
            try:
                chunk = self._in_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            t0 = time.perf_counter()
            processed = self._pipeline.process(chunk)
            self._latency_ms = (time.perf_counter() - t0) * 1000.0
            if self._output_stream is None:
                continue
            out = _adjust_channels(processed, self._out_channels)
            resampled = self._resampler.process(out, self._servo.ratio).astype(np.float32, copy=False)
            self._ring.write(resampled.reshape(-1, self._out_channels))
            self._servo.observe(self._ring.fill)
            chunks_since_update += 1
            if chunks_since_update >= _SERVO_UPDATE_EVERY_CHUNKS:
                self._servo.update()
                chunks_since_update = 0

    def _input_callback(
        self, indata: np.ndarray, frames: int, time_info, status
    ) -> None:
        if status and status.input_overflow:
            self._input_overflows += 1
        try:
            self._in_queue.put_nowait(indata.copy())
        except queue.Full:
            self._queue_drops += 1

    def _output_callback(
        self, outdata: np.ndarray, frames: int, time_info, status
    ) -> None:
        if status and status.output_underflow:
            self._output_underflows += 1
        outdata[:] = self._ring.read(frames)

    @property
    def measured_latency_ms(self) -> float:
        return self._latency_ms

    @property
    def playback_active(self) -> bool:
        return self._output_stream is not None

    @property
    def stats(self) -> dict:
        return {
            "playback_active": self.playback_active,
            "input_overflows": self._input_overflows,
            "output_underflows": self._output_underflows + (self._ring.underflows if self._ring else 0),
            "queue_drops": self._queue_drops + (self._ring.overflows if self._ring else 0),
            "ring_fill": self._ring.fill if self._ring else 0,
            "drift_ppm": round(self._servo.ppm, 2) if self._servo else 0.0,
        }


def _adjust_channels(audio: np.ndarray, out_ch: int) -> np.ndarray:
    proc_ch = audio.shape[1]
    if proc_ch == out_ch:
        return audio
    if proc_ch == 1 and out_ch > 1:
        return np.repeat(audio, out_ch, axis=1)
    return audio[:, :out_ch]
