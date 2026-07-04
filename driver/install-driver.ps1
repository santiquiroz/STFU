# Instalador del driver "STFU Microphone" (test-signed) para el usuario final.
#
# Se AUTO-ELEVA (pide UAC una sola vez). Ejecutar con doble-click sobre
# "Instalar STFU.cmd", o:  powershell -ExecutionPolicy Bypass -File install-driver.ps1
#
# Deja un log completo en install-log.txt (junto al script) para diagnostico.
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
# El proceso elevado deriva la carpeta de su propio $PSScriptRoot (-File), asi
# que no hace falta pasar -PackageDir (el array de -ArgumentList lo mangla en
# PS 5.1). Se pasa como string unico con comillas para robustez.
if (-not (Test-Admin)) {
    Write-Host "Solicitando permisos de administrador (UAC)..." -ForegroundColor Cyan
    $a = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -HardwareId `"$HardwareId`""
    Start-Process powershell -Verb RunAs -ArgumentList $a
    return
}

# El CWD de un proceso elevado es System32; hay que anclar todo al dir del
# script. $PSScriptRoot viene de -File y sobrevive la elevacion (a diferencia de
# un parametro pasado por Start-Process, que puede llegar vacio en PS 5.1).
$base = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($base)) { $base = Split-Path -Parent $MyInvocation.MyCommand.Definition }
if ($PackageDir -and (Test-Path $PackageDir)) { $base = $PackageDir }

$log = Join-Path $base "install-log.txt"
Start-Transcript -Path $log -Force | Out-Null
$transcribing = $true

function Finish([int]$code) {
    Write-Host ""
    Write-Host "Log guardado en: $log" -ForegroundColor DarkGray
    if ($script:transcribing) { try { Stop-Transcript | Out-Null } catch {} }
    Read-Host "Enter para salir"
    exit $code
}

$ErrorActionPreference = "Continue"
Write-Host "=== Instalador STFU Microphone (test-signed) ===" -ForegroundColor Cyan
Write-Host "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  |  Equipo: $env:COMPUTERNAME"
Write-Host "Carpeta del paquete: $base"

# --- Localizar artefactos (por nombre exacto, solo en el paquete) ---
$inf = Get-ChildItem -Path $base -Filter "VirtualAudioDriver.inf" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $inf) { Write-Host "ERROR: no encontre VirtualAudioDriver.inf en $base" -ForegroundColor Red; Finish 1 }
$cer    = Get-ChildItem -Path $base -Filter "*.cer" -ErrorAction SilentlyContinue | Select-Object -First 1
$devcon = Get-ChildItem -Path $base -Filter "devcon.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
Write-Host "INF   : $($inf.FullName)"
Write-Host "CER   : $($cer.FullName)"
Write-Host "devcon: $($devcon.FullName)"

# --- 2. Test-signing ---
$bcd = bcdedit /enum "{current}"
$testsigning = ($bcd | Select-String -Quiet "testsigning\s+Yes")
Write-Host "Test-signing: $(if ($testsigning) { 'ON' } else { 'OFF' })"
if (-not $testsigning) {
    Write-Host "Activando test-signing (necesario para drivers de desarrollo)..." -ForegroundColor Yellow
    bcdedit /set testsigning on
    Write-Host ""
    Write-Host "  >> REINICIA Windows y vuelve a ejecutar este instalador. <<" -ForegroundColor Yellow
    Finish 0
}

# --- 3. Confiar el certificado de test ---
if ($cer) {
    Write-Host "Confiando el certificado de test (Root + TrustedPublisher)..." -ForegroundColor Cyan
    Import-Certificate -FilePath $cer.FullName -CertStoreLocation Cert:\LocalMachine\Root -ErrorAction SilentlyContinue | Out-Null
    Import-Certificate -FilePath $cer.FullName -CertStoreLocation Cert:\LocalMachine\TrustedPublisher -ErrorAction SilentlyContinue | Out-Null
}

# --- 4. Instalar el paquete + crear el dispositivo root ---
Write-Host "Registrando el paquete del driver (pnputil)..." -ForegroundColor Cyan
pnputil /add-driver $inf.FullName /install
Write-Host "pnputil exit code: $LASTEXITCODE"

if ($devcon) {
    Write-Host "Creando el dispositivo virtual (devcon install $HardwareId)..." -ForegroundColor Cyan
    & $devcon.FullName install $inf.FullName $HardwareId
    Write-Host "devcon exit code: $LASTEXITCODE"
}

# --- 5. Verificar ---
Start-Sleep -Seconds 3
Write-Host ""
Write-Host "--- Dispositivos PnP con 'STFU' o 'VirtualAudio' ---"
Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -match "STFU|Virtual Audio" -or $_.InstanceId -match "VirtualAudioDriver" } |
    Format-Table -AutoSize FriendlyName, Status, Class, InstanceId

$eps = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match "STFU" }
if ($eps) {
    Write-Host "OK - dispositivos STFU detectados. Abri el Panel de Sonido: 'STFU Microphone' como microfono." -ForegroundColor Green
} else {
    Write-Host "Driver registrado, pero aun no veo endpoints 'STFU'." -ForegroundColor Yellow
    Write-Host "Revisa el Administrador de dispositivos. Errores de instalacion mas abajo (si los hay):" -ForegroundColor Yellow
    Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne "OK" -and $_.InstanceId -match "VirtualAudioDriver" } |
        Format-Table -AutoSize FriendlyName, Status, Problem, InstanceId
}

Finish 0
