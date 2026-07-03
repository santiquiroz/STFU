# STFU v2 — Driver de micrófono virtual ("STFU Microphone")

**Fecha:** 2026-07-03
**Motivo del pivote:** los APO de software no cargan en mics USB (Blue Snowball = 1 propiedad FX de fábrica vs ~130 del Realtek de placa base; audiodg nunca instancia el APO). Verificado exhaustivamente en hardware real. El driver virtual funciona con CUALQUIER dispositivo (patrón NVIDIA Broadcast/Krisp).

---

## Arquitectura — Modelo A (loopback cable, kernel mínimo)

**Base a forkear:** `VirtualDrivers/Virtual-Audio-Driver` (MIT, linaje SYSVAD/PortCls-WaveRT). Ya resuelve lo caro que no es DSP: empaquetado Win11, INF, x64/ARM64, release production-signed 2025, pipeline de firma en GitHub Actions, y ya expone speaker + mic virtual como endpoints separados.

**Problema verificado en fuente:** el mic de VirtualDrivers emite SILENCIO (`minwavertstream.cpp`: la rama captura hace `RtlZeroMemory`). No hay loopback ni feed de user-mode. Hay que añadir el camino de audio.

**Pieza a portar:** `RingBuffer.cpp/.h` de `JannesP/AudioMirror` (MIT, sysvad-derived) — el único proyecto con el loopback exacto (`Put()` productor + `Take()` que llena el DMA de captura, con spinlock).

**Flujo:**
```
[mic físico] --WASAPI capture--> [Python: DFN3 + drift servo (YA hecho)]
     --WASAPI render--> [STFU Audio Bridge (render oculto)]
     --RingBuffer kernel--> [STFU Microphone (captura)] --> Discord/Zoom
```

- **Kernel escrito: ~1-2 archivos.** Reemplazar el `WriteBytes`-silencio del mic por `RingBuffer->Take()` y el `ReadBytes`-a-archivo del speaker por `RingBuffer->Put()`. Portar `RingBuffer.*` tal cual. **El DSP jamás entra al kernel.**
- El backend Python escribe los frames limpios de DFN3 al "STFU Audio Bridge" con un cliente WASAPI render estándar. Cero IOCTL, cero shared memory custom, cero IPC kernel propio.

**Modelo B (evolución futura, solo si la latencia lo exige):** fill directo vía IOCTL/sección compartida al buffer de captura, elimina el speaker pareado — pero exige plumbing real de kernel. El buffer cíclico WaveRT NO sirve como canal de inyección (es para el consumidor). No ahora.

**Descartados:** Scream (sin captura), VB-CABLE (closed-source), ACX AudioCodec (mejor base greenfield a largo plazo, trae render+capture, es la ruta MS recomendada — pero curva KMDF/ACX empinada, sin loopback listo, sin precedente virtual-mic; no vale el tiempo-a-primer-mic ahora).

---

## Fases

- **Fase 0 — Toolchain (gratis):** descargar EWDK ISO build 26100 (debe igualar el SDK 10.0.26100 presente; regla: build de SDK == build de WDK). Montar ISO → `LaunchBuildEnv.cmd` → `msbuild`. Sin instalar VS completo ni WDK aparte. (El VS BuildTools 2018 instalado es muy viejo, ignorar.)
- **Fase 1 — Fork + compilar as-is:** forkear VirtualDrivers, compilar con test-signing, instalar (`pnputil`), validar los dos endpoints. De-risk opcional: compilar AudioMirror en VM Win10 x64 para confirmar el cable end-to-end antes de tocar el fork.
- **Fase 2 — Renombrar endpoints:** `STFU Microphone` / `STFU Audio Bridge` en INF/topology. Confirmar que Discord/Zoom/Windows los ven.
- **Fase 3 — Loopback kernel (único código kernel real):** portar `RingBuffer.*`, cablear `Put()`/`Take()`. Test: reproducir en Bridge → oír en Microphone.
- **Fase 4 — Feeder Python:** el pipeline abre cliente WASAPI render sobre el Bridge y escribe PCM. Reusar captura WASAPI + FormatAdapter soxr.
- **Fase 5 — DFN3 en vivo:** DeepFilterNet3 entre captura física y escritura al Bridge. Validar latencia e2e + drift servo.
- **Fase 6 — Firma para distribución** (ver abajo).

