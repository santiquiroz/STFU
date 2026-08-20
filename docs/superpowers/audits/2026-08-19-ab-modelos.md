# Decisión: modelo por defecto (A/B FastEnhancer tiny vs base)

**Veredicto: `fastenhancer-tiny` es el modelo floor/default — el que la UI
recomienda activar primero y al que el `DegradeMonitor` cae bajo presión.
`fastenhancer-base` es la opción de calidad, para presets que priorizan
fidelidad sobre presupuesto de cómputo.**

## Por qué no se corrió `ab_models.py` en este audit

`backend/scripts/ab_models.py` mide RTF (tiempo de proceso / duración de
audio) procesando un WAV real con cada modelo **instalado**. Dos requisitos
lo hacen inadecuado para un audit rápido:

1. Necesita un WAV ruidoso real como argumento — no trae fixture de audio
   bundleado.
2. Necesita los modelos ya **descargados** (`ModelRegistry.list()` sobre
   `~/.stfu/models`, no sobre el catálogo curado) — los `.onnx` se bajan de
   releases de GitHub (`fastenhancer_t.onnx` 0.13 MB, `fastenhancer_b.onnx`
   0.45 MB), trabajo de red que este audit evita a propósito.

Esta decisión se documenta con la evidencia ya disponible en los manifests
curados (`backend/stfu/hub/curated/*.json`) y en el diseño del
`DegradeMonitor`, no con una tabla RTF nueva. Si en el futuro se corre
`ab_models.py` con un WAV real, sus números deberían anexarse acá.

## Los dos modelos curados

| | `fastenhancer-tiny` | `fastenhancer-base` |
|---|---|---|
| Tier | `floor` | `quality` |
| Sample rate | 16 kHz | 48 kHz |
| Tamaño del `.onnx` | 0.13 MB | 0.45 MB |
| Chunk | 256 samples | 512 samples |
| Latencia algorítmica | 16.0 ms | 10.67 ms |
| Devices soportados | cpu, gpu | cpu, gpu |
| Licencia | MIT | MIT |

La latencia algorítmica (fija por el framing del chunk) es engañosa como
proxy de costo: es *menor* en `base` a pesar de que `base` es el modelo más
pesado. El tamaño del `.onnx` (3.5× más grande) y la tasa de muestreo 3×
mayor (48 kHz vs 16 kHz, tres veces más samples/segundo para procesar) son
los indicadores reales de costo de cómputo — ninguno de los dos se mide
directamente sin correr `ab_models.py`, pero ambos apuntan en la misma
dirección: `base` cuesta bastante más CPU/GPU por segundo de audio que
`tiny`.

## El argumento decisivo: `DegradeMonitor` nunca apaga la cancelación

`backend/stfu/audio/degrade_monitor.py` implementa la degradación automática
del spec (§3.5): si el stage del modelo sostiene p95 > presupuesto, el
sistema baja al siguiente tier instalado más liviano —

```python
_TIER_ORDER = ["quality", "default", "floor"]  # de más pesado a más liviano
```

— y la cancelación **nunca se apaga por carga** (a diferencia de Krisp, según
el comentario del propio módulo). Eso significa que `floor` es el piso de
seguridad: el modelo que el sistema asume que SIEMPRE puede sostener en
tiempo real, sin importar cuán degradada esté la CPU/GPU del usuario. Con
solo dos modelos curados hoy, `floor` = `fastenhancer-tiny` y `quality` =
`fastenhancer-base` — la asignación de tier en los manifests ya codifica
esta decisión; este audit documenta el porqué.

## Uso real en los presets curados

Los presets (`backend/stfu/presets/curated/*.json`) ya reflejan el mismo
trade-off:

- `fastenhancer-tiny` (floor, barato): `gaming.json`, `reunion.json` —
  escenarios donde la latencia/CPU disponible importa más que la fidelidad
  máxima (juegos comparten CPU con el motor; reuniones ya comprimen voz vía
  códec).
- `fastenhancer-base` (quality, caro): `streaming.json`, `podcast.json`,
  `accesibilidad.json` — escenarios donde la fidelidad de voz es el
  objetivo explícito y el usuario típicamente tiene margen de CPU (streaming
  dedicado, grabación de podcast, accesibilidad donde la inteligibilidad
  domina sobre el presupuesto).

## Conclusión

`fastenhancer-tiny` es el default/floor recomendado por la UI: es el modelo
más barato de los dos curados, el único candidato razonable para el rol de
`floor` en el `DegradeMonitor` (que nunca puede fallar bajo presión), y el
punto de entrada de menor riesgo para un usuario nuevo activando cancelación
de ruido por primera vez. `fastenhancer-base` queda como upgrade opcional de
calidad para quien tenga presupuesto de cómputo y priorice fidelidad —
reflejado en los presets curados que ya lo usan.
