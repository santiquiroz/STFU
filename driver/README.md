# STFU Microphone — driver de audio virtual (v2)

Fork de [VirtualDrivers/Virtual-Audio-Driver](https://github.com/VirtualDrivers/Virtual-Audio-Driver) (MIT, linaje SYSVAD/PortCls-WaveRT) + el `RingBuffer` de [JannesP/AudioMirror](https://github.com/JannesP/AudioMirror) (MIT) para el loopback.

**Qué expone:** dos endpoints —
- `STFU Microphone` (captura) — el que Discord/Zoom eligen.
- `STFU Audio Bridge` (render oculto) — donde el backend Python escribe el audio ya limpio de DeepFilterNet3.

Kernel = solo un cable: `Audio Bridge` (render) → RingBuffer → `STFU Microphone` (captura). **Nada de DSP en kernel.**

## Estado
- [x] Base forkeada (VirtualDrivers) + RingBuffer portado (AudioMirror)
- [ ] Cambios de código (ver `DRIVER-CHANGES.md`) — se hacen y compilan en la máquina de dev con Secure Boot OFF
- [ ] Compilar con EWDK (`build.ps1`)
- [ ] test-sign + instalar (`install-test.ps1`)
- [ ] Renombrar endpoints
- [ ] Loopback kernel (RingBuffer compartido)
- [ ] Firma attestation (release)

## Requisitos de la máquina de dev
- **Secure Boot OFF** (obligatorio para test-signing).
- **EWDK build 26100** (ISO, debe igualar el Windows SDK 10.0.26100). Descargar de "Other WDK downloads" de Microsoft. Montar → `LaunchBuildEnv.cmd` → `msbuild`.
- No requiere Visual Studio completo.

## Atribución
- Código original VirtualDrivers/Virtual-Audio-Driver: MIT (ver `LICENSE`).
- Código de sample de Microsoft (SYSVAD): MS-PL (ver `THIRD_PARTY_NOTICES.md`).
- RingBuffer de AudioMirror: MIT (ver `AudioMirror-LICENSE.md`).
