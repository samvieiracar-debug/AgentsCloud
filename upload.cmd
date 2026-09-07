@echo off
setlocal DisableDelayedExpansion
set "AGENTSCLOUD_PAUSE=0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\_launcher_console.ps1"
if "%errorlevel%"=="10" set "AGENTSCLOUD_PAUSE=1"
set "AGENTSCLOUD_CMD_WRAPPER=1"
if not exist "%~dp0.venv\Scripts\python.exe" goto missing_environment
"%~dp0.venv\Scripts\python.exe" "%~dp0upload.py" %*
set "AGENTSCLOUD_EXIT=%errorlevel%"
goto finish
:missing_environment
echo Nao foi encontrado o Python da .venv deste projeto.
echo Abra um terminal na pasta do AgentsCloud e execute: uv sync --locked
echo Se uv nao estiver instalado, siga a preparacao descrita no README.md.
set "AGENTSCLOUD_EXIT=1"
:finish
if "%AGENTSCLOUD_PAUSE%"=="1" pause
exit /b %AGENTSCLOUD_EXIT%
