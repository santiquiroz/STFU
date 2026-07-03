# Blueprint de cambios — STFU Microphone

Modificaciones exactas sobre el fork de VirtualDrivers. Se ejecutan y **compilan/verifican paso a paso** en la máquina de dev (Secure Boot OFF + EWDK). NO escritas a ciegas: cada paso compila y se prueba antes del siguiente.

Referencias de línea contra el código clonado el 2026-07-03.

---

## Diseño del loopback (Modelo A)

VirtualDrivers ya tiene los dos endpoints pero **desconectados**: el mic emite silencio, el speaker vuelca a archivo. Hay que conectarlos con **UN RingBuffer compartido** entre ambos streams.

```
[STFU Audio Bridge / render] --ReadBytes--> Ring.Put()
                                              │
                                        (RingBuffer único, spinlock)
                                              │
[STFU Microphone / capture]  --WriteBytes--> Ring.Take()  (silencio si underrun)
```

**Punto de diseño crítico:** AudioMirror aloja el ring POR-STREAM (`m_RingBuffer` en cada stream) porque usa fill directo por IOCTL. Para el loopback puro necesitamos el ring **compartido a nivel de adapter/miniport**, no por-stream — así el stream de render y el de captura tocan el MISMO ring. Opción simple y robusta: un `RingBuffer` de scope de archivo (o en el contexto del adapter) protegido por su spinlock.

---

## Cambio 1 — Portar RingBuffer (Source/Utilities/RingBuffer.{cpp,h})

Ya copiado. Ajustes al compilar:
- `RingBuffer.h`: cambiar `#include "Globals.h"` (de AudioMirror) por el header común de VAD (`common.h` / `definitions.h`) que traiga `KSPIN_LOCK`, `KIRQL`, tipos.
- Definir el pool tag: AudioMirror usa `MINWAVERTSTREAM_POOLTAG`; usar el tag de VAD o definir `STFU_RING_POOLTAG 'RUTS'`.
- Añadir `RingBuffer.cpp` a `Source/Utilities/Utilities.vcxproj` (ItemGroup de ClCompile) y `RingBuffer.h` al ClInclude.

## Cambio 2 — RingBuffer compartido (Source/Main/minwavert.cpp / adapter)

Instanciar UN ring compartido, inicializado al primer stream (o en el adapter context):
```cpp
// scope de archivo en minwavertstream.cpp (o miembro del adapter):
static RingBuffer g_LoopbackRing;
static BOOL       g_RingReady = FALSE;
```
Init con `Init(dmaBufferSize * 4, blockAlign)` cuando arranca el primer stream y el formato esté fijado. Ambos endpoints DEBEN anunciar el mismo formato (ver Cambio 5).

## Cambio 3 — Mic Take (Source/Main/minwavertstream.cpp, WriteBytes ~L1392)

Reemplazar el silencio:
```cpp
// ANTES (L1417):
RtlZeroMemory(m_pDmaBuffer + bufferOffset, runWrite);
// DESPUÉS:
SIZE_T read = 0;
if (g_RingReady) g_LoopbackRing.Take(m_pDmaBuffer + bufferOffset, runWrite, &read);
if (read < runWrite) RtlZeroMemory(m_pDmaBuffer + bufferOffset + read, runWrite - read); // underrun = silencio
```

## Cambio 4 — Speaker Put (Source/Main/minwavertstream.cpp, ReadBytes ~L1426)

Reemplazar el volcado a archivo:
```cpp
// ANTES (L1449):
m_SaveData.WriteData(m_pDmaBuffer + bufferOffset, runWrite);
// DESPUÉS:
if (g_RingReady) g_LoopbackRing.Put(m_pDmaBuffer + bufferOffset, runWrite);
```
`WriteBytes`/`ReadBytes` se llaman desde el mismo path DPC (L1333/L1370) — el spinlock del ring cubre la concurrencia render↔capture.

## Cambio 5 — Formato único acordado

Ambos endpoints deben usar el mismo formato para que Put/Take sean byte-compatibles. Fijar 48000 Hz / 16-bit / estéreo (o float32) en las tablas de formato:
- `Source/Filters/speakerwavtable.h` y `micarraywavtable.h` — dejar UN formato coincidente.
- Windows hace SRC per-app gratis, así que un formato fijo basta.

## Cambio 6 — Renombrar endpoints a STFU

- **INF:** `Source/Main/VirtualAudioDriver.inx`, sección `[Strings]` — cambiar los `*.DeviceDesc` / friendly names a `STFU Microphone` y `STFU Audio Bridge`. (Localizar las claves de string que referencian los KSNAME_* de minipairs.h.)
- **Topology templates:** `Source/Filters/minipairs.h` — los nombres `L"TopologySpeaker"`, `L"WaveSpeaker"`, y sus equivalentes de micrófono deben seguir apareados con las [Strings] del INF (comentarios en el archivo lo indican).
- Cambiar nombre del producto/driver en `.inx`, `.rc` y la .sln si se quiere `stfu_audio.sys`.

## Cambio 7 — Limpiar scaffolding sysvad sobrante (opcional)

`Source/Utilities/ToneGenerator.*` y `savedata.*` quedan sin uso tras Cambios 3-4. Se pueden dejar (inertes) o quitar de los vcxproj para reducir el binario.

---

## Orden de verificación en la máquina (compilar-y-probar cada paso)

1. Compilar el fork **as-is** (`build.ps1`) → produce `.sys` + `.inf`. Sin cambios aún.
2. test-sign + instalar (`install-test.ps1`) → confirmar que aparecen 2 endpoints en Sonido.
3. Cambio 6 (renombrar) → recompilar → confirmar nombres "STFU Microphone" / "Audio Bridge".
4. Cambios 1-5 (loopback) → recompilar → reproducir audio en Audio Bridge, oírlo en STFU Microphone (cable funcional).
5. Wire feeder Python (backend) → mic físico → DFN3 → escribir a Audio Bridge → Discord oye limpio.
6. Firma attestation (release).

Cada paso que compile mal → parar y arreglar antes de seguir. No acumular cambios sin compilar.
