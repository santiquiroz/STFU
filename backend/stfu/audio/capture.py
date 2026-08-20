import logging
import queue
import threading
import numpy as np
import samplerate
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.transport import RingBuffer, DriftServo
from stfu.audio.capture_stats import AudioTelemetry, _first_inference_status
from stfu.audio.capture_worker import PipelineWorker, _adjust_channels

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

    Compone dos colaboradores con dependencias explícitas: `PipelineWorker`
    (procesa/pasa el chunk y aplica swaps de plugin) y `AudioTelemetry`
    (acumula dB/espectro para `stats`). Esta clase retiene el ciclo de vida
    de los streams, el hilo worker y el ring/servo/resampler.
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
        self._pipeline_worker = PipelineWorker(pipeline)
        self._telemetry = AudioTelemetry()
        # Invariante: cada contador tiene UN solo hilo escritor (input CB o
        # output CB); con el GIL los += no pierden updates. No agregar
        # escritores sin repensar esto.
        self._input_overflows: int = 0
        self._output_underflows: int = 0
        self._queue_drops: int = 0
        self._worker_failed: bool = False
        self._chunks_since_update: int = 0

    def start(self) -> None:
        self._pipeline.compile(self._fmt)
        chunk = self._fmt.chunk_samples
        self._ring = RingBuffer(capacity=_RING_CHUNKS * chunk, channels=self._out_channels)
        self._ring.write(np.zeros((_TARGET_FILL_CHUNKS * chunk, self._out_channels), dtype=np.float32))
        self._servo = DriftServo(target_fill=_TARGET_FILL_CHUNKS * chunk)
        self._resampler = samplerate.Resampler("sinc_fastest", channels=self._out_channels)
        self._stop_event.clear()
        self._worker_failed = False
        self._chunks_since_update = 0
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        # Si la apertura de cualquier stream falla de forma dura, se limpia todo
        # (streams + worker) antes de propagar: nunca dejar el worker huérfano.
        try:
            self._open_output(chunk)
            self._open_input(chunk)
        except Exception:
            self.stop()
            raise

    def _open_output(self, chunk: int) -> None:
        # Playback es opcional: un fallo de dispositivo (PortAudioError) degrada a
        # 'sin playback'. Cualquier otro error se propaga tras cerrar el stream.
        stream = None
        try:
            stream = sd.OutputStream(
                device=self._out,
                samplerate=self._fmt.sample_rate,
                channels=self._out_channels,
                dtype=self._fmt.dtype,
                blocksize=chunk,
                latency="low",
                extra_settings=_wasapi_auto_convert(),
                callback=self._output_callback,
            )
            stream.start()
        except sd.PortAudioError:
            _log.warning("output stream failed to open (device %s); playback disabled", self._out, exc_info=True)
            _close_stream(stream)
            self._output_stream = None
            return
        except Exception:
            _close_stream(stream)
            raise
        self._output_stream = stream

    def _open_input(self, chunk: int) -> None:
        stream = None
        try:
            stream = sd.InputStream(
                device=self._in,
                samplerate=self._fmt.sample_rate,
                channels=self._fmt.channels,
                dtype=self._fmt.dtype,
                blocksize=chunk,
                latency="low",
                extra_settings=_wasapi_auto_convert(),
                callback=self._input_callback,
            )
            stream.start()
        except Exception:
            _close_stream(stream)
            raise
        self._input_stream = stream

    def stop(self) -> None:
        # Best-effort: el fallo al cerrar un stream no debe saltar la limpieza del
        # resto ni impedir que el worker termine.
        _close_stream(self._input_stream)
        self._input_stream = None
        _close_stream(self._output_stream)
        self._output_stream = None
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)
            self._worker = None
        self._pipeline.clear()

    def request_plugin_swap(self, index: int, plugin) -> None:
        self._pipeline_worker.request_swap(index, plugin)

    def request_plugin_insert(self, index: int, plugin) -> None:
        self._pipeline_worker.request_insert(index, plugin)

    def request_plugin_remove(self, index: int) -> None:
        self._pipeline_worker.request_remove(index)

    def set_bypass(self, on: bool) -> None:
        """Escritura atómica de un bool: el GIL garantiza que el worker nunca
        ve un estado a medio escribir, sin necesitar lock."""
        self._pipeline_worker.set_bypass(on)

    def _drain_swaps(self) -> None:
        self._pipeline_worker.drain_swaps()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            self._drain_swaps()
            try:
                chunk = self._in_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._process_and_output(chunk)
            except Exception:
                # Un fallo de INFRAESTRUCTURA (resample/ring/servo) detiene el
                # worker con flag visible. Un fallo de PLUGIN no llega acá:
                # _process_or_passthrough lo degrada a passthrough sin cortar audio.
                self._worker_failed = True
                _log.exception("worker del pipeline falló; procesamiento detenido")
                return

    def _process_and_output(self, chunk: np.ndarray) -> None:
        processed = self._process_or_passthrough(chunk)
        self._record_audio_telemetry(chunk, processed)
        if self._output_stream is None:
            return
        out = _adjust_channels(processed, self._out_channels)
        resampled = self._resampler.process(out, self._servo.ratio).astype(np.float32, copy=False)
        self._ring.write(resampled.reshape(-1, self._out_channels))
        self._servo.observe(self._ring.fill)
        self._chunks_since_update += 1
        if self._chunks_since_update >= _SERVO_UPDATE_EVERY_CHUNKS:
            self._servo.update()
            self._chunks_since_update = 0

    def _record_audio_telemetry(self, pre: np.ndarray, post: np.ndarray) -> None:
        self._telemetry.record(pre, post, self._fmt.sample_rate)

    def _process_or_passthrough(self, chunk: np.ndarray) -> np.ndarray:
        return self._pipeline_worker.process(chunk)

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
    def pipeline(self) -> Pipeline:
        return self._pipeline

    @property
    def measured_latency_ms(self) -> float:
        return self._pipeline_worker.latency_ms

    @property
    def playback_active(self) -> bool:
        return self._output_stream is not None

    @property
    def worker_failed(self) -> bool:
        return self._worker_failed

    @property
    def _pipeline_failed(self) -> bool:
        return self._pipeline_worker.pipeline_failed

    @property
    def stats(self) -> dict:
        return {
            "playback_active": self.playback_active,
            "worker_failed": self._worker_failed,
            "input_overflows": self._input_overflows,
            "output_underflows": self._output_underflows + (self._ring.underflows if self._ring else 0),
            "queue_drops": self._queue_drops + (self._ring.overflows if self._ring else 0),
            "ring_fill": self._ring.fill if self._ring else 0,
            "drift_ppm": round(self._servo.ppm, 2) if self._servo else 0.0,
            "pipeline_failed": self._pipeline_worker.pipeline_failed,
            "bypass": self._pipeline_worker.bypass,
            "stages": self._pipeline.stage_metrics(),
            "total_latency_ms": round(self._pipeline.total_latency_ms(), 2),
            "inference": _first_inference_status(self._pipeline._plugins),
            "audio": self._telemetry.snapshot(),
        }


def _close_stream(stream) -> None:
    if stream is None:
        return
    try:
        stream.stop()
        stream.close()
    except Exception:
        _log.warning("error cerrando stream de audio", exc_info=True)
