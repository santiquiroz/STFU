# STFU APO — COM DLL user-mode (audiodg.exe)

Cancelación de ruido inline en el motor de audio de Windows: sin dispositivos
virtuales ni drivers kernel. El APO corre dentro de `audiodg.exe` y bridgea
el audio al servicio Python vía named pipe.

## Arquitectura

```
audiodg.exe (RT)                         servicio STFU (Python)
┌─────────────────────────────┐          ┌──────────────────────┐
│ APOProcess()                │          │ ApoPipeServer        │
│   in → SpscRing ─┐          │   pipe   │   parse STFUFrame    │
│                  ├ worker ──┼──────────┤   Pipeline.process   │
│   out ← SpscRing ┘  thread  │          │   respond            │
│   (sin datos → passthrough) │          └──────────────────────┘
└─────────────────────────────┘
```

- `APOProcess` es RT-safe: solo copia memoria a rings lock-free (`spsc_ring.h`).
- El worker (`pipe_worker.cpp`) es el único que toca el pipe; si el servicio
  no está corriendo, el audio pasa limpio (passthrough) — nunca se corta.
- Formatos: el APO exige float32 (mix format de shared mode); el motor de
  Windows hace toda la SRC antes de entregarle audio. El server Python
  compila el `Pipeline` según el formato real del primer frame.

## Build

```powershell
cd apo
./build.ps1          # → build/stfu_apo.dll  (requiere VS Build Tools + SDK)
```

`test_pipe.exe` (harness): valida el protocolo contra el server Python sin
tocar audiodg:

```powershell
# terminal 1: servicio con bridge activo (POST /apo/bridge/Capture)
# terminal 2:
./build/test_pipe.exe
```

## Registro (riesgos reales — leer antes)

1. **APO sin firma:** audiodg solo carga APOs firmados. Igual que Equalizer
   APO, se requiere `DisableProtectedAudioDG=1`
   (`POST /apo/unsigned`, admin). Trade-off: apps que exigen ruta de audio
   protegida pueden negarse a reproducir.
2. **Registro por endpoint:** `POST /apo/register` escribe el CLSID en
   `HKLM\...\MMDevices\...\FxProperties` (MFX en captura, SFX en render),
   **guardando backup del CLSID previo** (`~/.stfu/apo_fx_backup.json`);
   `DELETE /apo/register/{flow}` restaura el original. Reinicia `audiosrv`
   (corta el audio del sistema ~2s). Requiere admin.
3. **Reinstalar el driver de audio borra el registro**, y un cumulative
   update de Windows 11 24H2 puede desactivar el APO en silencio. Auto-repair
   ya está shipped: `stfu/apo/health.py` compara los endpoints registrados
   contra su estado real, `ApoHealthMonitor` corre el chequeo en background
   (con un pase inmediato al arranque del backend) y publica un snapshot
   cacheado; `GET /apo/health` expone el diagnóstico y `POST /apo/repair`
   re-registra los endpoints desactivados (elevado, reinicia `audiosrv` una
   sola vez para todo el batch).
4. Clientes en modo exclusivo (WASAPI exclusive/ASIO) **bypasean** los APO.

CLSIDs (deben coincidir en `src/guids.h`, `backend/stfu/apo/constants.py`,
`frontend/src/services/api.ts`):

- Mic (MFX):     `{A5C595A5-CE9C-41DE-B555-82867799E74B}`
- Speaker (SFX): `{BD92FF05-2825-4D63-919B-D89FAF679713}`
