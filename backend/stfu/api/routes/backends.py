from fastapi import APIRouter
import onnxruntime as ort

router = APIRouter()


@router.get("/backends")
def get_backends():
    available = ort.get_available_providers()
    backends = [{"id": "cpu", "name": "CPU", "available": True}]
    if "DmlExecutionProvider" in available:
        backends.append({"id": "directml", "name": "DirectML (AMD / Intel / NVIDIA)", "available": True})
    if "CUDAExecutionProvider" in available:
        backends.append({"id": "cuda", "name": "CUDA (NVIDIA)", "available": True})
    return backends
