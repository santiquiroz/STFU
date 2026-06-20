#Requires -RunAsAdministrator
param([switch]$SkipVBCable)

Write-Host "STFU Setup" -ForegroundColor Cyan

$dataDir = "$env:APPDATA\stfu"
New-Item -ItemType Directory -Force -Path "$dataDir\models" | Out-Null
New-Item -ItemType Directory -Force -Path "$dataDir\plugins" | Out-Null
Write-Host "✓ Directorio de datos: $dataDir"

if (-not (Test-Path "backend\.venv")) {
    python -m venv backend\.venv
}
& "backend\.venv\Scripts\pip.exe" install -r backend\requirements.txt -q
Write-Host "✓ Dependencias Python instaladas"

if (-not $SkipVBCable) {
    $devices = Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue
    $hasVBCable = $devices | Where-Object { $_.FriendlyName -like "*CABLE*" }
    if (-not $hasVBCable) {
        Write-Host "VB-Cable no detectado — descargando..." -ForegroundColor Yellow
        $zip = "$env:TEMP\vbcable.zip"
        Invoke-WebRequest "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip" -OutFile $zip
        Expand-Archive $zip "$env:TEMP\vbcable" -Force
        Start-Process "$env:TEMP\vbcable\VBCABLE_Setup_x64.exe" -ArgumentList "/S" -Wait
        Write-Host "✓ VB-Cable instalado (puede requerir reinicio)"
    } else {
        Write-Host "✓ VB-Cable ya instalado"
    }
}

Write-Host "`n✓ Setup completo." -ForegroundColor Green
Write-Host "Iniciar STFU:"
Write-Host "  cd backend && .venv\Scripts\uvicorn stfu.main:app --port 8765"
