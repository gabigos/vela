# Builds dist\Vela\Vela.exe with PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File .\build.ps1

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "仮想環境が見つかりません。先に python -m venv .venv と pip install -r requirements-dev.txt を実行してください。"
}

$ffmpeg = Join-Path $PSScriptRoot "tools\ffmpeg\bin\ffmpeg.exe"
$ffprobe = Join-Path $PSScriptRoot "tools\ffmpeg\bin\ffprobe.exe"
if (-not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) {
    throw "tools\ffmpeg\bin に ffmpeg.exe と ffprobe.exe が必要です。"
}

& $python -c "import PyInstaller, PySide6, yt_dlp" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller / PySide6 / yt-dlp が仮想環境にありません。pip install -r requirements-dev.txt を実行してください。"
}

& $python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "アイコンの生成に失敗しました。" }

& $python -m PyInstaller --noconfirm --clean Vela.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller のビルドに失敗しました。" }

$exe = Join-Path $PSScriptRoot "dist\Vela\Vela.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "ビルド成果物が見つかりません: $exe" }

Write-Host ""
Write-Host "ビルドが完了しました: $exe"
Write-Host "確認: dist\Vela\Vela.exe --smoke-test"
