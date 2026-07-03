# Compila el driver STFU Microphone con el EWDK. Correr DENTRO del entorno EWDK:
#   1. Montar el EWDK ISO (build 26100).
#   2. En el ISO: LaunchBuildEnv.cmd  (abre un cmd con msbuild + WDK en PATH)
#   3. En ese cmd:  powershell -ExecutionPolicy Bypass -File driver\build.ps1
param([ValidateSet("Debug","Release")] [string]$Config = "Debug", [string]$Platform = "x64")

$ErrorActionPreference = "Stop"
$sln = Join-Path $PSScriptRoot "VirtualAudioDriver.sln"

$msbuild = (Get-Command msbuild -ErrorAction SilentlyContinue).Source
if (-not $msbuild) {
    throw "msbuild no está en PATH. Abre el entorno del EWDK con LaunchBuildEnv.cmd y reintenta."
}

Write-Host "Compilando $sln ($Config|$Platform) con EWDK..." -ForegroundColor Cyan
& $msbuild $sln /p:Configuration=$Config /p:Platform=$Platform /m /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw "build falló ($LASTEXITCODE)" }

# El paquete (.sys + .inf + .cat) queda bajo Package\$Platform\$Config o Source\...\$Platform\$Config
$out = Get-ChildItem -Path $PSScriptRoot -Recurse -Include *.sys,*.inf,*.cat -ErrorAction SilentlyContinue |
       Where-Object { $_.FullName -match "\\$Platform\\$Config\\" }
Write-Host "`nArtefactos:" -ForegroundColor Green
$out | ForEach-Object { "  $($_.FullName)" }
