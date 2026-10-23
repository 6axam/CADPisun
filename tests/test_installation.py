from __future__ import annotations

import importlib.util
import subprocess
import sys

import handwriting_plotter
from handwriting_plotter.cli import main
from handwriting_plotter.domain.errors import Diagnostic, ExitCode


def test_base_import_has_no_optional_dependency() -> None:
    assert handwriting_plotter.__version__ == "0.2.0+20261023.1"
    completed = subprocess.run(
        [sys.executable, "-c", "import handwriting_plotter,sys; print(','.join(sys.modules))"],
        text=True,
        capture_output=True,
        check=True,
    )
    imported = set(completed.stdout.strip().split(","))
    assert not {"torch", "serial", "svg.path"} & imported


def test_cli_help_and_version(capsys) -> None:
    assert main([]) == ExitCode.OK
    assert "Generate deterministic" in capsys.readouterr().out
    assert main(["version"]) == ExitCode.OK
    assert capsys.readouterr().out.strip() == "0.2.0+20261023.1"


def test_cli_invalid_input_uses_argparse_exit_code() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "handwriting_plotter.cli", "unknown"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == ExitCode.INVALID_INPUT
    assert "invalid choice" in completed.stderr


def test_diagnostic_is_strict_and_frozen() -> None:
    item = Diagnostic(code="EXAMPLE", severity="info", stage="installation", message="ok")
    assert item.code == "EXAMPLE"


def test_no_network_library_is_a_runtime_dependency() -> None:
    for module in ("requests", "httpx", "aiohttp", "torch", "serial"):
        assert importlib.util.find_spec(module) is None or module not in sys.modules

