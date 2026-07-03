import threading
import numpy as np


class RingBuffer:
    """Ring de samples float32 entre el worker y el callback de salida.

    write() descarta lo que no cabe (cuenta overflow); read() rellena con
    silencio lo que falte (cuenta underflow). El lock se sostiene solo
    durante copias de memoria acotadas.
    """

    def __init__(self, capacity: int, channels: int) -> None:
        self._buf = np.zeros((capacity, channels), dtype=np.float32)
        self._capacity = capacity
        self._channels = channels
        self._read_pos = 0
        self._write_pos = 0
        self._fill = 0
        self._lock = threading.Lock()
        self.overflows = 0
        self.underflows = 0

    def write(self, data: np.ndarray) -> int:
        with self._lock:
            n = min(len(data), self._capacity - self._fill)
            if n < len(data):
                self.overflows += 1
            first = min(n, self._capacity - self._write_pos)
            self._buf[self._write_pos:self._write_pos + first] = data[:first]
            if n > first:
                self._buf[:n - first] = data[first:n]
            self._write_pos = (self._write_pos + n) % self._capacity
            self._fill += n
            return n

    def read(self, n: int) -> np.ndarray:
        out = np.zeros((n, self._channels), dtype=np.float32)
        with self._lock:
            avail = min(n, self._fill)
            if avail < n:
                self.underflows += 1
            first = min(avail, self._capacity - self._read_pos)
            out[:first] = self._buf[self._read_pos:self._read_pos + first]
            if avail > first:
                out[first:avail] = self._buf[:avail - first]
            self._read_pos = (self._read_pos + avail) % self._capacity
            self._fill -= avail
        return out

    @property
    def fill(self) -> int:
        with self._lock:
            return self._fill


class DriftServo:
    """Compensa el drift de reloj entre dos dispositivos ajustando el ratio
    de resampleo en ppm según el llenado del ring (patrón CamillaDSP/zita).

    observe() alimenta un EMA del llenado en cada chunk; update() (llamado
    cada varios segundos) mueve la corrección hacia el error observado con
    clamp y slew-limit para que el cambio de pitch sea inaudible.
    """

    def __init__(
        self,
        target_fill: int,
        max_ppm: float = 200.0,
        gain_ppm: float = 400.0,
        slew_ppm: float = 20.0,
        ema_alpha: float = 0.05,
    ) -> None:
        if target_fill <= 0:
            raise ValueError("target_fill debe ser > 0 (se usa como divisor del error)")
        self._target = float(target_fill)
        self._max_ppm = max_ppm
        self._gain_ppm = gain_ppm
        self._slew_ppm = slew_ppm
        self._alpha = ema_alpha
        self._fill_ema = float(target_fill)
        self._ppm = 0.0

    def observe(self, fill: int) -> None:
        self._fill_ema += self._alpha * (fill - self._fill_ema)

    def update(self) -> None:
        error = (self._fill_ema - self._target) / self._target
        # llenado creciente = entrada más rápida que salida → producir menos
        desired = float(np.clip(-error * self._gain_ppm, -self._max_ppm, self._max_ppm))
        delta = float(np.clip(desired - self._ppm, -self._slew_ppm, self._slew_ppm))
        self._ppm += delta

    @property
    def ratio(self) -> float:
        return 1.0 + self._ppm * 1e-6

    @property
    def ppm(self) -> float:
        return self._ppm
