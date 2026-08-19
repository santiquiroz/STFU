# Decisión: NPU diferido (spike 2026-08-18)

**Veredicto: NO implementar runtime-packs de NPU ahora. Diferir. Mantener CPU (y GPU vía DirectML) como el path de inferencia real-time.**

El scaffolding actual (`ep_router` con el device `npu` que lanza `DeviceUnavailable`) es la representación correcta del estado: presente en el contrato, sin EP.

## Por qué (en orden de peso)

1. **El blocker real es model-fit, no packaging.** Las NPUs relevantes son mal fit para un denoiser recurrente streaming pequeño:
   - **QNN (Qualcomm, Snapdragon X)**: el NPU (HTP) categóricamente NO soporta dynamic shapes, Loops/Ifs, ni LSTM/GRU, y exige pesos cuantizados. Hard mismatch con FastEnhancer (recurrente, estado por frame, fp32).
   - **OpenVINO (Intel, Meteor/Lunar Lake)**: más capaz de ops (GRU/RNN soportados), pero el device NPU carga overhead de dispatch/compile por-inferencia que típicamente pierde contra CPU en tensores recurrentes de 10ms. Las NPUs están hechas para grafos grandes estáticos cuantizados, no frames de audio de baja latencia.
   - **VitisAI (AMD Ryzen AI)**: no está en PyPI (viene dentro del instalador de Ryzen AI SW).

2. **No existe una abstracción uniforme de "pip runtime-pack" entre vendors.** Solo Qualcomm shippea un plugin limpio y coexistente (`onnxruntime-qnn` 2.x, modelo plugin-EP de ORT 1.22+). OpenVINO es monolítico (provee el módulo `onnxruntime`, conflictúa con `onnxruntime-directml`, requiere venv+proceso aparte). VitisAI no está en pip. Construir una capa per-vendor `sys.path`+restart ahora codificaría un patrón que el modelo plugin-EP / Windows ML está obsoletando.

3. **La abstracción correcta a futuro ya existe pero está verde en Python.** Dos piezas:
   - **Plugin EPs** (ORT 1.22+): `onnxruntime.register_execution_provider_library(name, path)` + `SetEpSelectionPolicy(PREFER_NPU)`. Un plugin EP es una lib separada que se registra contra un ORT estándar — varios vendors pueden coexistir en un proceso. Hoy solo QNN y TensorRT shippean plugin.
   - **Windows ML** (GA sept-2025): `ExecutionProviderCatalog` descarga/gestiona los EPs por Windows Update (sirve QNN/OpenVINO/VitisAI/TensorRT). YA tiene API Python (`onnxruntime-windowsml` + `windowsml` ctypes shim, Python 3.10-3.13) pero rugosa: la API de conveniencia `EnsureAndRegisterCertifiedAsync()` es no-op en Python (hay que hacer find→ensure→register a mano), y hay un footgun de frontera de registro nativo↔Python. Requiere Win11 24H2 + Windows App SDK.

## Cuando se retome (backlog v-next)

- Arquitecturar la capa de device futura alrededor del **modelo plugin-EP** (`register_execution_provider_library` + `PREFER_NPU`), idealmente el `ExecutionProviderCatalog` de Windows ML, NO alrededor de instalaciones monolíticas per-vendor. El `ep_router` ya está aislado para esta migración.
- **Prerequisito que domina el esfuerzo**: producir una variante de modelo NPU-friendly — frame size fijo (sin dim temporal dinámica), estado recurrente como tensores de entrada/salida explícitos, cuantización int8/int16. Sin esto, ningún EP NPU sirve, independiente del packaging.

## Experimento opcional acotado (único vendor viable hoy)

Solo si se quiere probar, Qualcomm/Snapdragon X como extra pip opcional (no perturba el install actual):
- `onnxruntime==1.26.0` + `onnxruntime-qnn>=2.4,<3` (win_arm64, cp311-cp314).
- Registrar: `import onnxruntime_qnn; onnxruntime.register_execution_provider_library("qnn", <lib>)`.
- Requiere: NPU Hexagon de Snapdragon X (driver 30.0.140.0+); modelo **static-shape + cuantizado**; validación en hardware real (incluida la pregunta abierta de si el plugin QNN registra sobre un build `onnxruntime-directml` instalado, no documentado).
- NO intentar OpenVINO (monolítico) ni VitisAI (installer-only) como pip runtime-packs.

Fuentes verificadas en el spike: PyPI onnxruntime-qnn/openvino/windowsml, docs de QNN/OpenVINO/plugin-EP/Windows ML EPs de onnxruntime.ai y learn.microsoft.com, RyzenAI-SW #213.
