# test-sign + instalar el driver para DESARROLLO. Correr como ADMINISTRADOR.
# Requisitos previos (una vez por máquina de dev):
#   - Secure Boot OFF (BIOS).
#   - bcdedit /set testsigning on   (y reiniciar)
# Uso:  powershell -ExecutionPolicy Bypass -File driver\install-test.ps1 -InfPath <ruta al .inf compilado>
param(
    [Parameter(Mandatory = $true)] [string]$InfPath,
    [string]$CertName = "STFU Test Cert",
    [string]$SysPath  # opcional; si se omite, se busca el .sys junto al .inf
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $InfPath)) { throw "No existe el INF: $InfPath" }
if (-not $SysPath) { $SysPath = (Get-ChildItem (Split-Path $InfPath) -Filter *.sys | Select-Object -First 1).FullName }
if (-not $SysPath -or -not (Test-Path $SysPath)) { throw "No encontré el .sys (pasa -SysPath)" }

# 1. Cert de test self-signed en el store de la máquina (idempotente)
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Subject -eq "CN=$CertName" } | Select-Object -First 1
if (-not $cert) {
    Write-Host "Creando cert de test '$CertName'..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=$CertName" `
        -CertStoreLocation Cert:\LocalMachine\My -KeyUsage DigitalSignature -HashAlgorithm SHA256
    # Confiar el cert (Root + TrustedPublisher) para que el driver test-signed cargue
    $store = Get-Item "Cert:\LocalMachine\My\$($cert.Thumbprint)"
    foreach ($s in "Root", "TrustedPublisher") {
        $o = New-Object System.Security.Cryptography.X509Certificates.X509Store($s, "LocalMachine")
        $o.Open("ReadWrite"); $o.Add($store); $o.Close()
    }
}

# 2. Firmar el .sys con signtool (del WDK/EWDK)
$signtool = (Get-Command signtool -ErrorAction SilentlyContinue).Source
if (-not $signtool) { throw "signtool no está en PATH (abre entorno EWDK o agrega Windows Kits\10\bin\...\x64)" }
Write-Host "Firmando $SysPath..." -ForegroundColor Cyan
& $signtool sign /v /fd SHA256 /a /s My /n $CertName /tr http://timestamp.digicert.com /td SHA256 $SysPath
if ($LASTEXITCODE -ne 0) { throw "signtool falló" }

# 3. Instalar el driver
Write-Host "Instalando via pnputil..." -ForegroundColor Cyan
pnputil /add-driver $InfPath /install
Write-Host "`nListo. Revisa Panel de Sonido: deberían aparecer 'STFU Microphone' y 'STFU Audio Bridge'." -ForegroundColor Green
Write-Host "Si no cargó: confirma 'bcdedit' muestra testsigning Yes y Secure Boot OFF."
