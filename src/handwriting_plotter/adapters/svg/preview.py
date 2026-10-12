"""Diagnostic SVG with travel moves and operation numbering."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from handwriting_plotter.layout.pages import Page
from handwriting_plotter.strokes.compile import Draw, PenPlan, TravelTo

from .writer import SVG_NS, decimal, draw_path


def write_preview_svg(page: Page, plan: PenPlan) -> bytes:
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": f"{decimal(page.spec.width_mm)}mm",
            "height": f"{decimal(page.spec.height_mm)}mm",
            "viewBox": f"0 0 {decimal(page.spec.width_mm)} {decimal(page.spec.height_mm)}",
            "data-role": "diagnostic-preview",
        },
    )
    position = None
    draw_number = 0
    for operation in plan.operations:
        if isinstance(operation, TravelTo):
            if position is not None and position != operation.target:
                ET.SubElement(root, f"{{{SVG_NS}}}path", {
                    "d": f"M {decimal(position.x)} {decimal(position.y)} L {decimal(operation.target.x)} {decimal(operation.target.y)}",
                    "fill": "none", "stroke": "#4b80ff", "stroke-width": "0.15", "stroke-dasharray": "1 1",
                    "data-role": "travel",
                })
            position = operation.target
        elif isinstance(operation, Draw):
            draw_number += 1
            ET.SubElement(root, f"{{{SVG_NS}}}path", {
                "d": draw_path(operation), "fill": "none", "stroke": "black",
                "stroke-width": decimal(page.spec.pen_width_mm), "stroke-linecap": "round", "stroke-linejoin": "round",
                "data-role": "draw",
            })
            start = operation.segments[0].p0
            label = ET.SubElement(root, f"{{{SVG_NS}}}text", {
                "x": decimal(start.x), "y": decimal(start.y), "font-size": "2", "fill": "#c02020",
            })
            label.text = str(draw_number)
            position = operation.segments[-1].p1
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)

