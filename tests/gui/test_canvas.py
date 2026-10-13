from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from handwriting_plotter.application.service import GenerationRequest, HandwritingPlotterService
from handwriting_plotter.gui.canvas import PageCanvas


@pytest.fixture(scope="module")
def artifacts() -> dict[str, bytes]:
    return HandwritingPlotterService().build("Test 123", GenerationRequest()).files


def test_canvas_uses_physical_a4_scene(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    page = canvas.page_rect_mm
    assert page.width() == 210.0
    assert page.height() == 297.0


def test_canvas_renders_backend_svg_and_independent_diagnostics(qtbot, artifacts) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.set_artifacts(
        artifacts["page-0001.svg"],
        artifacts["page-0001.preview.svg"],
        artifacts["page-0001.plan.json"],
    )
    assert canvas.has_artifact
    assert canvas._production_item.isVisible()
    assert not canvas._preview_item.isVisible()
    assert all(not item.isVisible() for item in canvas._marker_items)

    canvas.set_show_travel(True)
    canvas.set_show_markers(True)
    assert not canvas._production_item.isVisible()
    assert canvas._preview_item.isVisible()
    assert all(item.isVisible() for item in canvas._marker_items)


def test_zoom_to_fit_is_stable(qtbot) -> None:
    canvas = PageCanvas()
    canvas.resize(700, 700)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.zoom_to_fit()
    assert 0.25 <= canvas.zoom_factor <= 20.0
