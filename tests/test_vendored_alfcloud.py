"""The integration ships a vendored copy of alfcloud; it must not drift from the source.

README: "kopiera om efter ändringar". All alfcloud tests run against the top-level
package, so a stale vendored copy would ship untested code to Home Assistant.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "alfcloud"
_VENDORED = _ROOT / "custom_components" / "alf" / "alfcloud"


def _modules(directory: Path) -> set[str]:
    return {p.name for p in directory.glob("*.py")}


def test_vendored_copy_has_same_modules():
    assert _modules(_VENDORED) == _modules(_SRC)


@pytest.mark.parametrize("name", sorted(_modules(_SRC)))
def test_vendored_module_matches_source(name):
    src = (_SRC / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    vendored = (_VENDORED / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert vendored == src, f"custom_components/alf/alfcloud/{name} is out of sync"
