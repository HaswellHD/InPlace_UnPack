@echo off
rem Double-click to build dist\Inplace-Unpack.exe and dist\inplace-unpack-cli.exe.
rem First run: creates a private Python environment (.venv) and installs the build tools.
rem Options are passed on to build.ps1, e.g.:  build.cmd -SkipTests
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3.11 or newer is needed to build. Get it from https://www.python.org/downloads/
    echo ^(tick "Add python.exe to PATH" during setup^), then run build.cmd again.
    goto :end
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the build environment .venv ...
    %PY% -m venv .venv || goto :fail
)
echo Installing / updating build tools ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-dev.txt || goto :fail

rem -ExecutionPolicy Bypass applies to this one PowerShell process only; system settings are not changed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" -Python "%~dp0.venv\Scripts\python.exe" %*
if errorlevel 1 goto :fail
echo.
echo Done. The programs are in the "dist" folder.
goto :end

:fail
echo.
echo Build FAILED - see the messages above.

:end
echo.
pause
