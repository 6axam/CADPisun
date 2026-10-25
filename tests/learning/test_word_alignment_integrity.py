"""Synthetic-only end-to-end binding tests for the TASK 12A photo adapter."""

from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import subprocess
import sys

import pytest
from pydantic import ValidationError
from handwriting_plotter.domain.models import canonical_json_bytes

from handwriting_plotter.learning import (
    AlignmentStaleError, BinaryInkMask, TranscriptionReviewRepository,
    WordAlignment, WordAlignmentRepository, align_photo_line, align_reviewed_line,
    manual_line_region, persist_ink_mask, persist_line_regions,
)
from handwriting_plotter.learning.masks import InkMaskRaster
from handwriting_plotter.learning.repository import DecodedImageInfo, PhotoRepository


@pytest.fixture
def photo_line(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper

    class Decoder:
        def probe(self, content, limits):
            return DecodedImageInfo(20, 10, "png", "image/png", "synthetic", "1")

    def png(raster):
        ok, encoded = cv2.imencode(".png", raster)
        assert ok
        return encoded.tobytes()

    pixels = np.zeros((10, 20), dtype=np.uint8)
    pixels[5, 3:8] = 255
    pixels[5, 12:17] = 255
    pixels[2, 5] = pixels[2, 13] = pixels[2, 15] = 255
    path = tmp_path / "synthetic.png"
    path.write_bytes(png(255 - pixels))
    photos = PhotoRepository(tmp_path / "local-only")
    source = photos.import_file(
        path, Decoder(), imported_at_utc="2026-10-25T10:00:00Z", application_version="test",
    )
    source = persist_ink_mask(photos, source, InkMaskRaster(
        "source-pixels", png(pixels), png(pixels), "synthetic/1",
    ))
    source = persist_line_regions(photos, source, (
        manual_line_region(frame_id="source-pixels", region_id="line-001", left=2, top=1, right=18, bottom=8),
    ))
    crop_digest, crop_path = photos.store_derivative(png(255 - pixels[1:8, 2:18]), suffix="png")
    reviews = TranscriptionReviewRepository(photos.root)
    review = reviews.append(
        source_manifest_sha256=source.sha256, line_id="line-001", crop_sha256=crop_digest,
        reviewed_text="мій їжак!", original_prediction=None, htr_run_sha256=None,
        status="accepted", expected_parent_revision_sha256=None,
    )
    return photos, source, reviews, review, OpenCvLineMaskCropper(), crop_path


def test_real_png_roundtrip_preserves_all_ink_and_frame_mapping(photo_line):
    photos, source, reviews, review, cropper, _ = photo_line
    alignment = align_photo_line(photos=photos, source=source, review=review, cropper=cropper)
    again = align_photo_line(photos=photos, source=source, review=review, cropper=cropper)
    assert (alignment.frame_id, alignment.crop_left_px, alignment.crop_top_px) == ("source-pixels", 2, 1)
    assert (alignment.mask_width_px, alignment.mask_height_px) == (16, 7)
    assert sum(component.pixel_count for component in alignment.components) == 13
    assert sum(component.pixel_count == 1 for component in alignment.components) == 3
    assert alignment.alternatives == again.alternatives
    assert alignment.components == again.components
    assert alignment.geometry_candidates == again.geometry_candidates
    repository = WordAlignmentRepository(photos.root)
    stored = repository.store(alignment)
    assert repository.load(stored.sha256).alignment == alignment
    repository.ensure_current(
        stored, reviews=reviews, source_manifest_sha256=source.sha256,
        line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256,
        mask_sha256=alignment.mask_sha256,
    )
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_MASK_STALE"):
        repository.ensure_current(
            stored, reviews=reviews, source_manifest_sha256=source.sha256,
            line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256,
            mask_sha256="0" * 64,
        )
    assert reviews.load(review.sha256) == review


def test_creation_refuses_stale_review_before_reading_any_new_crop(photo_line):
    photos, source, reviews, review, cropper, _ = photo_line
    reviews.append(
        source_manifest_sha256=source.sha256, line_id=review.revision.line_id,
        crop_sha256=review.revision.crop_sha256, reviewed_text="змінений текст",
        original_prediction=None, htr_run_sha256=None, status="edited",
        expected_parent_revision_sha256=review.sha256,
    )
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_REVIEW_REVISION_STALE"):
        align_photo_line(photos=photos, source=source, review=review, cropper=cropper)


def test_creation_refuses_resegmentation_and_in_memory_manifest_changes(photo_line):
    photos, source, _, review, cropper, _ = photo_line
    updated = persist_line_regions(photos, source, (
        manual_line_region(frame_id="source-pixels", region_id="line-001", left=3, top=1, right=18, bottom=8),
    ))
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_SOURCE_MANIFEST_STALE"):
        align_photo_line(photos=photos, source=updated, review=review, cropper=cropper)
    # Even a caller that accidentally retains the old record's hash is refused.
    forged = replace(source, photo=updated.photo)
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_SOURCE_MANIFEST_STALE"):
        align_photo_line(photos=photos, source=forged, review=review, cropper=cropper)


def test_creation_verifies_original_crop_bytes(photo_line):
    photos, source, _, review, cropper, crop_path = photo_line
    crop_path.write_bytes(b"damaged synthetic PNG")
    with pytest.raises(AlignmentStaleError, match="ALIGNMENT_CROP_HASH_MISMATCH"):
        align_photo_line(photos=photos, source=source, review=review, cropper=cropper)


@pytest.mark.parametrize("wrong_asset", ["crop", "mask"])
def test_creation_refuses_dimension_mismatch_even_for_valid_hashed_png(photo_line, wrong_asset):
    photos, source, reviews, review, cropper, _ = photo_line
    # A valid, content-addressed full-frame PNG cannot stand in for a line crop.
    if wrong_asset == "crop":
        digest, _ = photos.store_derivative(photos.read_original(source.photo), suffix="png")
        review = reviews.append(
            source_manifest_sha256=source.sha256, line_id=review.revision.line_id,
            crop_sha256=digest, reviewed_text="рядок", original_prediction=None, htr_run_sha256=None,
            status="accepted", expected_parent_revision_sha256=None,
        )
        code = "ALIGNMENT_CROP_DIMENSIONS_STALE"
    else:
        # Simulate an adapter reporting the wrong dimensions for the mask.
        original_cropper = cropper
        class WrongSize:
            def image_size(self, content):
                result = original_cropper.image_size(content)
                return (100, 100) if result == (20, 10) else result

        cropper = WrongSize()
        code = "ALIGNMENT_MASK_DIMENSIONS_STALE"
    with pytest.raises(AlignmentStaleError, match=code):
        align_photo_line(photos=photos, source=source, review=review, cropper=cropper)


def test_loaded_models_reject_corrupt_references_bounds_and_text(photo_line):
    photos, source, _, review, cropper, _ = photo_line
    alignment = align_photo_line(photos=photos, source=source, review=review, cropper=cropper)
    for update, code in (
        ({"reviewed_text_sha256": "0" * 64}, "ALIGNMENT_TEXT_HASH_MISMATCH"),
        ({"mask_width_px": 1}, "ALIGNMENT_COMPONENT_OUT_OF_BOUNDS"),
        ({"geometry_candidates": (*alignment.geometry_candidates, alignment.geometry_candidates[0])}, "DUPLICATE_GEOMETRY_CANDIDATE"),
    ):
        with pytest.raises(ValidationError, match=code):
            WordAlignment.model_validate({**alignment.model_dump(), **update})
    repo = WordAlignmentRepository(photos.root)
    stored = repo.store(alignment)
    stored.path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="WORD_ALIGNMENT_HASH_MISMATCH"):
        repo.load(stored.sha256)
    with pytest.raises(ValueError, match="WORD_ALIGNMENT_HASH_MISMATCH"):
        repo.store(alignment)


