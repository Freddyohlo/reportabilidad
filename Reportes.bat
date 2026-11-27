@echo off
setlocal
title Reportes STG / CCU
cd /d "%~dp0"

rem --- buscar Python ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo   No encontre Python en este equipo.
  echo.
  echo   Instalalo desde https://www.python.org/downloads/
  echo   Importante: marca la casilla "Add python.exe to PATH" al instalar.
  echo.
  pause
  exit /b 1
)

echo   Iniciando el generador de reportes...
echo.
%PY% app.py

echo.
echo   El servidor se detuvo. Puedes cerrar esta ventana.
pause
