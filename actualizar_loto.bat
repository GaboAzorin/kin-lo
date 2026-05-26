@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\actualizar_loto.ps1"
pause
