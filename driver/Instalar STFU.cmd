@echo off
REM Doble-click para instalar el driver STFU Microphone. Pide UAC una vez.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-driver.ps1"
