# Desinstala el driver "STFU Microphone". Se AUTO-ELEVA (UAC una vez).
# El driver es totalmente reversible: esto borra el dispositivo y el paquete.
[CmdletBinding()]
param([string]$HardwareId = "ROOT\VirtualAudioDriver")

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -HardwareId `"$HardwareId`""
    return
}

$ErrorActionPreference = "Continue"
Write-Host "=== Desinstalador STFU Microphone ===" -ForegroundColor Cyan

# 1. Quitar el dispositivo con devcon si está disponible
$devcon = Get-ChildItem -Path $PSScriptRoot -Recurse -Filter devcon.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($devcon) {
    Write-Host "Quitando el dispositivo virtual..." -ForegroundColor Cyan
    & $devcon.FullName remove $HardwareId
}

# 2. Borrar todos los paquetes de driver STFU/VirtualAudioDriver del DriverStore
Write-Host "Borrando el paquete del driver del DriverStore..." -ForegroundColor Cyan
$drivers = pnputil /enum-drivers
$current = $null
foreach ($line in $drivers) {
    if ($line -match "Published Name\s*:\s*(oem\d+\.inf)") { $current = $Matches[1] }
    if ($line -match "Original Name\s*:\s*(.*\.inf)" -and $current) {
        if ($Matches[1] -match "VirtualAudioDriver|stfu") {
            Write-Host "  eliminando $current ($($Matches[1]))" -ForegroundColor DarkGray
            pnputil /delete-driver $current /uninstall /force | Out-Null
        }
        $current = $null
    }
}

Write-Host "`nListo. El audio del sistema vuelve a su estado normal." -ForegroundColor Green
Read-Host "Enter para salir"
