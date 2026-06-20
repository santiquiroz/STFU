from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal
import numpy as np
from stfu.core.audio_format import AudioFormat


@dataclass
class Parameter:
    id: str
    label: str
    type: Literal["float", "int", "bool", "enum"]
    default: Any
    min: Any = None
    max: Any = None
    options: list[str] | None = None


class AudioPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @property
    @abstractmethod
    def preferred_format(self) -> AudioFormat: ...

    @abstractmethod
    def setup(self, fmt: AudioFormat) -> AudioFormat: ...

    @abstractmethod
    def process(self, audio: np.ndarray) -> np.ndarray: ...

    @abstractmethod
    def teardown(self) -> None: ...

    @property
    @abstractmethod
    def algorithmic_latency_ms(self) -> float: ...

    @property
    @abstractmethod
    def parameters(self) -> list[Parameter]: ...

    def set_parameter(self, id: str, value: Any) -> None:
        pass
