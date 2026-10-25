"""Completely synthetic geometry cases; no handwriting quality measurements."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zlib

import pytest
import regex
from pydantic import ValidationError

from handwriting_plotter.learning import (
    AlignmentStaleError, BinaryInkMask, GraphemeAlignment, GraphemeAlignmentRepository,
    GraphemeSearchLimits, TranscriptionReviewRepository, WordAlignmentRepository,
    align_graphemes, align_photo_graphemes, align_photo_line, align_reviewed_line,
    manual_line_region, persist_ink_mask, persist_line_regions, render_alignment_overlay_svg,
)
from handwriting_plotter.learning.masks import InkMaskRaster
from handwriting_plotter.learning.repository import DecodedImageInfo, PhotoRepository


def _png(mask: BinaryInkMask, *, ink_white=False) -> bytes:
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))

    pixels = bytes((value * 255 if ink_white else 255 - value * 255) for value in mask.foreground)
    rows = b"".join(b"\0" + pixels[y * mask.width_px:(y + 1) * mask.width_px] for y in range(mask.height_px))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", mask.width_px, mask.height_px, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _case(tmp_path, text, points, *, status="accepted"):
    mask = BinaryInkMask(40, 8, bytes(int((x, y) in points) for y in range(8) for x in range(40)))
    photos = PhotoRepository(tmp_path)
    crop = _png(mask)
    digest, _ = photos.store_derivative(crop, suffix="png")
    review = TranscriptionReviewRepository(tmp_path).append(
        source_manifest_sha256="a" * 64, line_id="line-001", crop_sha256=digest,
        htr_run_sha256=None, original_prediction=None, reviewed_text=text, status=status,
        expected_parent_revision_sha256=None,
    )
    words = WordAlignmentRepository(tmp_path).store(align_reviewed_line(
        review=review, mask=mask, mask_sha256="b" * 64,
    ))
    return words, review, mask, crop


def _align(case, **kwargs):
    words, review, mask, _ = case
    return align_graphemes(words=words, review=review, mask=mask, **kwargs)


def test_extended_graphemes_keep_exact_word_offsets_and_ukrainian_symbols(tmp_path):
    case = _case(tmp_path, "ґєіїйь, 42 п'ять п’ять пʼять і\u0301 👩\u200d🔬", set())
    result = _align(case)
    text = case[1].revision.reviewed_text
    assert [(token.start, token.end, token.text) for token in result.tokens] == [
        (match.start(), match.end(), match.group()) for match in regex.finditer(r"\X", text)
    ]
    assert any(token.text == "і\u0301" and token.end - token.start == 2 for token in result.tokens)
    assert any(token.text == "👩\u200d🔬" for token in result.tokens)
    assert all(text[token.start:token.end] == token.text for token in result.tokens)
    assert all(group.state in {"unresolved", "non_ink"} for hypothesis in result.hypotheses for group in hypothesis.groups)


def test_connected_cursive_keeps_mama_whole_without_fictitious_letter_cuts(tmp_path):
    case = _case(tmp_path, "мама", {(x, 4) for x in range(2, 20)})
    result = _align(case)
    for hypothesis in result.hypotheses:
        assert len(hypothesis.groups) == 1
        group = hypothesis.groups[0]
        assert group.grapheme_ids == ("g-0", "g-1", "g-2", "g-3")
        assert group.state == "ambiguous" and group.relation == "join_or_ligature"
        assert len(group.unresolved_joins) == 3
        assert (group.bounds.left_px, group.bounds.right_px) == (2, 20)
    assert result.components == case[0].alignment.components


def test_detached_yi_dots_and_body_are_one_grapheme_with_three_components(tmp_path):
    case = _case(tmp_path, "ї", {(4, 1), (7, 1), *( (x, 4) for x in range(3, 9))})
    result = _align(case)
    for hypothesis in result.hypotheses:
        assert len(hypothesis.groups) == 1
        group = hypothesis.groups[0]
        assert group.grapheme_ids == ("g-0",) and len(group.component_ids) == 3
        assert group.relation == "single_grapheme" and group.state == "ambiguous"
        assert group.bounds.top_px == 1


def test_repeated_letters_have_competing_whole_and_monotone_separate_groups(tmp_path):
    case = _case(tmp_path, "ммм", {(2, 4), (3, 4), (12, 4), (13, 4), (22, 4), (23, 4)})
    result = _align(case)
    assert any(len(hypothesis.groups) == 1 for hypothesis in result.hypotheses)
    separated = next(hypothesis for hypothesis in result.hypotheses if len(hypothesis.groups) == 3)
    assert [group.grapheme_ids for group in separated.groups] == [("g-0",), ("g-1",), ("g-2",)]
    assert [group.bounds.left_px for group in separated.groups] == [2, 12, 22]
    assert {item.word_alternative_id for item in result.hypotheses} == {item.alternative_id for item in case[0].alignment.alternatives}
    assert all(any(item.coarse and item.word_alternative_id == alternative.alternative_id for item in result.hypotheses)
               for alternative in case[0].alignment.alternatives)


def test_false_breaks_allow_one_grapheme_with_multiple_nonoverlapping_components(tmp_path):
    result = _align(_case(tmp_path, "й", {(3, 4), (9, 1)}))
    assert all(len(hypothesis.groups[0].component_ids) == 2 for hypothesis in result.hypotheses)
    assert all(len(hypothesis.groups[0].grapheme_ids) == 1 for hypothesis in result.hypotheses)


def test_diacritic_between_two_bodies_retains_competing_ownership(tmp_path):
    points = {(x, 4) for x in range(2, 6)} | {(x, 4) for x in range(14, 18)} | {(9, 1)}
    result = _align(_case(tmp_path, "іі", points))
    dot = next(component.component_id for component in result.components if component.top_px == 1)
    owners = {group.grapheme_ids for hypothesis in result.hypotheses for group in hypothesis.groups
              if dot in group.component_ids}
    assert ("g-0", "g-1") in owners  # Coarse shared ownership remains an option.
    assert ("g-0",) in owners and ("g-1",) in owners


def test_crossing_strokes_and_connected_words_stay_shared(tmp_path):
    points = {(x, 4) for x in range(2, 18)} | {(9, y) for y in range(1, 7)}
    result = _align(_case(tmp_path, "мій дім", points))
    for hypothesis in result.hypotheses:
        shared = next(group for group in hypothesis.groups if group.component_ids)
        assert shared.relation == "shared_words" and len(shared.grapheme_ids) == 6
        assert len(shared.unresolved_joins) == 5
        assert next(group for group in hypothesis.groups if group.grapheme_ids == ("g-3",)).state == "non_ink"


def test_punctuation_and_empty_words_are_unresolved_with_residual_ink_retained(tmp_path):
    result = _align(_case(tmp_path, "...", {(2, 4), (4, 4), (6, 4)}))
    for hypothesis in result.hypotheses:
        assert all(group.state == "unresolved" for group in hypothesis.groups)
        assert len(hypothesis.unassigned_component_ids) == 3
    empty = _align(_case(tmp_path / "empty", "є?", set()))
    assert all(group.bounds is None for hypothesis in empty.hypotheses for group in hypothesis.groups)


@pytest.mark.parametrize("field", ["max_nodes", "max_candidates", "max_transitions"])
def test_budget_exhaustion_is_bounded_and_keeps_safe_fallback_for_every_word_variant(tmp_path, field):
    case = _case(tmp_path, "ммм", {(2, 4), (12, 4), (22, 4)})
    limits = GraphemeSearchLimits(**{field: 1})
    result = _align(case, limits=limits)
    assert result.budget_exhausted
    assert result.nodes_visited <= limits.max_nodes
    assert result.transitions_evaluated <= limits.max_transitions
    assert result.candidates_evaluated <= limits.max_candidates
    assert all(hypothesis.coarse for hypothesis in result.hypotheses)
    assert {item.word_alternative_id for item in result.hypotheses} == {item.alternative_id for item in case[0].alignment.alternatives}


def test_limits_refuse_dropping_parent_alternatives_and_excessive_text(tmp_path):
    case = _case(tmp_path, "мій дім", {(2, 4), (12, 4)})
    with pytest.raises(ValueError, match="GRAPHEME_LIMIT_MUST_COVER_WORD_ALTERNATIVES"):
        _align(case, limits=GraphemeSearchLimits(max_alternatives=1))
    with pytest.raises(ValueError, match="GRAPHEME_TEXT_LIMIT"):
        _align(_case(tmp_path / "long", "а" * 513, {(2, 4)}))


def test_deterministic_geometry_with_independent_event_metadata(tmp_path):
    case = _case(tmp_path, "ііі", {(3, 1), (3, 4), (12, 1), (12, 4), (22, 1), (22, 4)})
    a, b = _align(case), _align(case)
    assert a.hypotheses == b.hypotheses
    assert a.tokens == b.tokens and a.components == b.components
    assert (a.nodes_visited, a.candidates_evaluated, a.transitions_evaluated) == (b.nodes_visited, b.candidates_evaluated, b.transitions_evaluated)
    assert a.alignment_id != b.alignment_id


def test_requires_accepted_review_and_refuses_mismatched_mask_parent_or_review(tmp_path):
    with pytest.raises(ValueError, match="GRAPHEME_REQUIRES_ACCEPTED_REVIEW"):
        _align(_case(tmp_path / "edited", "й", {(2, 4)}, status="edited"))
    words, review, mask, _ = _case(tmp_path, "є", {(2, 4)})
    with pytest.raises(AlignmentStaleError, match="GRAPHEME_BINARY_MASK_STALE"):
        align_graphemes(words=words, review=review, mask=BinaryInkMask(40, 8, bytes(320)))
    with pytest.raises(AlignmentStaleError, match="GRAPHEME_WORD_ALIGNMENT_HASH_MISMATCH"):
        align_graphemes(words=replace(words, sha256="e" * 64), review=review, mask=mask)
    with pytest.raises(AlignmentStaleError, match="GRAPHEME_REVIEW_HASH_MISMATCH"):
        align_graphemes(words=words, review=replace(review, sha256="e" * 64), mask=mask)
    newer = TranscriptionReviewRepository(tmp_path).append(
        source_manifest_sha256=review.revision.source_manifest_sha256, line_id="line-001",
        crop_sha256=review.revision.crop_sha256, htr_run_sha256=None, original_prediction=None,
        reviewed_text="є!", status="accepted", expected_parent_revision_sha256=review.sha256,
    )
    with pytest.raises(AlignmentStaleError, match="GRAPHEME_REVIEW_STALE"):
        align_graphemes(words=words, review=newer, mask=mask)


def test_immutable_store_reopen_hash_checks_and_model_reference_validation(tmp_path):
    case = _case(tmp_path, "ммм", {(2, 4), (12, 4), (22, 4)})
    result = _align(case)
    repository = GraphemeAlignmentRepository(tmp_path)
    stored = repository.store(result)
    assert repository.load(stored.sha256) == stored
    assert repository.store(result) == stored
    invalid = result.model_dump()
    invalid["tokens"] = (result.tokens[0].model_copy(update={"end": 2}), *result.tokens[1:])
    with pytest.raises(ValidationError, match="INVALID_EXTENDED_GRAPHEME_PARTITION"):
        GraphemeAlignment.model_validate(invalid)
    invalid = result.model_dump()
    groups = result.hypotheses[0].groups
    invalid["hypotheses"] = (result.hypotheses[0].model_copy(update={"groups": (groups[0], groups[0])}),)
    with pytest.raises(ValidationError, match="INVALID_GRAPHEME_GROUP_REFERENCE"):
        GraphemeAlignment.model_validate(invalid)
    with pytest.raises(AlignmentStaleError, match="GRAPHEME_WORD_ALIGNMENT_STALE"):
        result.validate_parent(replace(case[0], sha256="e" * 64))
    stored.path.write_bytes(b"corrupt synthetic result")
    with pytest.raises(ValueError, match="GRAPHEME_ALIGNMENT_HASH_MISMATCH"):
        repository.load(stored.sha256)
    with pytest.raises(ValueError, match="GRAPHEME_ALIGNMENT_HASH_MISMATCH"):
        repository.store(result)


def test_parent_validation_refuses_wrong_spans_missing_fallback_or_escaped_ink(tmp_path):
    case = _case(tmp_path, "мій дім", {(2, 4), (12, 4)})
    result = _align(case)
    invalid = result.model_copy(update={"tokens": (result.tokens[0].model_copy(update={"span_ids": ("missing",)}), *result.tokens[1:])})
    with pytest.raises(ValueError, match="GRAPHEME_SPAN_REFERENCES_MISMATCH"):
        invalid.validate_parent(case[0])
    invalid = result.model_copy(update={"hypotheses": tuple(item.model_copy(update={"coarse": False}) for item in result.hypotheses)})
    with pytest.raises(ValueError, match="GRAPHEME_COARSE_FALLBACK_REQUIRED"):
        invalid.validate_parent(case[0])
    separated = next(hypothesis for hypothesis in result.hypotheses
                     if sum(bool(group.component_ids) for group in hypothesis.groups) == 2)
    ink_groups = [group for group in separated.groups if group.component_ids]
    changed_groups = tuple(
        group.model_copy(update={"component_ids": ink_groups[1].component_ids})
        if group is ink_groups[0] else group for group in separated.groups
    )
    invalid = result.model_copy(update={"hypotheses": (*result.hypotheses, separated.model_copy(update={"coarse": False, "groups": changed_groups}))})
    with pytest.raises(ValueError, match="GRAPHEME_ESCAPES_WORD_CANDIDATE"):
        invalid.validate_parent(case[0])


def test_binary_digest_detects_internal_pixel_change_on_reopen(photo_case):
    from handwriting_plotter.learning.grapheme_alignment import binary_mask_digest

    photos, source, review, words, cropper = photo_case
    result = align_photo_graphemes(photos=photos, source=source, review=review, words=words, cropper=cropper)
    assert result.binary_mask_sha256 != binary_mask_digest(BinaryInkMask(40, 8, bytes(320)))
    invalid = result.model_copy(update={"binary_mask_sha256": "e" * 64})
    repository = GraphemeAlignmentRepository(photos.root)
    stored = repository.store(invalid)
    with pytest.raises(AlignmentStaleError, match="GRAPHEME_BINARY_MASK_STALE"):
        repository.load_current(stored.sha256, photos=photos, source=source, review=review, words=words, cropper=cropper)


def test_svg_shows_source_word_grapheme_shared_and_unresolved_geometry_and_escapes_text(tmp_path):
    case = _case(tmp_path, "ма<&", {(x, 4) for x in range(2, 12)})
    result = _align(case)
    svg = render_alignment_overlay_svg(alignment=result, words=case[0], crop_png=case[3])
    root = ET.fromstring(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert len(root.findall(".//s:image", ns)) == 1
    assert len(root.findall(".//s:rect", ns)) >= 3
    assert "join_or_ligature" in svg and "unresolved joins=1" in svg
    assert "&lt;" in svg and "&amp;" in svg
    assert "unresolved" in svg and "DIAGNOSTIC ALIGNMENT" in svg
    assert not root.findall(".//s:script", ns)
    with pytest.raises(AlignmentStaleError, match="OVERLAY_CROP_HASH_MISMATCH"):
        render_alignment_overlay_svg(alignment=result, words=case[0], crop_png=b"different")


@pytest.fixture
def photo_case(tmp_path):
    pytest.importorskip("cv2")
    from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper

    class Decoder:
        def probe(self, content, limits):
            return DecodedImageInfo(40, 8, "png", "image/png", "synthetic", "1")

    mask = BinaryInkMask(40, 8, bytes(int(y == 4 and x in (2, 3, 12, 13)) for y in range(8) for x in range(40)))
    photos = PhotoRepository(tmp_path / "local")
    original = tmp_path / "synthetic.png"
    original.write_bytes(_png(mask))
    source = photos.import_file(original, Decoder(), imported_at_utc="2026-10-26T10:00:00Z", application_version="test")
    source = persist_ink_mask(photos, source, InkMaskRaster("source-pixels", _png(mask, ink_white=True), _png(mask, ink_white=True), "test/1"))
    source = persist_line_regions(photos, source, (manual_line_region(frame_id="source-pixels", region_id="line-001", left=0, top=0, right=40, bottom=8),))
    digest, _ = photos.store_derivative(_png(mask), suffix="png")
    reviews = TranscriptionReviewRepository(photos.root)
    review = reviews.append(source_manifest_sha256=source.sha256, line_id="line-001", crop_sha256=digest,
                            reviewed_text="мм", original_prediction=None, htr_run_sha256=None, status="accepted", expected_parent_revision_sha256=None)
    cropper = OpenCvLineMaskCropper()
    words = WordAlignmentRepository(photos.root).store(align_photo_line(photos=photos, source=source, review=review, cropper=cropper))
    return photos, source, review, words, cropper


def test_verified_photo_pipeline_and_reopen(photo_case):
    photos, source, review, words, cropper = photo_case
    result = align_photo_graphemes(photos=photos, source=source, review=review, words=words, cropper=cropper)
    repository = GraphemeAlignmentRepository(photos.root)
    stored = repository.store(result)
    assert result.frame_id == "source-pixels" and result.crop_left_px == result.crop_top_px == 0
    assert repository.load_current(stored.sha256, photos=photos, source=source, review=review, words=words, cropper=cropper) == stored


@pytest.mark.parametrize("change", ["review", "mask", "crop", "word", "segmentation"])
def test_photo_stale_inputs_are_refused_at_creation_or_reopen(photo_case, change):
    photos, source, review, words, cropper = photo_case
    repository = GraphemeAlignmentRepository(photos.root)
    stored = repository.store(align_photo_graphemes(photos=photos, source=source, review=review, words=words, cropper=cropper))
    if change == "review":
        review = TranscriptionReviewRepository(photos.root).append(
            source_manifest_sha256=source.sha256, line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256,
            reviewed_text="мм!", original_prediction=None, htr_run_sha256=None, status="accepted", expected_parent_revision_sha256=review.sha256,
        )
    elif change == "mask":
        photos.derivative_path(words.alignment.mask_sha256, "png").write_bytes(b"corrupt mask")
    elif change == "crop":
        photos.derivative_path(words.alignment.crop_sha256, "png").write_bytes(b"corrupt crop")
    elif change == "word":
        words = WordAlignmentRepository(photos.root).store(words.alignment.model_copy(update={"alignment_id": str(uuid.uuid4())}))
    else:
        source = persist_line_regions(photos, source, (manual_line_region(frame_id="source-pixels", region_id="line-001", left=1, top=0, right=40, bottom=8),))
    with pytest.raises((AlignmentStaleError, ValueError)):
        repository.load_current(stored.sha256, photos=photos, source=source, review=review, words=words, cropper=cropper)


def test_stage_has_no_qt_cv_ml_import_side_effects():
    result = subprocess.run([sys.executable, "-c", """
import sys
from handwriting_plotter.learning import align_graphemes, render_alignment_overlay_svg
assert not any(name in sys.modules for name in ('PySide6', 'cv2', 'numpy', 'torch', 'transformers'))
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
