from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vela.core.paths import AppPaths  # noqa: E402


@pytest.fixture()
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(tmp_path / "data")
    result.ensure()
    return result


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT
