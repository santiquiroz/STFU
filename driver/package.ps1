# Empaqueta el driver STFU test-signed para distribucion al usuario.
# Corre en la maquina de DEV (con EWDK montado o Windows Kits instalado). NO
# requiere elevacion: el cert de test se crea en CurrentUser\My y firma desde ahi.
#
# Produce driver/package_out/ con: .sys (firmado), .inf, .cat (firmado),
# STFU-TestCert.cer, devcon.exe, install-driver.ps1, "Instalar STFU.cmd",
# uninstall-driver.ps1. Esa carpeta es lo que el usuario ejecuta (Instalar STFU.cmd).
[CmdletBinding()]
param(
    [string]$Config = "Debug",
    [string]$Platform = "x64",
    [string]$CertName = "STFU Test Cert"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$built = Join-Path $root "Source\Main\$Platform\$Config"
$sys = Join-Path $built "VirtualAudioDriver.sys"
$inf = Join-Path $built "VirtualAudioDriver.inf"
if (-not (Test-Path $sys)) { throw "No existe el .sys compilado: $sys (corre build.ps1 primero)" }

function Find-Tool([string]$name, [string]$archPref) {
    $roots = @("C:\Program Files (x86)\Windows Kits\10\bin", "C:\Program Files\Windows Kits\10\bin")
    Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object { $roots += "$($_.DriveLetter):\Program Files\Windows Kits\10\bin"; $roots += "$($_.DriveLetter):\Program Files\Windows Kits\10\Tools" }
    foreach ($r in $roots) {
        if (Test-Path $r) {
            $hit = Get-ChildItem $r -Recurse -Filter $name -ErrorAction SilentlyContinue |
                   Where-Object { $_.FullName -match "\\$archPref\\" } | Select-Object -First 1
            if (-not $hit) { $hit = Get-ChildItem $r -Recurse -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1 }
            if ($hit) { return $hit.FullName }
        }
    }
    throw "No encontre $name en ningun Windows Kit / EWDK montado."
}

$signtool = Find-Tool "signtool.exe" $Platform
$inf2cat  = Find-Tool "Inf2Cat.exe" "x86"
$devcon   = Find-Tool "devcon.exe" $Platform
Write-Host "signtool: $signtool" -ForegroundColor DarkGray
Write-Host "inf2cat : $inf2cat" -ForegroundColor DarkGray
Write-Host "devcon  : $devcon" -ForegroundColor DarkGray

# 1. Cert de test en CurrentUser\My (idempotente, sin elevacion)
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq "CN=$CertName" } | Select-Object -First 1
if (-not $cert) {
    Write-Host "Creando cert de test '$CertName'..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=$CertName" `
        -CertStoreLocation Cert:\CurrentUser\My -KeyUsage DigitalSignature -HashAlgorithm SHA256 -KeyExportPolicy Exportable
}

# 2. Carpeta de salida limpia con .sys + .inf
$out = Join-Path $root "package_out"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Path $out | Out-Null
Copy-Item $sys $out; Copy-Item $inf $out

# 3. Firmar el .sys embebido (ANTES de catalogar: el .cat hashea el .sys final)
Write-Host "Firmando el .sys..." -ForegroundColor Cyan
& $signtool sign /v /fd sha256 /a /s My /n $CertName /tr http://timestamp.digicert.com /td sha256 (Join-Path $out "VirtualAudioDriver.sys")
if ($LASTEXITCODE -ne 0) { throw "signtool (.sys) fallo" }

# 4. Generar el catalogo
Write-Host "Generando el catalogo..." -ForegroundColor Cyan
& $inf2cat /driver:$out /os:10_X64 /verbose
if ($LASTEXITCODE -ne 0) { throw "Inf2Cat fallo" }

# 5. Firmar el .cat
$cat = Get-ChildItem $out -Filter *.cat | Select-Object -First 1
Write-Host "Firmando el catalogo $($cat.Name)..." -ForegroundColor Cyan
& $signtool sign /v /fd sha256 /a /s My /n $CertName /tr http://timestamp.digicert.com /td sha256 $cat.FullName
if ($LASTEXITCODE -ne 0) { throw "signtool (.cat) fallo" }

# 6. Exportar el .cer publico (lo que el instalador confia)
Export-Certificate -Cert $cert -FilePath (Join-Path $out "STFU-TestCert.cer") | Out-Null

# 7. devcon + scripts del instalador
Copy-Item $devcon (Join-Path $out "devcon.exe")
Copy-Item (Join-Path $root "install-driver.ps1") $out
Copy-Item (Join-Path $root "uninstall-driver.ps1") $out
Copy-Item (Join-Path $root "Instalar STFU.cmd") $out

Write-Host "`nPaquete listo en: $out" -ForegroundColor Green
Get-ChildItem $out | Select-Object Name, Length | Format-Table -AutoSize
Write-Host "El usuario ejecuta 'Instalar STFU.cmd' (UAC una vez)." -ForegroundColor Green
