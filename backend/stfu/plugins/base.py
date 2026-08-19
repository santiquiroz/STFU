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

    def _clamp_param(self, id: str, value: Any) -> Any:
        """Clampea/valida un valor de parámetro contra su Parameter declarado.
        Params float/int se clampean a [min,max]; params enum caen al default
        si el valor no está en options; ids desconocidos pasan sin tocar."""
        param = next((p for p in self.parameters if p.id == id), None)
        if param is None:
            return value
        if param.type in ("float", "int"):
            v = float(value)
            if param.min is not None:
                v = max(v, float(param.min))
            if param.max is not None:
                v = min(v, float(param.max))
            return int(round(v)) if param.type == "int" else v
        if param.type == "enum":
            return value if (param.options and value in param.options) else param.default
        if param.type == "bool":
            return bool(value)
        return value
