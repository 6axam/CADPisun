from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from handwriting_plotter.application.service import GenerationRequest, HandwritingPlotterService
from handwriting_plotter.cli import main
from handwriting_plotter.domain.errors import ExitCode
from handwriting_plotter.storage.files import publish_bundle


SAMPLE = "Україна — це Європа. Ґрунт, підʼїзд, її зошит.\nEnglish 123."


def test_t_a02_full_test_style_bundle_and_cli(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    output = tmp_path / "bundle"
    source.write_text(SAMPLE, encoding="utf-8")
    assert main(["generate", str(source), str(output), "--seed", "42", "--realism", "0"]) == 0
    expected = {
        "input.txt", "request.json", "style-manifest.json", "page-0001.plan.json",
        "page-0001.motion.json", "page-0001.svg", "page-0001.preview.svg",
        "page-0001.gcode", "report.json", "job-manifest.json",
    }
    assert expected == {item.name for item in output.iterdir()}
    report = json.loads((output / "report.json").read_text())
    assert report["complete"] and report["machine"]["simulation_only"]
    assert report["style"]["test_only"] and not report["style"]["production_eligible"]
    assert report["pages"][0]["gcode_roundtrip_passed"]


def test_t_a03_unknown_final_glyph_publishes_nothing(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match="MISSING_GLYPH"):
        HandwritingPlotterService().generate(SAMPLE + "🙂", output, GenerationRequest())
    assert not output.exists()


def test_t_a04_same_inputs_are_byte_identical(tmp_path: Path) -> None:
    service = HandwritingPlotterService()
    first = service.generate(SAMPLE, tmp_path / "one", GenerationRequest(seed=77, realism=0))
    second = service.generate(SAMPLE, tmp_path / "two", GenerationRequest(seed=77, realism=0))
    assert first.files.keys() == second.files.keys()
    assert all(first.files[name] == second.files[name] for name in first.files)


@pytest.mark.parametrize("seed", [-1, 2**64])
def test_generation_request_rejects_seed_outside_unsigned_64_bit(seed: int) -> None:
    with pytest.raises(ValueError, match="unsigned 64-bit"):
        GenerationRequest(seed=seed)


def test_cli_distinguishes_input_resource_and_io_failures(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.txt"
    assert main(["simulate", str(missing)]) == ExitCode.IO_ERROR
    assert json.loads(capsys.readouterr().err)["error"] == "IO_ERROR"

    invalid_utf8 = tmp_path / "invalid.txt"
    invalid_utf8.write_bytes(b"\xff")
    assert main(["simulate", str(invalid_utf8)]) == ExitCode.INVALID_INPUT
    assert json.loads(capsys.readouterr().err)["error"] == "UnicodeDecodeError"

    unsupported = tmp_path / "unsupported.txt"
    unsupported.write_text("🙂", encoding="utf-8")
    assert main(["inspect", str(unsupported)]) == ExitCode.INVALID_INPUT
    assert json.loads(capsys.readouterr().out)["passed"] is False

    oversized = tmp_path / "oversized.txt"
    oversized.write_text("a" * (1024 * 1024 + 1), encoding="utf-8")
    assert main(["simulate", str(oversized)]) == ExitCode.RESOURCE_LIMIT
    assert json.loads(capsys.readouterr().err)["message"].startswith("RESOURCE_LIMIT")


def test_atomic_publish_preserves_existing_bundle_on_failure(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "bundle"
    target.mkdir()
    (target / "old.txt").write_text("preserve", encoding="utf-8")
    original_fsync = os.fsync
    sync_count = 0

    def fail(descriptor: int) -> None:
        nonlocal sync_count
        sync_count += 1
        if sync_count == 2:
            raise OSError("simulated disk full")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="disk full"):
        publish_bundle(target, {"first.txt": b"ok", "second.txt": b"fail"}, overwrite=True)
    assert (target / "old.txt").read_text() == "preserve"


def test_style_validate_and_inspect_commands(tmp_path: Path, capsys) -> None:
    source = tmp_path / "input.txt"
    source.write_text("Україна", encoding="utf-8")
    assert main(["inspect", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["passed"]
    style = Path(__file__).parents[2] / "assets" / "styles" / "test-technical-v1" / "1.0.0"
    assert main(["styles", "validate", str(style)]) == 0
    assert json.loads(capsys.readouterr().out)["test_only"]


def test_test_style_has_exact_required_character_families() -> None:
    snapshot = HandwritingPlotterService().load_style(GenerationRequest())
    ua = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
    ru = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    latin = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ascii_punctuation = "".join(
        chr(value)
        for value in (*range(0x21, 0x30), *range(0x3A, 0x41), *range(0x5B, 0x61), *range(0x7B, 0x7F))
    )
    special = "«»“”‘’ʼ–—…№°±×÷≤≥→₴€"
    required = set(
        ua + ua.lower() + ru + ru.lower() + latin + latin.lower()
        + "0123456789" + ascii_punctuation + special
    )
    assert required <= set(snapshot.variants_by_key)

