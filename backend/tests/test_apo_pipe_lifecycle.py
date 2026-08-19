import sys
import time
import pytest
from stfu.core.pipeline import Pipeline

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="named pipes")

_PIPE = r"\\.\pipe\stfu_test_lifecycle"
_PIPE_HANDLERS = r"\\.\pipe\stfu_test_lifecycle_handlers"


def test_stop_unblocks_accept_and_joins():
    from stfu.apo.pipe_server import ApoPipeServer
    server = ApoPipeServer(_PIPE, Pipeline())
    server.start()
    time.sleep(0.2)  # el accept loop queda bloqueado en ConnectNamedPipe
    assert server.is_alive is True
    t0 = time.perf_counter()
    server.stop()
    assert time.perf_counter() - t0 < 3.0  # no espera un cliente que nunca llega
    assert server.is_alive is False


def test_is_alive_false_before_start():
    from stfu.apo.pipe_server import ApoPipeServer
    server = ApoPipeServer(_PIPE, Pipeline())
    assert server.is_alive is False


def test_stop_joins_handler_threads():
    import win32file
    from stfu.apo.pipe_server import ApoPipeServer
    server = ApoPipeServer(_PIPE_HANDLERS, Pipeline())
    server.start()
    time.sleep(0.2)  # el accept loop queda bloqueado en ConnectNamedPipe

    client = win32file.CreateFile(
        _PIPE_HANDLERS,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0, None, win32file.OPEN_EXISTING, 0, None,
    )
    try:
        time.sleep(0.2)  # deja que el accept loop registre el handler thread
        with server._client_threads_lock:
            handler_threads = list(server._client_threads)
        assert len(handler_threads) == 1
        assert handler_threads[0].is_alive()

        server.stop()

        assert all(not t.is_alive() for t in handler_threads)
        with server._client_threads_lock:
            assert server._client_threads == []
    finally:
        win32file.CloseHandle(client)
