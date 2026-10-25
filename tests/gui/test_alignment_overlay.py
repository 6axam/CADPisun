"""Render a synthetic diagnostic SVG using the same optional Qt SVG runtime."""

from hashlib import sha256

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from handwriting_plotter.learning import (
    BinaryInkMask, TranscriptionReviewRepository, WordAlignmentRepository,
    align_graphemes, align_reviewed_line, render_alignment_overlay_svg,
)


def test_synthetic_overlay_renders_original_and_diagnostic_groups(qtbot, tmp_path):
    image = QImage(32, 12, QImage.Format.Format_RGB32)
    image.fill(0xffffffff)
    for x in range(2, 18):
        image.setPixel(x, 6, 0xff000000)
    path = tmp_path / "synthetic.png"
    assert image.save(str(path), "PNG")
    crop_png = path.read_bytes()
    mask = BinaryInkMask(32, 12, bytes(int(y == 6 and 2 <= x < 18) for y in range(12) for x in range(32)))
    review = TranscriptionReviewRepository(tmp_path).append(
        source_manifest_sha256="a" * 64, line_id="synthetic", crop_sha256=sha256(crop_png).hexdigest(),
        reviewed_text="мама?", htr_run_sha256=None, original_prediction=None,
        status="accepted", expected_parent_revision_sha256=None,
    )
    words = WordAlignmentRepository(tmp_path).store(align_reviewed_line(review=review, mask=mask, mask_sha256="b" * 64))
    graphemes = align_graphemes(words=words, review=review, mask=mask)
    svg = render_alignment_overlay_svg(alignment=graphemes, words=words, crop_png=crop_png)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    assert renderer.isValid()
    target = QImage(renderer.defaultSize(), QImage.Format.Format_RGB32)
    target.fill(0xffffffff)
    painter = QPainter(target)
    renderer.render(painter)
    painter.end()
    # The source ink is visible inside the image area (translated Y=58,
    # scale=25); the orange border does not erase its center.
    assert target.pixelColor(12 + 8 * 25, 58 + 6 * 25 + 10).red() < 50
    assert "join_or_ligature" in svg and "unresolved" in svg