def test_budget_refusal_retains_whole_line_without_recursive_failure(photo_line, monkeypatch):
    import handwriting_plotter.learning.word_alignment as module
    photos, source, _, review, _, _ = photo_line
    monkeypatch.setattr(module, "MAX_PARTITION_TRANSITIONS", 3)
    mask = BinaryInkMask(100, 1, bytes(int(x % 4 == 0) for x in range(100)))
    alignment = align_reviewed_line(review=review, mask=mask, mask_sha256="c" * 64)
    assert "SEARCH_BUDGET_EXHAUSTED" in alignment.diagnostics
    assert all(assignment.state in {"ambiguous", "non_ink", "unresolved"}
               for alternative in alignment.alternatives for assignment in alternative.assignments)


def test_alignment_import_needs_no_qt_cv_or_ml_runtime():
    script = """
import sys
from handwriting_plotter.learning import BinaryInkMask, align_reviewed_line
assert not any(name in sys.modules for name in ('PySide6', 'cv2', 'numpy', 'torch', 'transformers'))
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_legacy_algorithm_record_still_opens(photo_line):
    photos, source, _, review, cropper, _ = photo_line
    alignment = align_photo_line(photos=photos, source=source, review=review, cropper=cropper)
    payload = alignment.model_dump(mode="json", exclude={"frame_id", "crop_left_px", "crop_top_px"})
    payload["algorithm_version"] = "word-spans-components/1"
    content = canonical_json_bytes(payload)
    digest = sha256(content).hexdigest()
    repository = WordAlignmentRepository(photos.root)
    path = repository.path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    loaded = repository.load(digest).alignment
    assert loaded.algorithm_version == "word-spans-components/1"
    assert loaded.frame_id is None
    assert loaded.spans == alignment.spans


def test_sized_work_limits_refuse_instead_of_dropping_marks(photo_line):
    from handwriting_plotter.learning.word_alignment import extract_ink_components

    with pytest.raises(ValueError, match="ALIGNMENT_PIXEL_LIMIT"):
        BinaryInkMask(4_000_001, 1, b"")
    with pytest.raises(ValueError, match="ALIGNMENT_COMPONENT_LIMIT"):
        extract_ink_components(BinaryInkMask(514, 1, bytes(index % 2 for index in range(514))))
    photos, source, _, review, cropper, _ = photo_line
    with pytest.raises(ValueError, match="ALIGNMENT_ALTERNATIVE_LIMIT"):
        align_photo_line(photos=photos, source=source, review=review, cropper=cropper, max_alternatives=0)
