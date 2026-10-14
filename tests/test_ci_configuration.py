from __future__ import annotations

from pathlib import Path


def test_ci_runs_locked_headless_tests_on_linux_and_windows() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert 'python-version: "3.12.12"' in workflow
    assert "QT_QPA_PLATFORM: offscreen" in workflow
    assert "uv sync --locked --python 3.12.12 --extra dev --extra import-svg --extra gui-dev" in workflow
    assert "if: runner.os == 'Linux'" in workflow
    assert "libegl1" in workflow
    assert "uv run pytest -q" in workflow
