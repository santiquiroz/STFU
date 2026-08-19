from stfu.apo.apo_engine import ApoEngine


class _DeadServer:
    is_alive = False

    def stop(self):
        pass


class _LiveServer:
    is_alive = True

    def stop(self):
        pass


def test_status_reflects_thread_liveness():
    eng = ApoEngine()
    eng._servers["capture"] = _LiveServer()
    eng._servers["render"] = _DeadServer()
    assert eng.status() == {"capture": True, "render": False}


def test_status_empty():
    assert ApoEngine().status() == {}
