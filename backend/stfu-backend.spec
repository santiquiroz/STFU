# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs

datas = []
binaries = []
# La DLL del APO viaja junto a stfu-backend.exe; register.py la localiza ahí
_apo_dll = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "..", "apo", "build", "stfu_apo.dll")
if os.path.exists(_apo_dll):
    binaries += [(_apo_dll, ".")]
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on']
datas += collect_data_files('_sounddevice_data')
binaries += collect_dynamic_libs('soxr')
binaries += collect_dynamic_libs('samplerate')
# Los manifests curados del hub deben viajar en el binario (lineup ONNX)
datas += [("stfu/hub/curated", "stfu/hub/curated")]
# Los presets curados (Gaming/Reunión/Streaming/Podcast/Música/Accesibilidad)
datas += [("stfu/presets/curated", "stfu/presets/curated")]
# DFN3 (torch/df) es extra opcional legacy — se excluye del instalador ONNX


a = Analysis(
    ['run_backend.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchaudio", "df", "deepfilternet"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='stfu-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='stfu-backend',
)
