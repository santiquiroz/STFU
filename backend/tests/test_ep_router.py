import pytest
from stfu.inference import ep_router


def test_providers_for_gpu_includes_cpu_fallback():
    assert ep_router.providers_for("gpu") == ["DmlExecutionProvider", "CPUExecutionProvider"]


def test_providers_for_cpu():
    assert ep_router.providers_for("cpu") == ["CPUExecutionProvider"]


def test_providers_for_npu_raises_until_f25():
    with pytest.raises(ep_router.DeviceUnavailable):
        ep_router.providers_for("npu")


def test_auto_picks_first_device_whose_probe_passes():
    attempts = []

    def probe(providers):
        attempts.append(providers[0])
        return providers[0] == "CPUExecutionProvider"

    assert ep_router.select_device("auto", probe) == "cpu"
    # npu se saltea (sin EP), gpu probeó y falló, cpu pasó
    assert attempts == ["DmlExecutionProvider", "CPUExecutionProvider"]


def test_manual_device_does_not_fall_back():
    with pytest.raises(ep_router.DeviceUnavailable):
        ep_router.select_device("gpu", lambda providers: False)


def test_unknown_device_rejected():
    with pytest.raises(ValueError):
        ep_router.select_device("tpu", lambda p: True)
