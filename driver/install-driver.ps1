# Instalador del driver "STFU Microphone" (test-signed) para el usuario final.
#
# Se AUTO-ELEVA (pide UAC una sola vez). Ejecutar con doble-click sobre
# "Instalar STFU.cmd", o:  powershell -ExecutionPolicy Bypass -File install-driver.ps1
#
# Que hace, ya elevado:
#   1. Verifica test-signing (lo activa y pide reinicio si esta OFF).
#   2. Confia el certificado de test (Root + TrustedPublisher).
#   3. Instala el paquete del driver en el DriverStore (pnputil).
#   4. Crea el dispositivo root-enumerated (devcon) - es un mic virtual sin hardware.
#   5. Verifica que aparezcan los endpoints "STFU Microphone" / "STFU Audio Bridge".
#
# El .sys ya viene firmado (test cert); esta maquina NO necesita EWDK ni signtool.
[CmdletBinding()]
param(
    [string]$PackageDir = $PSScriptRoot,
    [string]$HardwareId = "ROOT\VirtualAudioDriver"
)

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --- 1. Auto-elevacion (UAC una vez) ---
if (-not (Test-Admin)) {
    Write-Host "Solicitando permisos de administrador (UAC)..." -ForegroundColor Cyan
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
        "-PackageDir", $PackageDir, "-HardwareId", $HardwareId
    )
    return
}

$ErrorActionPreference = "Stop"
Write-Host "=== Instalador STFU Microphone (test-signed) ===" -ForegroundColor Cyan

# --- Localizar artefactos ---
$inf = Get-ChildItem -Path $PackageDir -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $inf) { Write-Host "ERROR: no encontre el .inf en $PackageDir" -ForegroundColor Red; Read-Host "Enter para salir"; exit 1 }
$cer    = Get-ChildItem -Path $PackageDir -Recurse -Filter *.cer -ErrorAction SilentlyContinue | Select-Object -First 1
$devcon = Get-ChildItem -Path $PackageDir -Recurse -Filter devcon.exe -ErrorAction SilentlyContinue | Select-Object -First 1

# --- 2. Test-signing ---
$testsigning = (bcdedit /enum "{current}" | Select-String -Quiet "testsigning\s+Yes")
if (-not $testsigning) {
    Write-Host "Test-signing esta OFF. Activandolo (necesario para drivers de desarrollo)..." -ForegroundColor Yellow
    bcdedit /set testsigning on | Out-Null
    Write-Host ""
    Write-Host "  >> REINICIA Windows y vuelve a ejecutar este instalador. <<" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Enter para salir"; exit 0
}

# --- 3. Confiar el certificado de test ---
if ($cer) {
    Write-Host "Confiando el certificado de test..." -ForegroundColor Cyan
    Import-Certificate -FilePath $cer.FullName -CertStoreLocation Cert:\LocalMachine\Root -ErrorAction SilentlyContinue | Out-Null
    Import-Certificate -FilePath $cer.FullName -CertStoreLocation Cert:\LocalMachine\TrustedPublisher -ErrorAction SilentlyContinue | Out-Null
}

# --- 4. Instalar el paquete + crear el dispositivo root ---
Write-Host "Registrando el paquete del driver..." -ForegroundColor Cyan
pnputil /add-driver $inf.FullName /install

if ($devcon) {
    Write-Host "Creando el dispositivo virtual (devcon)..." -ForegroundColor Cyan
    & $devcon.FullName install $inf.FullName $HardwareId
} else {
    Write-Host "AVISO: devcon.exe no esta en el paquete; intento con pnputil." -ForegroundColor Yellow
    Write-Host "Si los endpoints no aparecen, usa 'Agregar hardware heredado' en el Administrador de dispositivos." -ForegroundColor Yellow
}

# --- 5. Verificar ---
Start-Sleep -Seconds 2
$eps = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match "STFU" }
Write-Host ""
if ($eps) {
    Write-Host "OK - dispositivos STFU detectados:" -ForegroundColor Green
    $eps | ForEach-Object { Write-Host ("   " + $_.FriendlyName + "  [" + $_.Status + "]") }
    Write-Host "Abre el Panel de Sonido: 'STFU Microphone' deberia estar disponible como microfono." -ForegroundColor Green
} else {
    Write-Host "Driver instalado, pero aun no veo endpoints 'STFU'." -ForegroundColor Yellow
    Write-Host "Revisa el Administrador de dispositivos / Panel de Sonido." -ForegroundColor Yellow
    Write-Host "Si no aparece, usa 'Accion > Agregar hardware heredado' y elige el driver STFU." -ForegroundColor Yellow
}
Read-Host "Enter para salir"
