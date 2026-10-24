"""A4 notebook-paper templates kept separate from plotter geometry.

The module is deliberately Qt-free: it owns millimetre geometry and the
standalone SVG export used by the desktop preview and File menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, isfinite
from typing import Iterator, Literal

from pydantic import Field, model_validator

from handwriting_plotter.domain.models import StrictModel

TemplateKind = Literal["blank", "squared", "ruled"]
Orientation = Literal["portrait", "landscape"]

A4_PORTRAIT_MM = (210.0, 297.0)


class NotebookPageTemplate(StrictModel):
    """Portable visual A4 paper definition measured entirely in millimetres."""

    kind: TemplateKind = "squared"
    orientation: Orientation = "portrait"
    margin_left_mm: float = Field(default=15.0, ge=0.0, le=297.0)
    margin_right_mm: float = Field(default=15.0, ge=0.0, le=297.0)
    margin_top_mm: float = Field(default=15.0, ge=0.0, le=297.0)
    margin_bottom_mm: float = Field(default=15.0, ge=0.0, le=297.0)
    pitch_x_mm: float = Field(default=5.0, gt=0.0, le=50.0)
    pitch_y_mm: float = Field(default=5.0, gt=0.0, le=50.0)
    offset_x_mm: float = Field(default=0.0, ge=-100.0, le=297.0)
    offset_y_mm: float = Field(default=0.0, ge=-100.0, le=297.0)
    line_color: str = Field(default="#9CC9E8", pattern=r"^#[0-9A-Fa-f]{6}$")
    line_width_mm: float = Field(default=0.15, gt=0.0, le=2.0)
    major_every: int = Field(default=5, ge=1, le=50)
    major_line_color: str = Field(default="#6AAED6", pattern=r"^#[0-9A-Fa-f]{6}$")
    major_line_width_mm: float = Field(default=0.25, gt=0.0, le=2.0)

    @property
    def page_size_mm(self) -> tuple[float, float]:
        width, height = A4_PORTRAIT_MM
        return (width, height) if self.orientation == "portrait" else (height, width)

    @property
    def content_rect_mm(self) -> tuple[float, float, float, float]:
        width, height = self.page_size_mm
        return (
            self.margin_left_mm,
            self.margin_top_mm,
            width - self.margin_right_mm,
            height - self.margin_bottom_mm,
        )

    @model_validator(mode="after")
    def margins_leave_a_writable_area(self) -> "NotebookPageTemplate":
        width, height = self.page_size_mm
        if self.margin_left_mm + self.margin_right_mm >= width:
            raise ValueError("template horizontal margins consume A4")
        if self.margin_top_mm + self.margin_bottom_mm >= height:
            raise ValueError("template vertical margins consume A4")
        if self.major_line_width_mm < self.line_width_mm:
            raise ValueError("major line width must not be smaller than line width")
        return self


@dataclass(frozen=True, slots=True)
class BackgroundLine:
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    color: str
    width_mm: float
    major: bool


def _axis_positions(start: float, end: float, pitch: float, offset: float) -> Iterator[tuple[float, int]]:
    """Yield aligned positions in a clipped printable interval, inclusive."""

    anchor = start + offset
    first = ceil((start - anchor) / pitch - 1e-10)
    last = floor((end - anchor) / pitch + 1e-10)
    for index in range(first, last + 1):
        position = anchor + index * pitch
        if start - 1e-8 <= position <= end + 1e-8:
            yield (min(end, max(start, position)), index)


def background_lines(template: NotebookPageTemplate) -> tuple[BackgroundLine, ...]:
    """Return page-background lines without any pen-plan semantics."""

    left, top, right, bottom = template.content_rect_mm
    if template.kind == "blank":
        return ()
    lines: list[BackgroundLine] = []

    def style(index: int) -> tuple[str, float, bool]:
        major = index % template.major_every == 0
        return (
            template.major_line_color if major else template.line_color,
            template.major_line_width_mm if major else template.line_width_mm,
            major,
        )

    if template.kind == "squared":
        for x, index in _axis_positions(left, right, template.pitch_x_mm, template.offset_x_mm):
            color, width, major = style(index)
            lines.append(BackgroundLine(x, top, x, bottom, color, width, major))
    for y, index in _axis_positions(top, bottom, template.pitch_y_mm, template.offset_y_mm):
        color, width, major = style(index)
        lines.append(BackgroundLine(left, y, right, y, color, width, major))
    return tuple(lines)


def _number(value: float) -> str:
    if not isfinite(value):
        raise ValueError("background geometry must be finite")
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def notebook_background_svg(template: NotebookPageTemplate) -> bytes:
    """Render a standalone physical A4 SVG for printing or visual reference.

    This is intentionally outside the production/diagnostic SVG and G-code
    exporters.  Backgrounds are paper artwork, never plotting strokes.
    """

    width, height = template.page_size_mm
    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_number(width)}mm" '
        f'height="{_number(height)}mm" viewBox="0 0 {_number(width)} {_number(height)}">',
        f'  <rect x="0" y="0" width="{_number(width)}" height="{_number(height)}" fill="#FFFFFF"/>',
    ]
    for line in background_lines(template):
        svg.append(
            "  <line "
            f'x1="{_number(line.x1_mm)}" y1="{_number(line.y1_mm)}" '
            f'x2="{_number(line.x2_mm)}" y2="{_number(line.y2_mm)}" '
            f'stroke="{line.color.upper()}" stroke-width="{_number(line.width_mm)}" '
            'vector-effect="non-scaling-stroke"/>'
        )
    svg.append("</svg>")
    return ("\n".join(svg) + "\n").encode("utf-8")
