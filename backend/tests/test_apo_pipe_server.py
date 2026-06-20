import struct
import numpy as np
import pytest
from stfu.apo.pipe_server import build_response_frame, parse_request_frame

SAMPLE_RATE = 48000
CHANNELS    = 2
NUM_SAMPLES = 480

def _build_request(frame_id=1):
    audio = np.zeros((NUM_SAMPLES, CHANNELS), dtype=np.float32)
    header = struct.pack("<IIII", frame_id, SAMPLE_RATE, CHANNELS, NUM_SAMPLES)
    return header + audio.tobytes()

def test_parse_request_frame():
    data = _build_request(frame_id=42)
    req = parse_request_frame(data)
    assert req["frame_id"] == 42
    assert req["sample_rate"] == SAMPLE_RATE
    assert req["channels"] == CHANNELS
    assert req["num_samples"] == NUM_SAMPLES
    assert req["audio"].shape == (NUM_SAMPLES, CHANNELS)

def test_build_response_frame_matches_frame_id():
    audio = np.ones((NUM_SAMPLES, CHANNELS), dtype=np.float32)
    frame = build_response_frame(99, audio)
    frame_id, num_samples = struct.unpack_from("<II", frame, 0)
    assert frame_id == 99
    assert num_samples == NUM_SAMPLES
