"""Synthetic PNG integration with the existing TASK 07/08/11/12 store."""

from pathlib import Path

import pytest
from pydantic import ValidationError

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper
from handwriting_plotter.learning import (
    AlignmentStaleError, SkeletonCleanupRepository, SkeletonGraph, SkeletonLimitError, SkeletonRepository,
    TranscriptionReviewRepository, extract_photo_skeleton, manual_line_region,
    cleanup_skeleton, persist_ink_mask, persist_line_regions, render_skeleton_overlay_svg, select_ink_mask_variant,
)
from handwriting_plotter.learning.masks import InkMaskRaster
from handwriting_plotter.learning.repository import DecodedImageInfo, PhotoRepository


@pytest.fixture
def photo(tmp_path: Path):
    def png(image):
        ok, content = cv2.imencode(".png", image)
        assert ok
        return content.tobytes()

    class Decoder:
        def probe(self, content, limits):
            image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            assert image is not None
            return DecodedImageInfo(int(image.shape[1]), int(image.shape[0]), "png", "image/png", "test-opencv", "1")

    mask = np.zeros((24, 48), dtype=np.uint8)
    mask[10:14, 4:40] = 255
    mask[3, 7] = mask[3, 12] = 255
    original = tmp_path / "synthetic.png"
    original.write_bytes(png(255 - mask))
    photos = PhotoRepository(tmp_path / "local")
    source = photos.import_file(original, Decoder(), imported_at_utc="2026-10-26T10:00:00Z", application_version="test")
    source = persist_ink_mask(photos, source, InkMaskRaster(
        frame_id="source-pixels", raw_png=png(mask), cleaned_png=png(mask), method="synthetic/1",
    ))
    source = persist_line_regions(photos, source, (
        manual_line_region(frame_id="source-pixels", region_id="line-001", left=1, top=1, right=45, bottom=21),
    ))
    crop_digest, _ = photos.store_derivative(png(255 - mask[1:21, 1:45]), suffix="png")
    review = TranscriptionReviewRepository(photos.root).append(
        source_manifest_sha256=source.sha256, line_id="line-001", crop_sha256=crop_digest,
        reviewed_text="синтетичний рядок", original_prediction=None, htr_run_sha256=None,
        status="accepted", expected_parent_revision_sha256=None,
    )
    return photos, source, review, OpenCvLineMaskCropper()


def test_photo_source_mask_crop_review_coordinates_and_raw_raster_survive_reopen(photo):
    photos, source, review, cropper = photo
    original = photos.read_original(source.photo)
    graph = extract_photo_skeleton(photos=photos, source=source, review=review, cropper=cropper)
    provenance = graph.provenance
    assert (graph.width_px, graph.height_px) == (44, 20)
    assert (provenance.frame_id, provenance.crop_left_px, provenance.crop_top_px) == ("source-pixels", 1, 1)
    assert provenance.source_manifest_sha256 == source.sha256
    assert provenance.review_revision_sha256 == review.sha256
    assert provenance.crop_sha256 == review.revision.crop_sha256
    assert len(graph.components) == 3
    assert {node.anchor for node in graph.nodes if node.kind == "isolated"} == {(6, 2), (11, 2)}
    repository = SkeletonRepository(photos.root)
    stored = repository.store(graph)
    loaded = repository.load_current(stored.sha256, photos=photos, source=source, review=review, cropper=cropper)
    assert loaded == stored
    assert loaded.graph.skeleton_mask() == graph.skeleton_mask()
    assert photos.read_original(source.photo) == original
    assert TranscriptionReviewRepository(photos.root).load(review.sha256) == review
    cleanup_repository = SkeletonCleanupRepository(photos.root)
    cleanup = cleanup_repository.store(cleanup_skeleton(stored))
    reopened = cleanup_repository.load_current(cleanup.sha256, photos=photos, source=source, review=review, cropper=cropper)
    assert reopened == cleanup
    assert reopened.cleanup.provenance == provenance
    assert reopened.cleanup.skeleton_mask() == graph.skeleton_mask()
    assert review.revision.reviewed_text not in render_skeleton_overlay_svg(stored, cleanup=cleanup.cleanup)


