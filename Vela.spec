# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows one-folder build.

Run ``build.ps1`` (recommended) or::

    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean Vela.spec

The bundled FFmpeg binaries are copied into ``_internal/tools/ffmpeg/bin`` and
discovered at runtime through ``resource_root()``.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)
FFMPEG_DIR = ROOT / "tools" / "ffmpeg" / "bin"

binaries = [
    (str(FFMPEG_DIR / "ffmpeg.exe"), "tools/ffmpeg/bin"),
    (str(FFMPEG_DIR / "ffprobe.exe"), "tools/ffmpeg/bin"),
]
datas = [
    (str(ROOT / "assets" / "app.ico"), "assets"),
    (str(ROOT / "assets" / "app.png"), "assets"),
]
hiddenimports = collect_submodules("yt_dlp")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vela",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Vela",
)
