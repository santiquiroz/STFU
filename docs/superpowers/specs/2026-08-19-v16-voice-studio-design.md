# STFU v1.6 — "Voice Studio": diseño

**Estado:** diseño derivado de research (last30days wishlist + survey de extensibilidad, 2026-08-19). El usuario delegó la mejora creativa con autonomía amplia.

**Tesis:** STFU hoy cancela ruido con un modelo. v1.6 lo convierte en una **estación de voz any-device**: cadena DSP editable (gate, compressor/AGC, de-esser, limiter, EQ), feedback visual en vivo (espectro + reducción en dB), A/B bypass, Music Mode, y scene presets. Todo se apoya en que el backend YA soporta cadenas de plugins arbitrarias — el hardcoding a un solo modelo vive solo en el frontend.

## Por qué estas features (research)

Las 3 quejas más fuertes de Krisp/RTX/Broadcast/Discord y la necesidad #1 sin resolver:
1. **Suppression demasiado agresivo** ("robótico/bajo el agua/me corta la voz") → strength dry/wet + A/B bypass + medidor visible.
2. **Nivel de mic desparejo** ("unos gritan, otros no se oyen") → AGC/compressor (auto-leveling).
3. **"¿Está haciendo algo?"** → medidor de reducción en dB + espectro input-vs-removido (la UX más elogiada).
4. **Music/Instrument Mode** (instrumentos/soundboard atraviesan el filtro) — la necesidad más pedida que NINGÚN competidor resuelve → bypass rápido / pass-through.
Más: la cadena canónica de streamer/podcaster (Gate→EQ→Compressor→De-esser→Limiter) que la gente arma a mano en Equalizer APO/GoXLR, y scene presets con hotkeys.

## Alcance

### En alcance
- **Plugins DSP builtin nuevos** (numpy/scipy, formato-estable 48k/mono/960, patrón stateful de `eq_parametric.py` con swap atómico de estado):
  - `noise_gate` — threshold, attack, release, grace/hold; abre/cierra por RMS.
  - `compressor` — threshold, ratio, attack, release, makeup gain; con modo AGC (target RMS) para auto-leveling.
  - `de_esser` — banda de sibilancia (~5-8kHz) con reducción dinámica.
  - `limiter` — ceiling duro, look-ahead corto.
- **`GET /plugins`** — catálogo: por cada plugin_id builtin, su `name`, `version`, y `parameters` (metadata del `Parameter` dataclass para auto-generar UI).
- **Feeder con cadena arbitraria** — el backend ya lo soporta (`FeederConfig.plugins` es una lista ordenada); el frontend deja de mandar solo `deepfilternet3` y construye la cadena.
- **Telemetría de audio** en `_process_and_output` (worker, single-writer, patrón de los contadores xrun):
  - `pre_rms`/`post_rms` por chunk → `stats["audio"] = {pre_db, post_db, reduction_db}`.
  - `spectrum` — `np.fft.rfft` cada N chunks (gate por `_chunks_since_update`) sobre ~48 bins log → `stats["audio"]["spectrum_pre"]/["spectrum_post"]`.
  - Todo ride el `/status` + `/ws/metering` existente. Sin transporte de audio crudo al browser.
- **A/B bypass** — flag atómico en `CaptureThread` leído en `_process_or_passthrough`; `POST /feeder/bypass` + `POST /pipeline/{target}/bypass`. Glitch-free (el output es mismo-formato).
- **Music Mode** — un bypass toggle expuesto + un preset "Música" (gate abierto, strength bajo). El toggle rápido cubre soundboard/instrumento al instante.
- **Scene presets** — `PresetStore` espejo de `hub/registry.py`: `~/.stfu/presets/<name>.json` = la lista `PipelineConfig.plugins`. `GET/POST/DELETE /presets`. Seeds: Gaming, Reunión, Streaming, Podcast, Música, Accesibilidad.
- **UI** (tab nueva "Estudio" o expansión de Control):
  - Visualizador canvas: espectro (pre vs post overlay) + medidor de reducción en dB. `requestAnimationFrame` leyendo de `usePipelineStatus`/WS.
  - Editor de cadena: lista ordenada de plugins con sliders auto-generados del `Parameter` metadata; agregar/quitar/reordenar (aplica con restart del feeder — el swap live de add/remove es futuro).
  - Preset picker (cargar/guardar).
  - A/B bypass toggle (+ tecla espacio).

### Fuera de alcance (v1.7+ backlog)
- Studio Voice (modelo de enhancement/super-resolución ONNX) — L, requiere encontrar/convertir un modelo; se hace después como su propia fase (encaja en el hub existente).
- Monitor Mode (clasificación de sonidos ambientes YAMNet) — M, novel; backlog.
- Voice changer / anonimización — scope creep.
- Live captions (whisper.cpp) — v3 backlog.
- Global hotkeys del SO (más allá de la tecla espacio en foco) — requiere registro de hotkey del SO; futuro.
- Add/remove de plugins en vivo sin restart — el editor aplica con restart del feeder por ahora.

## Arquitectura (extension points verificados)

- Plugin nuevo = subclase de `AudioPlugin` (`plugins/base.py`) + 1 línea en el dict `builtin` de `pipeline_factory.py`. El invariante `setup()→fmt` se cumple trivialmente (DSP no cambia formato).
- Cadena = orden de la lista en `build_pipeline`; ya multi-stage con `FormatAdapter` entre formatos distintos (todos los builtins son 48k/mono/960 → sin costo de adapter entre ellos).
- Telemetría = atributos en `CaptureThread` escritos por el worker en `_process_and_output`, expuestos en `stats`. Mismo patrón single-writer/GIL que los contadores existentes.
- Presets = archivos JSON en `~/.stfu/presets/`, con la forma que `build_pipeline` ya consume (sin schema nuevo).
- UI = React/Tailwind zinc/green, primitivos en `components/ui.tsx`, `Parameter`-driven auto-form, canvas greenfield.

## Fases

| Fase | Contenido | Riesgo |
|---|---|---|
| **A** | DSP plugins (gate/compressor+AGC/de-esser/limiter) + `GET /plugins` catálogo + telemetría de audio (RMS/dB/spectrum) + A/B bypass | Bajo-medio; DSP con tests de propiedad (gate cierra bajo umbral, compressor reduce rango dinámico, limiter no pasa el techo) |
| **B** | `PresetStore` + rutas `/presets` + seeds de scene presets + feeder con cadena arbitraria (backend) | Bajo |
| **C** | UI: visualizador canvas, editor de cadena, preset picker, A/B toggle, Music Mode | Medio (canvas + auto-form greenfield) |

Cada fase: rama nueva desde master, subagent-driven con review adversarial, merge por PR. Release v1.6.0 al cerrar C.

## Testing
- Backend: tests de propiedad por plugin DSP (comportamiento, no solo shape): gate atenúa por debajo del threshold y pasa por encima; compressor baja el rango dinámico; AGC converge al target RMS; de-esser reduce energía en la banda de sibilancia con una señal de test; limiter garantiza |out| ≤ ceiling. Telemetría: reduction_db positivo cuando el modelo suprime; spectrum tiene N bins. Bypass: output == input crudo. Catálogo: `/plugins` lista los builtins con sus params. Presets: round-trip save/load, la cadena cargada corre.
- Frontend: type-check + build por task; smoke E2E al cierre (visualizador anima, editor arma una cadena, preset carga, bypass conmuta).
- El DSP real-time se valida además con un WAV de voz+ruido por el script `ab_models.py` extendido a cadenas.
