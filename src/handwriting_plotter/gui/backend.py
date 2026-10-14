"""Qt-free project snapshot conversion into the desktop application API."""

from __future__ import annotations

from dataclasses import asdict

from handwriting_plotter.application.desktop import (
    CompositionRequest,
    CompositionTextBlock,
    DesktopApplicationAdapter,
)
from handwriting_plotter.application.service import GenerationResult
from handwriting_plotter.domain.models import canonical_hash
from handwriting_plotter.layout.pages import PageSpec

from .document import ProjectSnapshot, TextObject


def composition_request(snapshot: ProjectSnapshot) -> CompositionRequest:
    page = snapshot.page
    page_spec = PageSpec(
        width_mm=page.width_mm,
        height_mm=page.height_mm,
        margin_left_mm=page.margin_left_mm,
        margin_right_mm=page.margin_right_mm,
        margin_top_mm=page.margin_top_mm,
        margin_bottom_mm=page.margin_bottom_mm,
        paragraph_gap_mm=page.paragraph_gap_mm,
        pen_width_mm=page.pen_width_mm,
    )
    blocks = tuple(
        CompositionTextBlock(
            object_id=item.object_id,
            name=item.name,
            text=item.text,
            x_mm=item.x_mm,
            y_mm=item.y_mm,
            x_height_mm=item.x_height_mm,
            line_pitch_mm=item.line_pitch_mm,
            style_id=item.style_id,
            style_revision=item.style_revision,
            seed=item.seed,
            realism=item.realism,
        )
        for item in snapshot.objects if isinstance(item, TextObject) and item.visible
    )
    return CompositionRequest(snapshot.project_id, page_spec, blocks)


def generation_source_hash(snapshot: ProjectSnapshot) -> str:
    """Hash only the project fields consumed by the generation backend."""

    request = composition_request(snapshot)
    return canonical_hash({
        "project_id": request.project_id,
        "page_spec": asdict(request.page_spec),
        "blocks": [asdict(block) for block in request.blocks],
    })


class GuiBackend:
    def __init__(self, adapter: DesktopApplicationAdapter | None = None) -> None:
        self.adapter = adapter or DesktopApplicationAdapter()

    def build(self, snapshot: ProjectSnapshot) -> GenerationResult:
        return self.adapter.build(composition_request(snapshot))
