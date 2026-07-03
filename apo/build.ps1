# Compila stfu_apo.dll con MSVC (Build Tools). Salida: apo/build/stfu_apo.dll
param([switch]$Debug, [switch]$TestHarness)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$out = Join-Path $root "build"
New-Item -ItemType Directory -Force $out | Out-Null

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "MSVC Build Tools no encontrados" }
$devcmd = Join-Path $vsPath "Common7\Tools\VsDevCmd.bat"

$flags = if ($Debug) { "/Od /Zi /MDd" } else { "/O2 /MD" }

cmd /c "cd /d `"$root`" && `"$devcmd`" -arch=amd64 -no_logo && cl /nologo /std:c++17 /W4 /EHsc $flags /LD src\dllmain.cpp src\stfu_apo.cpp src\pipe_worker.cpp /Fobuild\ /Febuild\stfu_apo.dll /link /DEF:src\stfu_apo.def ole32.lib advapi32.lib uuid.lib"
if ($LASTEXITCODE -ne 0) { throw "build DLL falló ($LASTEXITCODE)" }
Write-Host "OK -> build\stfu_apo.dll"

if ($TestHarness) {
    cmd /c "cd /d `"$root`" && `"$devcmd`" -arch=amd64 -no_logo && cl /nologo /std:c++17 /W4 /EHsc $flags src\test_pipe.cpp src\pipe_worker.cpp /Fobuild\ /Febuild\test_pipe.exe"
    if ($LASTEXITCODE -ne 0) { throw "build harness falló ($LASTEXITCODE)" }
    Write-Host "OK -> build\test_pipe.exe"
}
