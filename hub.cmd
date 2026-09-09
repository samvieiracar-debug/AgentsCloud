@echo off
setlocal DisableDelayedExpansion
set "AGENTSCLOUD_PAUSE=0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\_launcher_console.ps1"
if "%errorlevel%"=="10" set "AGENTSCLOUD_PAUSE=1"
set "AGENTSCLOUD_CMD_WRAPPER=1"
set "AGENTSCLOUD_PYTHON="
for /f "delims=" %%P in ('py -3 -I -c "import sys; print(sys._base_executable)" 2^>nul') do set "AGENTSCLOUD_PYTHON=%%P"
if not defined AGENTSCLOUD_PYTHON for /f "delims=" %%P in ('python -I -c "import sys; print(sys._base_executable)" 2^>nul') do set "AGENTSCLOUD_PYTHON=%%P"
if not defined AGENTSCLOUD_PYTHON (
    echo Python nao encontrado. Instale Python 3.11 ou superior e disponibilize py ou python no PATH.
    echo Execute diagnostico.cmd para obter orientacoes.
    if "%AGENTSCLOUD_PAUSE%"=="1" pause
    exit /b 1
)
(
    "%AGENTSCLOUD_PYTHON%" -E -s "%~dp0hub.py" %*
    call set "AGENTSCLOUD_EXIT=%%errorlevel%%"
    setlocal EnableDelayedExpansion
    if "%AGENTSCLOUD_PAUSE%"=="1" pause
    exit /b !AGENTSCLOUD_EXIT!
)
