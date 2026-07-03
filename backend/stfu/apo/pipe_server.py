"""APO named pipe server that bridges the APO COM DLL to the Python pipeline."""

import logging
import struct
import threading
import time
import numpy as np

# Try importing win32 modules; they're only available on Windows with pywin32 installed
try:
    import win32api
    import win32con
    import win32file
    import win32pipe
    import win32security
    import ntsecuritycon
    import pywintypes
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

from stfu.core.audio_format import AudioFormat

_log = logging.getLogger(__name__)

_HDR_FMT = "<IIII"   # frame_id, sample_rate, channels, num_samples
_HDR_SIZE = struct.calcsize(_HDR_FMT)
_MAX_MESSAGE = 1 << 20


def parse_request_frame(data: bytes) -> dict:
    """Parse incoming audio frame from APO DLL.

    Expected binary format:
      - 4 bytes: frame_id (uint32)
      - 4 bytes: sample_rate (uint32)
      - 4 bytes: channels (uint32)
      - 4 bytes: num_samples (uint32)
      - N bytes: audio samples (float32, interleaved)
    """
    if len(data) < _HDR_SIZE:
        raise ValueError("frame demasiado corto")
    frame_id, sample_rate, channels, num_samples = struct.unpack_from(_HDR_FMT, data)
    if channels == 0 or channels > 8 or num_samples == 0 or num_samples > 1 << 20:
        raise ValueError(f"header inválido: channels={channels} num_samples={num_samples}")
    expected = _HDR_SIZE + num_samples * channels * 4
    if len(data) < expected:
        raise ValueError(f"payload incompleto: {len(data)} < {expected}")
    raw = np.frombuffer(data, dtype=np.float32, offset=_HDR_SIZE,
                        count=num_samples * channels)
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


def _pipe_security_attributes():
    """DACL que permite conectar a audiodg.exe (LOCAL SERVICE) y al usuario.

    Sin esto el pipe hereda el DACL por defecto del usuario y el APO dentro
    de audiodg no puede abrirlo.
    """
    sd = win32security.SECURITY_DESCRIPTOR()
    dacl = win32security.ACL()
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    local_service = win32security.ConvertStringSidToSid("S-1-5-19")
    system = win32security.ConvertStringSidToSid("S-1-5-18")
    access = ntsecuritycon.GENERIC_READ | ntsecuritycon.GENERIC_WRITE
    for sid in (user_sid, local_service, system):
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access, sid)
    sd.SetSecurityDescriptorDacl(1, dacl, 0)
    sa = pywintypes.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    return sa


class ApoPipeServer:
    """Named pipe server that bridges the APO COM DLL to the Python pipeline."""

    def __init__(self, pipe_name: str, pipeline):
        self._pipe_name = pipe_name
        self._pipeline = pipeline
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._fmt_key: tuple[int, int, int] | None = None

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
        sa = _pipe_security_attributes()
        while not self._stop_event.is_set():
            pipe = None
            try:
                pipe = win32pipe.CreateNamedPipe(
                    self._pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    _MAX_MESSAGE, _MAX_MESSAGE, 0, sa,
                )
                win32pipe.ConnectNamedPipe(pipe, None)
                threading.Thread(target=self._handle_client, args=(pipe,), daemon=True).start()
            except pywintypes.error:
                _log.exception("pipe accept error")
                if pipe is not None:
                    win32file.CloseHandle(pipe)

    def _compile_for(self, req: dict) -> None:
        fmt_key = (req["sample_rate"], req["channels"], req["num_samples"])
        if fmt_key == self._fmt_key:
            return
        self._pipeline.compile(
            AudioFormat(req["sample_rate"], req["channels"], req["num_samples"])
        )
        self._fmt_key = fmt_key
        _log.info("APO bridge compilado para %s", fmt_key)

    def _handle_client(self, pipe) -> None:
        """Handle a single client connection."""
        try:
            while not self._stop_event.is_set():
                _, avail, _ = win32pipe.PeekNamedPipe(pipe, 0)
                if avail == 0:
                    time.sleep(0.002)
                    continue
                _, data = win32file.ReadFile(pipe, _MAX_MESSAGE)
                try:
                    req = parse_request_frame(bytes(data))
                except ValueError:
                    _log.warning("frame malformado descartado (%d bytes)", len(data))
                    continue
                try:
                    self._compile_for(req)
                    processed = self._pipeline.process(req["audio"].copy())
                except Exception:
                    # nunca matar al cliente: passthrough ante error de DSP
                    _log.exception("error procesando frame %d", req["frame_id"])
                    processed = req["audio"]
                response = build_response_frame(req["frame_id"], processed)
                win32file.WriteFile(pipe, response)
        except pywintypes.error:
            pass
        finally:
            win32file.CloseHandle(pipe)
