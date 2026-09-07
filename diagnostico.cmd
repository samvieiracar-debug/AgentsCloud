@echo off
setlocal DisableDelayedExpansion
set "AGENTSCLOUD_PAUSE=0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\_launcher_console.ps1"
if "%errorlevel%"=="10" set "AGENTSCLOUD_PAUSE=1"
set "AGENTSCLOUD_CMD_WRAPPER=1"
set "AGENTSCLOUD_PYTHON="
for /f "delims=" %%P in ('py -3 -I -c "import sys; print(sys._base_executable)" 2^>nul') do set "AGENTSCLOUD_PYTHON=%%P"
if not defined AGENTSCLOUD_PYTHON for /f "delims=" %%P in ('python -I -c "import sys; print(sys._base_executable)" 2^>nul') do set "AGENTSCLOUD_PYTHON=%%P"
if not defined AGENTSCLOUD_PYTHON goto :missing_python
(
    "%AGENTSCLOUD_PYTHON%" -E -s "%~dp0diagnostico.py" %*
    call set "AGENTSCLOUD_EXIT=%%errorlevel%%"
    setlocal EnableDelayedExpansion
    if "%AGENTSCLOUD_PAUSE%"=="1" pause
    exit /b !AGENTSCLOUD_EXIT!
)
:missing_python
echo Python nao encontrado. Instale Python 3.11 ou superior e disponibilize py ou python no PATH.
echo No Windows com winget: winget install --id Python.Python.3.11 --exact --source winget
echo Depois reabra o terminal e execute diagnostico.cmd novamente. Questionary global nao e necessario.
rem Oferta automatizada somente na abertura interativa sem argumentos. Ajuda/automacao nao instalam.
if not "%~1"=="" goto :missing_done
if not "%AGENTSCLOUD_PAUSE%"=="1" goto :missing_done
where winget >nul 2>nul
if errorlevel 1 goto :missing_done
choice /c SN /n /m "Autoriza instalar Python.Python.3.11 neste computador usando winget? [S/N] "
if errorlevel 2 goto :missing_done
if errorlevel 1 winget install --id Python.Python.3.11 --exact --source winget --disable-interactivity
echo Confira o resultado do gerenciador; a disponibilidade do Python sera verificada na proxima execucao.
:missing_done
if "%AGENTSCLOUD_PAUSE%"=="1" pause
exit /b 1
