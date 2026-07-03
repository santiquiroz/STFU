import threading
import numpy as np
import pytest
from stfu.audio.transport import RingBuffer, DriftServo


def _data(n: int, value: float = 1.0) -> np.ndarray:
    return np.full((n, 2), value, dtype=np.float32)


def test_ring_write_then_read_roundtrip():
    ring = RingBuffer(capacity=1000, channels=2)
    ring.write(_data(300, 0.5))
    out = ring.read(300)
    np.testing.assert_array_equal(out, _data(300, 0.5))
    assert ring.fill == 0


def test_ring_wraps_around():
    ring = RingBuffer(capacity=100, channels=2)
    for i in range(10):
        ring.write(_data(30, float(i)))
        out = ring.read(30)
        np.testing.assert_array_equal(out, _data(30, float(i)))


def test_ring_overflow_drops_and_counts():
    ring = RingBuffer(capacity=100, channels=2)
    written = ring.write(_data(150))
    assert written == 100
    assert ring.overflows == 1
    assert ring.fill == 100


def test_ring_underflow_pads_silence_and_counts():
    ring = RingBuffer(capacity=100, channels=2)
    ring.write(_data(40, 1.0))
    out = ring.read(100)
    np.testing.assert_array_equal(out[:40], _data(40, 1.0))
    np.testing.assert_array_equal(out[40:], _data(60, 0.0))
    assert ring.underflows == 1


def test_servo_fill_above_target_slows_production():
    servo = DriftServo(target_fill=1000)
    for _ in range(200):
        servo.observe(1200)  # entrada corre más rápido
    servo.update()
    assert servo.ratio < 1.0


def test_servo_fill_below_target_speeds_production():
    servo = DriftServo(target_fill=1000)
    for _ in range(200):
        servo.observe(800)
    servo.update()
    assert servo.ratio > 1.0


def test_servo_correction_clamped_to_max_ppm():
    servo = DriftServo(target_fill=1000, max_ppm=200.0, slew_ppm=1e9)
    for _ in range(500):
        servo.observe(10_000)  # error enorme
    servo.update()
    assert servo.ppm == pytest.approx(-200.0)


def test_servo_slew_limits_change_per_update():
    servo = DriftServo(target_fill=1000, slew_ppm=20.0)
    for _ in range(500):
        servo.observe(10_000)
    servo.update()
    assert servo.ppm == pytest.approx(-20.0)  # un paso, no el clamp completo
    servo.update()
    assert servo.ppm == pytest.approx(-40.0)


def test_servo_at_target_keeps_unity_ratio():
    servo = DriftServo(target_fill=1000)
    for _ in range(100):
        servo.observe(1000)
    servo.update()
    assert servo.ratio == pytest.approx(1.0)


def test_servo_rejects_nonpositive_target_fill():
    with pytest.raises(ValueError, match="target_fill"):
        DriftServo(target_fill=0)
    with pytest.raises(ValueError):
        DriftServo(target_fill=-10)


def test_servo_ratio_derives_from_ppm_factor():
    servo = DriftServo(target_fill=1000, max_ppm=200.0, slew_ppm=1e9)
    for _ in range(500):
        servo.observe(10_000)
    servo.update()
    # ratio = 1 + ppm*1e-6; con ppm clamped a -200 => 0.9998 exacto
    assert servo.ppm == pytest.approx(-200.0)
    assert servo.ratio == pytest.approx(1.0 + servo.ppm * 1e-6)
    assert servo.ratio == pytest.approx(0.9998)


def test_servo_converges_to_clamp_without_overshoot():
    servo = DriftServo(target_fill=1000, max_ppm=200.0, slew_ppm=20.0)
    for _ in range(500):
        servo.observe(10_000)  # error enorme y sostenido
    for _ in range(100):
        servo.update()
    # tras muchos updates el ppm se estabiliza exactamente en el clamp, sin pasarse
    assert servo.ppm == pytest.approx(-200.0)
    prev = servo.ppm
    servo.update()
    assert servo.ppm == pytest.approx(prev)  # ya no se mueve


def test_ring_overflow_partial_preserves_old_and_new_in_order():
    ring = RingBuffer(capacity=100, channels=2)
    # llena 80/100 con ceros conocidos (valor 0.5 para distinguir de silencio)
    ring.write(_data(80, 0.5))
    # escribe 40 nuevos; solo caben 20
    new = np.arange(1, 41, dtype=np.float32).reshape(-1, 1).repeat(2, axis=1)
    written = ring.write(new)
    assert written == 20
    assert ring.overflows == 1
    assert ring.fill == 100
    out = ring.read(100)
    # primero los 80 viejos intactos
    np.testing.assert_array_equal(out[:80], _data(80, 0.5))
    # luego exactamente los primeros 20 nuevos (new[:20]), no los ultimos
    np.testing.assert_array_equal(out[80:], new[:20])


def test_ring_read_empty_returns_silence_and_counts():
    ring = RingBuffer(capacity=100, channels=2)
    out = ring.read(50)
    np.testing.assert_array_equal(out, _data(50, 0.0))
    assert ring.underflows == 1
    assert ring.fill == 0


def test_ring_underflow_with_wrap_boundary():
    ring = RingBuffer(capacity=100, channels=2)
    # posiciona read_pos/write_pos cerca del final: escribe 90, lee 90
    ring.write(_data(90, 9.0))
    ring.read(90)  # read_pos=90, fill=0
    # escribe 30 (envuelve: 10 al final, 20 al inicio)
    ring.write(_data(30, 7.0))
    # lee 50 pidiendo mas de lo disponible: 30 datos (con wrap) + 20 silencio
    out = ring.read(50)
    np.testing.assert_array_equal(out[:30], _data(30, 7.0))
    np.testing.assert_array_equal(out[30:], _data(20, 0.0))
    assert ring.underflows == 1


def test_ring_concurrent_producer_consumer_preserves_order_and_bounds():
    cap = 256
    ring = RingBuffer(capacity=cap, channels=1)
    total = 20_000
    block = 37
    fill_violations = []
    order_ok = [True]
    seen = [0]
    last = [0.0]

    def producer():
        i = 1
        while i <= total:
            n = min(block, total - i + 1)
            data = np.arange(i, i + n, dtype=np.float32).reshape(-1, 1)
            written = ring.write(data)
            i += written  # solo avanza lo aceptado; el resto se reintenta

    def consumer():
        guard = 0
        while seen[0] < total and guard < 2_000_000:
            guard += 1
            out = ring.read(53)
            f = ring.fill
            if not (0 <= f <= cap):
                fill_violations.append(f)
            for v in out[:, 0]:
                if v == 0.0:
                    continue  # silencio de underflow
                if v <= last[0]:
                    order_ok[0] = False
                last[0] = float(v)
                seen[0] += 1

    p = threading.Thread(target=producer)
    c = threading.Thread(target=consumer)
    c.start(); p.start(); p.join(); c.join(timeout=10)

    assert not fill_violations, f"fill fuera de [0,{cap}]: {fill_violations[:5]}"
    assert order_ok[0], "se leyeron datos fuera de orden o duplicados"
    assert seen[0] == total, f"consumidos {seen[0]} de {total}"
    assert 0 <= ring.fill <= cap
