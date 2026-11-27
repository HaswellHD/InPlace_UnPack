# Builds dist\Inplace-Unpack.exe (GUI) and dist\inplace-unpack-cli.exe (command line).
# Usage:  .\build.ps1 [-Python C:\path\to\venv\Scripts\python.exe] [-SkipTests]
# Needs:  pip install -r requirements-dev.txt
# If Inno Setup 6 is installed, it also builds dist\Inplace-Unpack-Setup.exe.
param([string]$Python = "python", [switch]$SkipTests)

# PyInstaller logs to stderr; with "Stop" Windows PowerShell 5.1 would treat that as an error.
# Failures are detected through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$work = Join-Path $env:TEMP "inplace-unpack-build"

if (-not $SkipTests) {
    & $Python -m pytest tests -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }
}

# A running Inplace-Unpack.exe cannot be replaced - say so instead of a PyInstaller traceback.
foreach ($exe in "dist\Inplace-Unpack.exe", "dist\inplace-unpack-cli.exe") {
    if (Test-Path $exe) {
        try { [IO.File]::Open($exe, 'Open', 'ReadWrite', 'None').Close() }
        catch { throw "$exe is running or locked. Close Inplace-Unpack (use 'Pause' first if it is extracting) and run the build again." }
    }
}

$icon = Join-Path $PSScriptRoot "assets\icon.ico"
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name Inplace-Unpack `
    --icon $icon --add-data "$icon;assets" `
    --workpath $work --specpath $work --distpath dist app_gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (GUI) failed" }

& $Python -m PyInstaller --noconfirm --onefile --console --name inplace-unpack-cli `
    --icon $icon --exclude-module tkinter --workpath $work --specpath $work --distpath dist app_cli.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (CLI) failed" }

# Optional code signing (see docs/Signing.md). Nothing is signed unless one of these is set:
#   $env:SIGN_CERT_THUMBPRINT  certificate in the Windows certificate store (incl. USB token / smart card)
#   $env:SIGN_PFX + $env:SIGN_PFX_PASSWORD  certificate file
#   $env:SIGN_COMMAND  any other signing command; {file} is replaced by the file to sign
function Invoke-Sign([string]$file) {
    $ts = "http://timestamp.digicert.com"
    if ($env:SIGN_COMMAND) {
        $cmd = $env:SIGN_COMMAND.Replace("{file}", "`"$file`"")
        cmd /c $cmd
    } elseif ($env:SIGN_CERT_THUMBPRINT -or $env:SIGN_PFX) {
        $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if (-not $signtool) { throw "signtool.exe not found - install the Windows SDK (Signing Tools)." }
        if ($env:SIGN_CERT_THUMBPRINT) {
            & $signtool.FullName sign /sha1 $env:SIGN_CERT_THUMBPRINT /fd sha256 /tr $ts /td sha256 /d "Inplace-Unpack" $file
        } else {
            & $signtool.FullName sign /f $env:SIGN_PFX /p $env:SIGN_PFX_PASSWORD /fd sha256 /tr $ts /td sha256 /d "Inplace-Unpack" $file
        }
    } else {
        return
    }
    if ($LASTEXITCODE -ne 0) { throw "Signing failed: $file" }
    Write-Host "Signed: $file"
}
Invoke-Sign "dist\Inplace-Unpack.exe"
Invoke-Sign "dist\inplace-unpack-cli.exe"

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc installer.iss
    if (Test-Path "dist\Inplace-Unpack-Setup.exe") { Invoke-Sign "dist\Inplace-Unpack-Setup.exe" }
} else {
    Write-Host "Inno Setup 6 not found - skipping the installer (the .exe files work on their own)."
}
Get-ChildItem dist -File | Select-Object Name, @{n="MB"; e={[math]::Round($_.Length / 1MB, 1)}}