@pytest.mark.parametrize("changed", ["review", "mask", "crop", "segmentation", "selected_variant"])
def test_stale_or_corrupt_photo_references_are_refused(photo, changed):
    photos, source, review, cropper = photo
    repository = SkeletonRepository(photos.root)
    stored = repository.store(extract_photo_skeleton(photos=photos, source=source, review=review, cropper=cropper))
    cleanup_repository = SkeletonCleanupRepository(photos.root)
    cleanup = cleanup_repository.store(cleanup_skeleton(stored))
    if changed == "review":
        review = TranscriptionReviewRepository(photos.root).append(
            source_manifest_sha256=source.sha256, line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256,
            reviewed_text="новий рядок", original_prediction=None, htr_run_sha256=None,
            status="accepted", expected_parent_revision_sha256=review.sha256,
        )
    elif changed == "mask":
        photos.derivative_path(stored.graph.provenance.encoded_mask_sha256, "png").write_bytes(b"corrupt synthetic mask")
    elif changed == "crop":
        photos.derivative_path(review.revision.crop_sha256, "png").write_bytes(b"corrupt synthetic crop")
    elif changed == "segmentation":
        source = persist_line_regions(photos, source, (
            manual_line_region(frame_id="source-pixels", region_id="line-001", left=2, top=1, right=45, bottom=21),
        ))
    else:
        source = select_ink_mask_variant(photos, source, "raw")
    with pytest.raises((AlignmentStaleError, ValueError), match="STALE|HASH_MISMATCH"):
        repository.load_current(stored.sha256, photos=photos, source=source, review=review, cropper=cropper)
    with pytest.raises((AlignmentStaleError, ValueError), match="STALE|HASH_MISMATCH"):
        cleanup_repository.load_current(cleanup.sha256, photos=photos, source=source, review=review, cropper=cropper)


def test_unaccepted_review_is_refused_before_thinning(photo):
    photos, source, review, cropper = photo
    edited = TranscriptionReviewRepository(photos.root).append(
        source_manifest_sha256=source.sha256, line_id="line-001", crop_sha256=review.revision.crop_sha256,
        reviewed_text="зміна", original_prediction=None, htr_run_sha256=None,
        status="edited", expected_parent_revision_sha256=review.sha256,
    )
    with pytest.raises(ValueError, match="SKELETON_REQUIRES_ACCEPTED_REVIEW"):
        extract_photo_skeleton(photos=photos, source=source, review=edited, cropper=cropper)


def test_stored_coordinate_shift_cannot_be_applied_to_current_crop(photo):
    photos, source, review, cropper = photo
    graph = extract_photo_skeleton(photos=photos, source=source, review=review, cropper=cropper)
    altered = graph.model_copy(update={"provenance": graph.provenance.model_copy(update={"crop_left_px": 2})})
    repository = SkeletonRepository(photos.root)
    stored = repository.store(altered)
    with pytest.raises(AlignmentStaleError, match="SKELETON_PROVENANCE_STALE"):
        repository.load_current(stored.sha256, photos=photos, source=source, review=review, cropper=cropper)
    cleanups = SkeletonCleanupRepository(photos.root)
    cleanup = cleanups.store(cleanup_skeleton(stored))
    with pytest.raises(AlignmentStaleError, match="SKELETON_PROVENANCE_STALE"):
        cleanups.load_current(cleanup.sha256, photos=photos, source=source, review=review, cropper=cropper)


def test_inconsistent_geometry_and_resource_metadata_cannot_be_persisted(photo):
    photos, source, review, cropper = photo
    graph = extract_photo_skeleton(photos=photos, source=source, review=review, cropper=cropper)
    wrong = {**graph.model_dump(), "components": tuple(
        component.model_copy(update={"cycle_rank": 20}) for component in graph.components
    )}
    with pytest.raises(ValidationError, match="SKELETON_GRAPH_GEOMETRY_MISMATCH"):
        SkeletonGraph.model_validate(wrong)
    wrong = {**graph.model_dump(), "working_memory_estimate_bytes": 0}
    with pytest.raises(ValueError, match="SKELETON_MEMORY_LIMIT"):
        SkeletonGraph.model_validate(wrong)


def test_record_size_is_bounded_before_parsing(photo, monkeypatch):
    import handwriting_plotter.learning.skeleton as module

    photos, source, review, cropper = photo
    graph = extract_photo_skeleton(photos=photos, source=source, review=review, cropper=cropper)
    repository = SkeletonRepository(photos.root)
    stored = repository.store(graph)
    monkeypatch.setattr(module, "MAX_RECORD_BYTES", 16)
    with pytest.raises(SkeletonLimitError, match="SKELETON_RECORD_TOO_LARGE"):
        repository.load(stored.sha256)
    with pytest.raises(SkeletonLimitError, match="SKELETON_RECORD_TOO_LARGE"):
        repository.store(graph)
