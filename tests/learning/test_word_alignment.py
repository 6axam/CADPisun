from __future__ import annotations

from pathlib import Path

import pytest

from handwriting_plotter.learning import (
    AlignmentStaleError,
    BinaryInkMask,
    TranscriptionReviewRepository,
    WordAlignmentRepository,
    align_photo_line,
    align_reviewed_line,
    extract_ink_components,
    manual_line_region,
    persist_ink_mask,
    persist_line_regions,
    prepare_line_alignment_context,
    split_text_spans,
)
from handwriting_plotter.learning.masks import InkMaskRaster
from handwriting_plotter.learning.repository import DecodedImageInfo, PhotoRepository


SOURCE = "a" * 64
CROP = "b" * 64
MASK = "c" * 64


def _mask(width: int, height: int, points: set[tuple[int, int]]) -> BinaryInkMask:
    return BinaryInkMask(
        width_px=width,
        height_px=height,
        foreground=bytes(int((x, y) in points) for y in range(height) for x in range(width)),
    )


def _review(root: Path, text: str, *, status: str = "accepted"):
    return TranscriptionReviewRepository(root).append(
        source_manifest_sha256=SOURCE,
        line_id="line-001",
        crop_sha256=CROP,
        htr_run_sha256=None,
        original_prediction=None,
        reviewed_text=text,
        status=status,  # type: ignore[arg-type]
        expected_parent_revision_sha256=None,
        created_at_utc="2026-10-25T10:00:00Z",
    )


def test_unicode_span_partition_preserves_apostrophes_hyphens_whitespace_and_ranges() -> None:
    text = "півʼяблука, ґанок-й\nїжак"
    spans = split_text_spans(text)

    assert [(span.kind, span.text, span.start, span.end) for span in spans] == [
        ("word", "півʼяблука", 0, 10),
        ("punctuation", ",", 10, 11),
        ("whitespace", " ", 11, 12),
        ("word", "ґанок", 12, 17),
        ("punctuation", "-", 17, 18),
        ("word", "й", 18, 19),
        ("whitespace", "\n", 19, 20),
        ("word", "їжак", 20, 24),
    ]
    assert "".join(span.text for span in spans) == text


def test_components_keep_tiny_dot_and_connected_words_remain_ambiguous(tmp_path: Path) -> None:
    # One main cursive component plus the dot of і.  There is no trustworthy
    # pixel evidence for splitting the two reviewed words at their space.
    mask = _mask(12, 6, {
        (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3), (8, 3),
        (4, 1),
    })
    components = extract_ink_components(mask)
    assert any(component.pixel_count == 1 for component in components)
    alignment = align_reviewed_line(review=_review(tmp_path, "мій дім"), mask=mask, mask_sha256=MASK)

    word_assignments = [
        assignment for assignment in alignment.alternatives[0].assignments
        if alignment.spans[int(assignment.span_id.removeprefix("span-"))].kind == "word"
    ]
    assert all(assignment.state == "ambiguous" for assignment in word_assignments)
    assert word_assignments[0].geometry_candidate_ids == word_assignments[1].geometry_candidate_ids
    assert "NO_LETTER_BOUNDARIES_IN_TASK_12A" in alignment.diagnostics


def test_false_component_breaks_and_missing_spaces_keep_alternatives(tmp_path: Path) -> None:
    # A false visual gap within one word must not become an invented letter or
    # exact word boundary.  The all-components grouping remains a candidate.
    mask = _mask(16, 5, {
        (1, 2), (2, 2), (3, 2), (8, 2), (9, 2), (10, 2),
    })
    alignment = align_reviewed_line(review=_review(tmp_path, "привіт"), mask=mask, mask_sha256=MASK)

    assert len(alignment.alternatives) >= 2
    assert any(
        any(assignment.state == "ambiguous" for assignment in alternative.assignments)
        for alternative in alignment.alternatives
    )
    assert all(
        assignment.state != "matched" or len(assignment.geometry_candidate_ids) == 1
        for alternative in alignment.alternatives for assignment in alternative.assignments
    )


def test_punctuation_and_absent_ink_are_explicitly_unresolved_not_fabricated(tmp_path: Path) -> None:
    mask = _mask(8, 4, set())
    alignment = align_reviewed_line(review=_review(tmp_path, "слово..."), mask=mask, mask_sha256=MASK)
    assignments = {assignment.span_id: assignment for assignment in alignment.alternatives[0].assignments}

    assert assignments["span-0"].state == "unresolved"
    assert assignments["span-1"].state == "unresolved"
    assert assignments["span-2"].state == "unresolved"
    assert assignments["span-3"].state == "unresolved"


