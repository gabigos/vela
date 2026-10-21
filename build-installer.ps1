# Builds the Windows installer with Inno Setup 6.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\build-installer.ps1
#   powershell -ExecutionPolicy Bypass -File .\build-installer.ps1 -Verify
#
# The installer is written to dist\installer\Vela-<version>-setup.exe.
# -Verify installs it into a temporary directory, runs --version and
# --smoke-test, then uninstalls it again.

param(
    [switch]$Verify,
    [switch]$SkipAppBuild
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$appExe = Join-Path $PSScriptRoot "dist\Vela\Vela.exe"
$iss = Join-Path $PSScriptRoot "packaging\vela.iss"

if (-not (Test-Path -LiteralPath $appExe)) {
    if ($SkipAppBuild) {
        throw "dist\Vela\Vela.exe was not found. Run build.ps1 first, or omit -SkipAppBuild."
    }
    Write-Host "dist\Vela\Vela.exe was not found. Running build.ps1 first..."
    & (Join-Path $PSScriptRoot "build.ps1")
    if (-not (Test-Path -LiteralPath $appExe)) {
        throw "The application build did not produce dist\Vela\Vela.exe."
    }
}

$initPath = Join-Path $PSScriptRoot "vela\__init__.py"
$initText = Get-Content -LiteralPath $initPath -Raw
if ($initText -notmatch '__version__\s*=\s*"([^"]+)"') {
    throw "Could not read __version__ from vela\__init__.py."
}
$version = $Matches[1]

$isccCandidates = @()
if ($env:ISCC) {
    $isccCandidates += $env:ISCC
}
$isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($isccCommand) {
    $isccCandidates += $isccCommand.Source
}
if ($env:INNO_SETUP_HOME) {
    $isccCandidates += (Join-Path $env:INNO_SETUP_HOME "ISCC.exe")
}
$isccCandidates += (Join-Path $PSScriptRoot "tools\InnoSetup\ISCC.exe")
if ($env:LOCALAPPDATA) {
    $isccCandidates += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
}
if ($env:ProgramFiles) {
    $isccCandidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
}
if (${env:ProgramFiles(x86)}) {
    $isccCandidates += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
}
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $iscc) {
    throw @"
Inno Setup 6 (ISCC.exe) was not found.
Install it with:
  winget install --id JRSoftware.InnoSetup --exact
Or set INNO_SETUP_HOME to the directory containing ISCC.exe.
"@
}

$outputDir = Join-Path $PSScriptRoot "dist\installer"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$setup = Join-Path $outputDir "Vela-$version-setup.exe"

# Compile into a fresh temporary directory first.  Some antivirus products
# hold a lock on a newly created EXE inside the project tree long enough for
# Inno Setup's EndUpdateResource call to fail.  Moving the finished installer
# afterwards avoids that lock and also prevents a half-written output file
# from being mistaken for a valid installer.
$stagingDir = Join-Path $env:TEMP ("vela-installer-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
try {
    Write-Host "Compiling Vela $version installer with $iscc"
    & $iscc /Qp "/DMyAppVersion=$version" "/O$stagingDir" "/FVela-$version-setup" $iss
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
    }

    $stagedSetup = Join-Path $stagingDir "Vela-$version-setup.exe"
    if (-not (Test-Path -LiteralPath $stagedSetup)) {
        throw "The installer was not created: $stagedSetup"
    }
    if (Test-Path -LiteralPath $setup) {
        Remove-Item -LiteralPath $setup -Force
    }
    Move-Item -LiteralPath $stagedSetup -Destination $setup -Force
}
finally {
    if (Test-Path -LiteralPath $stagingDir) {
        Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $setup)) {
    throw "The installer was not created: $setup"
}

$sizeMb = (Get-Item -LiteralPath $setup).Length / 1MB
Write-Host ("Installer created: {0} ({1:N1} MB)" -f $setup, $sizeMb)

$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
$hashFile = "$setup.sha256"
Set-Content -LiteralPath $hashFile -Value "$hash  Vela-$version-setup.exe" -Encoding ASCII
Write-Host "SHA256: $hash"

if (-not $Verify) {
    Write-Host "Run again with -Verify to test installation, smoke test, and uninstallation."
    exit 0
}

$verifyRoot = Join-Path $env:TEMP ("vela-installer-verify-" + [guid]::NewGuid().ToString("N"))
$installDir = Join-Path $verifyRoot "app"
$dataDir = Join-Path $verifyRoot "data"
$installLog = Join-Path $verifyRoot "install.log"
New-Item -ItemType Directory -Force -Path $verifyRoot | Out-Null

$uninstallerFound = $false
$uninstallExitCode = 0

try {
    Write-Host "Installing into a temporary directory..."
    $installArgs = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CURRENTUSER",
        "/NOICONS",
        "/DIR=`"$installDir`"",
        "/LOG=`"$installLog`""
    )
    $install = Start-Process -FilePath $setup -ArgumentList $installArgs -Wait -PassThru
    if ($install.ExitCode -ne 0) {
        throw "Installer exited with code $($install.ExitCode). See $installLog"
    }

    $installedExe = Join-Path $installDir "Vela.exe"
    if (-not (Test-Path -LiteralPath $installedExe)) {
        throw "Installed Vela.exe was not found: $installedExe"
    }

    $versionOut = Join-Path $verifyRoot "version.out.txt"
    $versionErr = Join-Path $verifyRoot "version.err.txt"
    $versionProcess = Start-Process -FilePath $installedExe -ArgumentList "--version" -Wait -PassThru -RedirectStandardOutput $versionOut -RedirectStandardError $versionErr
    if ($versionProcess.ExitCode -ne 0) {
        throw "Installed Vela.exe --version exited with code $($versionProcess.ExitCode)."
    }
    $versionText = Get-Content -LiteralPath $versionOut -Raw -ErrorAction SilentlyContinue
    if ($versionText -notmatch [regex]::Escape("Vela $version")) {
        throw "Unexpected --version output: $versionText"
    }

    $smokeOut = Join-Path $verifyRoot "smoke.out.txt"
    $smokeErr = Join-Path $verifyRoot "smoke.err.txt"
    $smokeArgs = @("--smoke-test", "--data-dir", "`"$dataDir`"")
    $smokeProcess = Start-Process -FilePath $installedExe -ArgumentList $smokeArgs -Wait -PassThru -RedirectStandardOutput $smokeOut -RedirectStandardError $smokeErr
    if ($smokeProcess.ExitCode -ne 0) {
        throw "Installed Vela.exe --smoke-test exited with code $($smokeProcess.ExitCode)."
    }
    $smokeText = Get-Content -LiteralPath $smokeOut -Raw -ErrorAction SilentlyContinue
    if ($smokeText -notmatch "SMOKE OK") {
        throw "Unexpected --smoke-test output: $smokeText"
    }

    Write-Host "Installation, --version, and --smoke-test passed."
}
finally {
    $uninstaller = Join-Path $installDir "unins000.exe"
    if (Test-Path -LiteralPath $uninstaller) {
        $uninstallerFound = $true
        Write-Host "Uninstalling temporary installation..."
        $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
        $uninstallExitCode = $uninstall.ExitCode
    }
    if (Test-Path -LiteralPath $verifyRoot) {
        Remove-Item -LiteralPath $verifyRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not $uninstallerFound) {
    throw "The uninstaller was not found after installation."
}
if ($uninstallExitCode -ne 0) {
    throw "Uninstaller exited with code $uninstallExitCode."
}

Write-Host "Installer verification passed: install, --version, --smoke-test, uninstall."
