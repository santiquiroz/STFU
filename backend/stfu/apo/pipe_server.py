"""APO named pipe server that bridges the APO COM DLL to the Python pipeline."""

import logging
import struct
import threading
import time
import numpy as np

# Try importing win32 modules; they're only available on Windows with pywin32 installed
try:
    import win32pipe
    import win32file
    import pywintypes
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

_log = logging.getLogger(__name__)

_HDR_FMT = "<IIII"   # frame_id, sample_rate, channels, num_samples
_HDR_SIZE = struct.calcsize(_HDR_FMT)


def parse_request_frame(data: bytes) -> dict:
    """Parse incoming audio frame from APO DLL.

    Expected binary format:
      - 4 bytes: frame_id (uint32)
      - 4 bytes: sample_rate (uint32)
      - 4 bytes: channels (uint32)
      - 4 bytes: num_samples (uint32)
      - N bytes: audio samples (float32)
    """
    frame_id, sample_rate, channels, num_samples = struct.unpack_from(_HDR_FMT, data)
    raw = np.frombuffer(data, dtype=np.float32, offset=_HDR_SIZE)
    audio = raw.reshape(num_samples, channels)
    return {
        "frame_id": frame_id,
        "sample_rate": sample_rate,
        "channels": channels,
        "num_samples": num_samples,
        "audio": audio,
    }


def build_response_frame(frame_id: int, audio: np.ndarray) -> bytes:
    """Build response frame to send back to APO DLL.

    Binary format:
      - 4 bytes: frame_id (uint32)
      - 4 bytes: num_samples (uint32)
      - N bytes: audio samples (float32)
    """
    num_samples = audio.shape[0]
    header = struct.pack("<II", frame_id, num_samples)
    return header + audio.astype(np.float32).tobytes()


class ApoPipeServer:
    """Named pipe server that bridges the APO COM DLL to the Python pipeline."""

    def __init__(self, pipe_name: str, pipeline):
        self._pipe_name = pipe_name
        self._pipeline = pipeline
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the named pipe server."""
        if not _WIN32_AVAILABLE:
            raise RuntimeError("pywin32 required on Windows; install via: pip install pywin32")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the named pipe server."""
        self._stop_event.set()

    def _accept_loop(self) -> None:
        """Accept incoming client connections."""
        while not self._stop_event.is_set():
            pipe = None
            try:
                pipe = win32pipe.CreateNamedPipe(
                    self._pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536, 65536, 0, None,
                )
                win32pipe.ConnectNamedPipe(pipe, None)
                threading.Thread(target=self._handle_client, args=(pipe,), daemon=True).start()
            except pywintypes.error:
                _log.exception("pipe accept error")
                if pipe is not None:
                    win32file.CloseHandle(pipe)

    def _handle_client(self, pipe) -> None:
        """Handle a single client connection."""
        try:
            while not self._stop_event.is_set():
                _, avail, _ = win32pipe.PeekNamedPipe(pipe, 0)
                if avail == 0:
                    time.sleep(0.01)
                    continue
                _, data = win32file.ReadFile(pipe, 65536)
                req = parse_request_frame(bytes(data))
                processed = self._pipeline.process(req["audio"].copy())
                response = build_response_frame(req["frame_id"], processed)
                win32file.WriteFile(pipe, response)
        except pywintypes.error:
            pass
        finally:
            win32file.CloseHandle(pipe)
