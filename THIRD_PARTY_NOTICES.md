# Third-Party Notices

Vela itself is licensed under the MIT License. See [LICENSE](LICENSE).

Vela uses or bundles the following third-party components. This file is a
summary, not legal advice. Refer to each project's license for the exact terms.

## Runtime dependencies

| Component | License | Project |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | https://github.com/yt-dlp/yt-dlp |
| [FFmpeg](https://ffmpeg.org/) | GPL v3 for the gyan.dev essentials build used by this project | https://www.gyan.dev/ffmpeg/builds/ |
| [Qt for Python / PySide6](https://doc.qt.io/qtforpython/) | LGPL v3 | https://www.qt.io/qt-licensing |
| [Python](https://www.python.org/) | PSF License | https://docs.python.org/3/license.html |

FFmpeg is **not** committed to this repository. The build scripts expect a
local copy under `tools/ffmpeg/bin/`. The installer created by
`build-installer.ps1` can bundle that local copy; if you distribute such an
installer, review FFmpeg's GPL requirements, including source-code availability.

## Build and development tools

| Component | License | Project |
| --- | --- | --- |
| [PyInstaller](https://pyinstaller.org/) | GPL 2.0 with bootloader exception | https://pyinstaller.org/en/stable/license.html |
| [Pillow](https://python-pillow.org/) | HPND | https://python-pillow.org/ |
| [pytest](https://pytest.org/) | MIT | https://github.com/pytest-dev/pytest |
| [pytest-qt](https://pytest-qt.readthedocs.io/) | MIT | https://github.com/pytest-dev/pytest-qt |
| [Ruff](https://docs.astral.sh/ruff/) | MIT | https://github.com/astral-sh/ruff |
| [setuptools](https://setuptools.pypa.io/) | MIT | https://github.com/pypa/setuptools |

## Media and trademarks

The screenshots in `tools/screenshots/` show the Vela UI. Product names,
trademarks, and service names referenced by the application belong to their
respective owners. Vela is not affiliated with YouTube or any other supported
site.
