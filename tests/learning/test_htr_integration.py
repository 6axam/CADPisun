from __future__ import annotations

import json
import sys
import time
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from handwriting_plotter.learning.htr import (
    HtrCancelled,
    HtrProcessClient,
    HtrProcessError,
    HtrResultRepository,
    HtrRuntime,
    make_htr_request,
    new_htr_run,
)


def _request(*, timeout_seconds: int = 5):
    crop = b"synthetic line crop"
    return make_htr_request(
        "crnn-rukopys", (("line-1", sha256(crop).hexdigest(), crop),),
        timeout_seconds=timeout_seconds, memory_limit_bytes=512 * 1024 * 1024,
    )


def _fake_worker(path: Path, mode: str = "success") -> None:
    body = {
        "success": """
import json, sys
request = json.loads(sys.stdin.readline())
assert "transcript" not in json.dumps(request, ensure_ascii=False)
line = request["lines"][0]
print(json.dumps({"event": "progress", "completed": 1, "total": 1, "stage": "recognizing"}), flush=True)
print(json.dumps({"event": "complete", "model_revision": "test-revision", "model_sha256": "b" * 64, "lines": [{"line_id": line["line_id"], "crop_sha256": line["crop_sha256"], "text": "їжак", "elapsed_ms": 2.5, "confidence": None}]}), flush=True)
""",
        "sleep": """
import json, time, sys
json.loads(sys.stdin.readline())
time.sleep(5)
""",
        "crash": "raise SystemExit(9)\n",
    }[mode]
    path.write_text(body, encoding="utf-8")


def _client(tmp_path: Path, script: Path, *, timeout_seconds: int = 5) -> HtrProcessClient:
    runtime = HtrRuntime(
        python_executable=Path(sys.executable), model_root=tmp_path,
        timeout_seconds=timeout_seconds, memory_limit_bytes=512 * 1024 * 1024,
    )
    return HtrProcessClient(runtime, worker_script=script)


def test_protocol_contains_only_line_pixels_and_rejects_ground_truth_fields() -> None:
    request = _request()
    wire = request.to_wire().decode("utf-8")

    assert "transcript" not in wire and "ground_truth" not in wire
    with pytest.raises(ValidationError, match="extra_forbidden"):
        type(request).model_validate({**request.model_dump(), "ground_truth": "приватний текст"})


def test_isolated_client_reports_unicode_progress_and_persists_provenance(tmp_path: Path) -> None:
    script = tmp_path / "worker.py"
    _fake_worker(script)
    progress: list[tuple[int, int, str]] = []
    request = _request()

    lines, revision, model_hash = _client(tmp_path, script).recognize(
        request, progress=lambda *values: progress.append(values), cancelled=lambda: False,
    )
    run = new_htr_run(
        source_manifest_sha256="c" * 64, original_sha256="d" * 64, frame_id="source-pixels",
        request=request, status="succeeded", lines=lines, model_revision=revision, model_sha256=model_hash,
    )
    stored = HtrResultRepository(tmp_path).store(run)

    assert progress == [(1, 1, "recognizing")]
    assert lines[0].text == "їжак" and lines[0].confidence is None
    assert HtrResultRepository(tmp_path).load(stored.sha256) == stored
    assert HtrResultRepository(tmp_path).list_for_source("c" * 64) == (stored,)


def test_client_timeout_cancellation_and_crash_leave_recoverable_error_boundary(tmp_path: Path) -> None:
    sleeping = tmp_path / "sleep.py"
    _fake_worker(sleeping, "sleep")
    with pytest.raises(HtrProcessError, match="exceeded") as timeout:
        _client(tmp_path, sleeping, timeout_seconds=1).recognize(
            _request(timeout_seconds=1), progress=lambda *_: None, cancelled=lambda: False,
        )
    assert timeout.value.code == "HTR_TIMEOUT"

    script = tmp_path / "success.py"
    _fake_worker(script)
    with pytest.raises(HtrCancelled):
        _client(tmp_path, script).recognize(_request(), progress=lambda *_: None, cancelled=lambda: True)

    crashed = tmp_path / "crash.py"
    _fake_worker(crashed, "crash")
    with pytest.raises(HtrProcessError) as failure:
        _client(tmp_path, crashed).recognize(_request(), progress=lambda *_: None, cancelled=lambda: False)
    assert failure.value.code == "HTR_PROVIDER_CRASHED"
    # A fresh job must not inherit a failed child's state.
    assert _client(tmp_path, script).recognize(_request(), progress=lambda *_: None, cancelled=lambda: False)[0][0].text == "їжак"


def test_real_worker_reports_missing_weights_before_importing_ml_runtime(tmp_path: Path) -> None:
    request = _request()
    client = HtrProcessClient(HtrRuntime(
        python_executable=Path(sys.executable), model_root=tmp_path,
        timeout_seconds=5, memory_limit_bytes=512 * 1024 * 1024,
    ))

    with pytest.raises(HtrProcessError) as failure:
        client.recognize(request, progress=lambda *_: None, cancelled=lambda: False)

    assert failure.value.code == "HTR_CRNN_WEIGHTS_MISSING"
