"""The optional Qt renderer must show retained ink, marks and removal diagnostics."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from handwriting_plotter.learning import (
    BinaryInkMask, SkeletonRepository, cleanup_skeleton, extract_skeleton, render_skeleton_overlay_svg,
)


def test_skeleton_diagnostics_render_as_png_without_direction_or_lost_marks(qtbot, tmp_path):
    points = {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(8, 11)} | {(3, 2), (6, 2)}
    mask = BinaryInkMask(32, 24, bytes(int((x, y) in points) for y in range(24) for x in range(32)))
    raw = SkeletonRepository(tmp_path).store(extract_skeleton(mask))
    candidate = cleanup_skeleton(raw).candidates[0]
    cleanup = cleanup_skeleton(raw, remove_edge_ids=(candidate.edge_id,))
    renderer = QSvgRenderer(QByteArray(render_skeleton_overlay_svg(raw, cleanup=cleanup).encode()))
    assert renderer.isValid()
    image = QImage(640, 480, QImage.Format.Format_RGB32)
    image.fill(0xffffffff)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    removed = image.pixelColor(12 * 20 + 10, 8 * 20 + 10)
    dot = image.pixelColor(3 * 20 + 10, 2 * 20 + 10)
    retained = image.pixelColor(8 * 20 + 10, 10 * 20 + 10)
    assert removed.red() > 150 and removed.green() < 100
    assert dot.blue() > dot.red() and dot.green() > dot.red()
    assert retained.blue() > retained.red()
    assert image.pixelColor(0, 0).name() == "#ffffff"
    assert image.save(str(tmp_path / "synthetic-skeleton-diagnostic.png"), "PNG")
