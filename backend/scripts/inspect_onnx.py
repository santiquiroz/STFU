"""Imprime IO spec + sha256 de un .onnx: todo lo que necesita un manifest curado.

Uso: python scripts/inspect_onnx.py <ruta-o-url-del-modelo>
"""
import hashlib
import sys
import tempfile
from pathlib import Path

import httpx
import onnxruntime as ort


def _fetch(src: str) -> Path:
    if not src.startswith("http"):
        return Path(src)
    dest = Path(tempfile.mkdtemp()) / src.rsplit("/", 1)[-1]
    with httpx.stream("GET", src, follow_redirects=True, timeout=120.0) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return dest


def main() -> None:
    path = _fetch(sys.argv[1])
    print(f"file: {path.name}")
    print(f"size_mb: {path.stat().st_size / 1e6:.2f}")
    print(f"sha256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    print("inputs:")
    for t in session.get_inputs():
        print(f"  - {t.name}  shape={t.shape}  dtype={t.type}")
    print("outputs:")
    for t in session.get_outputs():
        print(f"  - {t.name}  shape={t.shape}  dtype={t.type}")


if __name__ == "__main__":
    main()