---

## Firma (verificado 2025/2026)

| Etapa | Mecanismo | Costo / fricción |
|---|---|---|
| **Dev (tú)** | test-signing: `bcdedit /set testsigning on`, `New-SelfSignedCertificate`, `signtool`, `pnputil` | Gratis. **Secure Boot OFF** obligatorio. Watermark "Test Mode". Iterás libre, sin round-trip a Microsoft. |
| **Alpha/testers** | Partner Center (gratis) + **EV cert** + attestation signing | EV: Sectigo ~$279-360/año (o Sole-Proprietor EV vía SSL.com sin empresa); DigiCert ~$560-700. Desde 15-feb-2026: validez máx 1 año, llave en token FIPS/HSM. |
| **Release** | El MISMO .sys attestation-signed | Carga con Secure Boot ON en cualquier Win10/11, sin watermark, instalado por tu NSIS. Patrón Krisp/NVIDIA. |

**Proceso de firma por versión:** `MakeCab` (driver + INF) → firmar CAB con EV cert → subir a Partner Center (cajas test-signing sin marcar) → Microsoft re-firma con catálogo SHA-2 → descargar. **Automatizado, minutos-horas, sin lab HLK, sin costo por envío.** Scriptable en CI.

**Re-firmar en cada fix:** solo para builds DISTRIBUIDOS, no para tu desarrollo (ese es test-signing). Cada re-firma es rápida y automatizable — con el kernel mínimo, trivial.

**Un cert EV cubre TODO:** todos tus proyectos que necesiten firma + firma el `STFU.exe`/instalador (elimina SmartScreen "editor desconocido").

**No hacer:** WHQL/HLK (solo para Windows Update/logo OEM). Azure Trusted Signing NO firma kernel. Cross-signing muerto (24H2). Attestation es el único camino vivo.

---

## Reúso del código actual (casi todo)

- Captura WASAPI del mic físico → completa.
- FormatAdapter (soxr) → conciliar formato con el Bridge.
- DFN3 / pipeline DSP → intacto, user-mode Python, jamás kernel.
- Drift servo + `auto_convert=True` → reusar; ahora gobierna la escritura al Bridge.
- Frontend → sin cambios de arquitectura; añadir toggle de estado del mic virtual.
- Instalador NSIS → empaqueta el `.sys` firmado + INF, ejecuta `pnputil`.
- RingBuffer de AudioMirror → se porta, no se reescribe.

---

## Esfuerzo estimado (~3-4 semanas de calendario)

- Fase 0-2 (setup + fork + renombrado): 2-4 días
- Fase 3 (portar loopback): 3-6 días (corazón técnico, acotado a 1-2 archivos)
- Fase 4-5 (feeder + DFN3 vivo): 3-5 días reusando pipeline
- Fase 6 (Partner Center + EV + attestation): 3-10 días calendario (dominado por compra/validación EV, no por código)

La mayor incertidumbre es el onboarding de firma, no el kernel.

---

## Correcciones de la verificación adversarial

- **Refutado (parcial):** que test-signing en 24H2/26100 requiera Safe Mode o desactivar HVCI cada vez — NO soportado por fuentes MS. Confirmado sí: Secure Boot OFF + watermark. Verificar empíricamente en tu build.
- **Confirmado sólido:** mic de VirtualDrivers = silencio; VirtualDrivers MIT + mic separado + release firmado 2025 + CI; AudioMirror MIT con RingBuffer real; EWDK ISO compila con MSBuild sin VS full; regla SDK==WDK 26100; attestation suficiente (WHQL no); Azure Trusted Signing no firma kernel; sin tier gratis.

## Fuentes clave
- github.com/VirtualDrivers/Virtual-Audio-Driver · github.com/JannesP/AudioMirror · github.com/microsoft/Windows-driver-samples (sysvad, Acx/AudioCodec)
- learn.microsoft.com/windows-hardware/drivers/dashboard/code-signing-attestation · EWDK "Other WDK downloads"
