# Compila stfu_apo.dll con MSVC (Build Tools). Salida: apo/build/stfu_apo.dll
param([switch]$Debug)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$out = Join-Path $root "build"
New-Item -ItemType Directory -Force $out | Out-Null

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "MSVC Build Tools no encontrados" }

$flags = if ($Debug) { "/Od /Zi /MDd" } else { "/O2 /MD" }
$cmd = @(
    "`"$vsPath\Common7\Tools\VsDevCmd.bat`" -arch=amd64 -no_logo",
    "cl /nologo /std:c++17 /W4 /EHsc $flags /LD",
    "`"$root\src\dllmain.cpp`" `"$root\src\stfu_apo.cpp`" `"$root\src\pipe_worker.cpp`"",
    "/Fo`"$out\\`" /Fe`"$out\stfu_apo.dll`"",
    "/link /DEF:`"$root\src\stfu_apo.def`" ole32.lib advapi32.lib uuid.lib"
) -join " "

cmd /c "$cmd"
if ($LASTEXITCODE -ne 0) { throw "build falló ($LASTEXITCODE)" }
Write-Host "OK -> $out\stfu_apo.dll"
