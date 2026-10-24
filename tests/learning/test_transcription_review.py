from __future__ import annotations

from pathlib import Path

import pytest

from handwriting_plotter.learning import (
    ReadingOrderEntry,
    ReviewConflict,
    TranscriptionReviewRepository,
)


SOURCE = "a" * 64
CROP_A = "b" * 64
CROP_B = "c" * 64
RUN = "d" * 64


def test_append_only_review_normalizes_unicode_and_preserves_original_prediction(tmp_path: Path) -> None:
    repository = TranscriptionReviewRepository(tmp_path)
    first = repository.append(
        source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP_A,
        htr_run_sha256=RUN, original_prediction="і\u0308жак", reviewed_text="ґе\u0301й, їжаче!",
        status="edited", expected_parent_revision_sha256=None,
        created_at_utc="2026-10-24T10:00:00Z",
    )
    second = repository.append(
        source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP_A,
        htr_run_sha256=RUN, original_prediction=first.revision.original_prediction,
        reviewed_text="ґей, їжаче!", status="accepted", expected_parent_revision_sha256=first.sha256,
        created_at_utc="2026-10-24T10:01:00Z",
    )

    assert first.revision.original_prediction == "їжак"
    assert second.revision.reviewed_text == "ґей, їжаче!"
    assert repository.load(first.sha256) == first
    assert repository.latest_for_line(SOURCE, "line-001", CROP_A) == second
    assert len(repository.list_for_source(SOURCE)) == 2


def test_review_conflict_and_new_crop_cannot_silently_replace_another_line(tmp_path: Path) -> None:
    repository = TranscriptionReviewRepository(tmp_path)
    first = repository.append(
        source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP_A,
        htr_run_sha256=None, original_prediction=None, reviewed_text="", status="unresolved",
        expected_parent_revision_sha256=None,
    )
    with pytest.raises(ReviewConflict, match="REVIEW_REVISION_CONFLICT"):
        repository.append(
            source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP_A,
            htr_run_sha256=None, original_prediction=None, reviewed_text="текст", status="edited",
            expected_parent_revision_sha256=None,
        )

    replacement = repository.append(
        source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP_B,
        htr_run_sha256=None, original_prediction=None, reviewed_text="новий crop", status="edited",
        expected_parent_revision_sha256=None,
    )
    assert repository.latest_for_line(SOURCE, "line-001", CROP_A) == first
    assert repository.latest_for_line(SOURCE, "line-001", CROP_B) == replacement


def test_reading_order_is_append_only_and_detects_obsolete_writer(tmp_path: Path) -> None:
    repository = TranscriptionReviewRepository(tmp_path)
    initial = repository.append_order(
        source_manifest_sha256=SOURCE,
        entries=(
            ReadingOrderEntry(line_id="line-001", crop_sha256=CROP_A),
            ReadingOrderEntry(line_id="line-002", crop_sha256=CROP_B),
        ),
        expected_parent_revision_sha256=None,
    )
    reordered = repository.append_order(
        source_manifest_sha256=SOURCE,
        entries=tuple(reversed(initial.revision.entries)),
        expected_parent_revision_sha256=initial.sha256,
    )
    with pytest.raises(ReviewConflict, match="READING_ORDER_REVISION_CONFLICT"):
        repository.append_order(
            source_manifest_sha256=SOURCE, entries=initial.revision.entries,
            expected_parent_revision_sha256=initial.sha256,
        )
    assert repository.load_order(reordered.sha256) == reordered