def test_alignment_persistence_and_stale_review_or_crop_are_rejected(tmp_path: Path) -> None:
    reviews = TranscriptionReviewRepository(tmp_path)
    review = reviews.append(
        source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP,
        htr_run_sha256=None, original_prediction=None, reviewed_text="так", status="accepted",
        expected_parent_revision_sha256=None,
    )
    alignment = align_reviewed_line(
        review=review, mask=_mask(6, 4, {(1, 2), (2, 2)}), mask_sha256=MASK,
    )
    stored = WordAlignmentRepository(tmp_path).store(alignment)
    repository = WordAlignmentRepository(tmp_path)
    assert repository.load(stored.sha256) == stored
    repository.ensure_current(
        stored, reviews=reviews, source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP,
    )

    newer = reviews.append(
        source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP,
        htr_run_sha256=None, original_prediction=None, reviewed_text="так!", status="edited",
        expected_parent_revision_sha256=review.sha256,
    )
    assert newer.sha256 != review.sha256
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_REVIEW_REVISION_STALE"):
        repository.ensure_current(
            stored, reviews=reviews, source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256=CROP,
        )
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_CROP_OR_MANIFEST_STALE"):
        repository.ensure_current(
            stored, reviews=reviews, source_manifest_sha256=SOURCE, line_id="line-001", crop_sha256="d" * 64,
        )


def test_unreviewed_or_unresolved_text_cannot_enter_alignment(tmp_path: Path) -> None:
    mask = _mask(3, 3, {(1, 1)})
    with pytest.raises(ValueError, match="ALIGNMENT_REQUIRES_REVIEWED_TEXT"):
        align_reviewed_line(review=_review(tmp_path, "текст", status="unresolved"), mask=mask, mask_sha256=MASK)


def test_existing_photo_mask_line_and_review_are_reused_without_parallel_pipeline(tmp_path: Path) -> None:
    class Decoder:
        def probe(self, content: bytes, _limits):  # noqa: ANN001
            return DecodedImageInfo(
                width_px=12, height_px=6, detected_format="png", media_type="image/png",
                decoder_id="test", decoder_version="1",
            )

    root = tmp_path / "private-local-store"
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"opaque-private-original")
    photos = PhotoRepository(root)
    imported = photos.import_file(
        source_path, Decoder(), imported_at_utc="2026-10-25T10:00:00Z", application_version="test",
        source_id="alignment-source", rights_status="private_user_material",
    )
    masked = persist_ink_mask(photos, imported, InkMaskRaster(
        frame_id="source-pixels", raw_png=b"raw-mask", cleaned_png=b"clean-mask", method="test-mask/1",
    ))
    source = persist_line_regions(photos, masked, (
        manual_line_region(frame_id="source-pixels", region_id="line-001", left=1, top=1, right=11, bottom=5),
    ))
    reviews = TranscriptionReviewRepository(root)
    review = reviews.append(
        source_manifest_sha256=source.sha256, line_id="line-001", crop_sha256=CROP,
        htr_run_sha256=None, original_prediction=None, reviewed_text="слово", status="accepted",
        expected_parent_revision_sha256=None,
    )

    context = prepare_line_alignment_context(photos=photos, source=source, review=review)
    assert context.mask_sha256 == source.photo.ink_mask.cleaned_sha256  # type: ignore[union-attr]
    assert context.line_region.region_id == "line-001"

    class StubCropper:
        def crop(self, mask_png: bytes, *, line_region):  # noqa: ANN001
            assert mask_png == b"clean-mask" and line_region.region_id == "line-001"
            return _mask(5, 3, {(1, 1), (2, 1)})

    alignment = align_photo_line(photos=photos, source=source, review=review, cropper=StubCropper())
    assert alignment.source_manifest_sha256 == source.sha256
    assert alignment.mask_sha256 == source.photo.ink_mask.cleaned_sha256  # type: ignore[union-attr]


def test_opencv_cropper_preserves_single_pixel_diacritic() -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper

    raster = np.zeros((6, 10), dtype=np.uint8)
    raster[3, 2:7] = 255
    raster[1, 4] = 255
    ok, encoded = cv2.imencode(".png", raster)
    assert ok
    cropped = OpenCvLineMaskCropper().crop(
        encoded.tobytes(),
        line_region=manual_line_region(
            frame_id="source-pixels", region_id="line-001", left=1, top=0, right=8, bottom=5,
        ),
    )
    assert sum(cropped.foreground) == 6
