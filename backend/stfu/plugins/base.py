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
    def setup(self, fmt: AudioFormat) -> AudioFormat:
        """Prepara el plugin para recibir audio en `fmt` y devuelve el
        formato que efectivamente produce en `process()`.

        Invariante requerido por el swap quirúrgico de Pipeline
        (`_swap_stage_in_place`): debe devolver `fmt` sin modificar. Un
        plugin cuyo `setup()` transforme el formato (devuelva algo distinto
        de `fmt`) es incompatible con ese camino — el adapter del stage
        siguiente, reutilizado sin reconstruir, quedaría con el formato de
        entrada equivocado. Un plugin así necesita recompilación completa,
        no swap in-place."""
        ...

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
