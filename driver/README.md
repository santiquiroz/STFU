# STFU Microphone — driver de audio virtual (v2)

**Estado: PAUSADO** — decisión explícita del usuario. El core kernel-mode
compila, firma y pasa las 3 fases de desarrollo (ver abajo), pero el foco
activo del proyecto es el **APO en modo usuario** (`apo/README.md`): no
requiere driver kernel, no requiere Secure Boot OFF ni test-signing, y ya
tiene auto-repair shipped. Este driver queda documentado tal como está, sin
más trabajo de código mientras dure la pausa.

Fork de [VirtualDrivers/Virtual-Audio-Driver](https://github.com/VirtualDrivers/Virtual-Audio-Driver) (MIT, linaje SYSVAD/PortCls-WaveRT) + el `RingBuffer` de [JannesP/AudioMirror](https://github.com/JannesP/AudioMirror) (MIT) para el loopback.

**Qué expone:** dos endpoints —
- `STFU Microphone` (captura) — el que Discord/Zoom eligen.
- `STFU Audio Bridge` (render oculto) — donde el backend Python escribe el audio ya limpio de DeepFilterNet3.

Kernel = solo un cable: `Audio Bridge` (render) → RingBuffer → `STFU Microphone` (captura). **Nada de DSP en kernel.**

## Estado
- [x] Base forkeada (VirtualDrivers) + RingBuffer portado (AudioMirror)
- [x] Cambios de código (ver `DRIVER-CHANGES.md`) — hechos y compilados en la máquina de dev con Secure Boot OFF
- [x] Compilar con EWDK (`build.ps1`) — Fase 1, exit 0 (ver `PROGRESS.md`)
- [x] Test-sign (`package.ps1`, cert propio CN=STFU Test Cert)
- [x] Renombrar endpoints — Fase 2, `.inf` stampa "STFU Microphone" / "STFU Audio Bridge"
- [x] Loopback kernel (RingBuffer compartido) — Fase 3, compila y firma
- [ ] Instalar en una máquina real (requiere elevación interactiva del usuario, UAC)
- [ ] Verificar el cable en runtime (`verify_cable.py`) — bloqueado por la instalación
- [ ] Firma attestation (release)

## Requisitos de la máquina de dev
- **Secure Boot OFF** (obligatorio para test-signing).
- **EWDK build 26100** (ISO, debe igualar el Windows SDK 10.0.26100). Descargar de "Other WDK downloads" de Microsoft. Montar → `LaunchBuildEnv.cmd` → `msbuild`.
- No requiere Visual Studio completo.

## Atribución
- Código original VirtualDrivers/Virtual-Audio-Driver: MIT (ver `LICENSE`).
- Código de sample de Microsoft (SYSVAD): MS-PL (ver `THIRD_PARTY_NOTICES.md`).
- RingBuffer de AudioMirror: MIT (ver `AudioMirror-LICENSE.md`).
