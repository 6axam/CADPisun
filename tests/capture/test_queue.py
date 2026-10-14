from __future__ import annotations

import json

import pytest

from handwriting_plotter.capture.queue import CaptureQueueState, CaptureQueueStore


def test_queue_round_trip_preserves_progress_and_review_metadata(tmp_path) -> None:
    store = CaptureQueueStore(tmp_path)
    state = CaptureQueueState(
        queue_id="default",
        name="Five letters",
        tokens=("а", "м", "и", "н", "о"),
        current_index=2,
        required_variants=2,
        skipped_tokens=frozenset({"м"}),
        rejected_capture_hashes=frozenset({"a" * 64}),
    )

    store.save(state)

    assert store.load("default") == state
    assert json.loads(store.path_for("default").read_bytes())["schema_version"] == "1.0"
    assert not list(tmp_path.rglob("*.tmp"))


def test_queue_rejects_duplicates_invalid_progress_and_unknown_schema(tmp_path) -> None:
    with pytest.raises(ValueError, match="duplicate queue token"):
        CaptureQueueState(queue_id="bad", name="Bad", tokens=("а", "а"))
    with pytest.raises(ValueError, match="current_index"):
        CaptureQueueState(queue_id="bad", name="Bad", tokens=("а",), current_index=1)

    store = CaptureQueueStore(tmp_path)
    path = store.path_for("future")
    path.parent.mkdir(parents=True)
    path.write_text('{"format":"hp-capture-queue","schema_version":"9.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="UNSUPPORTED_QUEUE_SCHEMA"):
        store.load("future")


def test_queue_store_rejects_unsafe_id(tmp_path) -> None:
    store = CaptureQueueStore(tmp_path)
    with pytest.raises(ValueError, match="INVALID_QUEUE_ID"):
        store.path_for("../escape")

