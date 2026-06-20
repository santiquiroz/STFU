from dataclasses import dataclass


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int
    chunk_samples: int
    dtype: str = "float32"

    @property
    def duration_ms(self) -> float:
        return (self.chunk_samples / self.sample_rate) * 1000.0
