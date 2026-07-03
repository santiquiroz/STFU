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
