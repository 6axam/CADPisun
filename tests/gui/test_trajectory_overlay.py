"""Headless rendering checks for explicitly inferred arrows and pen-up transfers."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from handwriting_plotter.learning import (
    BinaryInkMask, SkeletonRepository, TrajectoryLimits, extract_skeleton,
    infer_trajectories, render_trajectory_overlay_svg,
)


@pytest.mark.parametrize("fallback", [False, True])
def test_directions_and_pen_lifts_render_without_losing_dots(qtbot, tmp_path, fallback):
    points = {(x, 12) for x in range(3, 23)} | {(3, 2), (8, 2)}
    mask = BinaryInkMask(32, 24, bytes(int((x, y) in points) for y in range(24) for x in range(32)))
    raw = SkeletonRepository(tmp_path).store(extract_skeleton(mask))
    limits = TrajectoryLimits(max_search_expansions=1) if fallback else TrajectoryLimits()
    run = infer_trajectories(raw, limits=limits)
    svg = render_trajectory_overlay_svg(raw, run)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    assert renderer.isValid()
    image = QImage(640, 480, QImage.Format.Format_RGB32)
    image.fill(0xffffffff)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    dot = image.pixelColor(3 * 20 + 10, 2 * 20 + 10)
    line = image.pixelColor(18 * 20 + 10, 12 * 20 + 10)
    assert dot.blue() > dot.red() and dot.green() > dot.red()
    assert line.red() < 180  # retained chain in both inferred and unresolved views
    assert ('data-layer="direction-hypothesis"' in svg) is not fallback
    assert ('data-layer="inferred-pen-up"' in svg) is not fallback
    assert ('data-layer="order-hypothesis"' in svg) is not fallback
    assert image.save(str(tmp_path / f"synthetic-trajectory-{fallback}.png"), "PNG")
