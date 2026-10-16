"""Pure production SVG: visible pen contacts only."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from xml.etree import ElementTree as ET

from handwriting_plotter.geometry.curves import Cubic, Line, Quadratic
from handwriting_plotter.layout.pages import Page
from handwriting_plotter.strokes.compile import Draw, PenPlan
from handwriting_plotter.strokes.validate import validate_pen_plan


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def decimal(value: float, quantum: str = "0.001") -> str:
    result = Decimal(str(value)).quantize(Decimal(quantum), rounding=ROUND_HALF_EVEN)
    if result == 0:
        result = abs(result)
    return format(result, "f")


def draw_path(operation: Draw) -> str:
    start = operation.segments[0].p0
    parts = [f"M {decimal(start.x)} {decimal(start.y)}"]
    for segment in operation.segments:
        if isinstance(segment, Line):
            parts.append(f"L {decimal(segment.p1.x)} {decimal(segment.p1.y)}")
        elif isinstance(segment, Quadratic):
            parts.append(
                f"Q {decimal(segment.c1.x)} {decimal(segment.c1.y)} {decimal(segment.p1.x)} {decimal(segment.p1.y)}"
            )
        elif isinstance(segment, Cubic):
            parts.append(
                "C "
                f"{decimal(segment.c1.x)} {decimal(segment.c1.y)} "
                f"{decimal(segment.c2.x)} {decimal(segment.c2.y)} "
                f"{decimal(segment.p1.x)} {decimal(segment.p1.y)}"
            )
    return " ".join(parts)


def operation_color(operation: Draw, stroke_colors: dict[str, str] | None) -> str:
    if not stroke_colors or not operation.stroke_ids:
        return "black"
    object_id = operation.stroke_ids[0].split("/", 1)[0]
    return stroke_colors.get(object_id, "black")


def write_production_svg(
    page: Page,
    plan: PenPlan,
    stroke_colors: dict[str, str] | None = None,
) -> bytes:
    validation = validate_pen_plan(plan)
    if not validation.passed or plan.page_id != page.page_id:
        raise ValueError("INVALID_PEN_PLAN")
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": f"{decimal(page.spec.width_mm)}mm",
            "height": f"{decimal(page.spec.height_mm)}mm",
            "viewBox": f"0 0 {decimal(page.spec.width_mm)} {decimal(page.spec.height_mm)}",
            "data-role": "production",
        },
    )
    ET.SubElement(root, f"{{{SVG_NS}}}metadata").text = f"Handwriting Plotter page {page.page_id}"
    for operation in plan.operations:
        if isinstance(operation, Draw):
            ET.SubElement(
                root,
                f"{{{SVG_NS}}}path",
                {
                    "d": draw_path(operation),
                    "fill": "none",
                    "stroke": operation_color(operation, stroke_colors),
                    "stroke-width": decimal(page.spec.pen_width_mm),
                    "stroke-linecap": "round",
                    "stroke-linejoin": "round",
                    "data-op-id": operation.op_id,
                    "data-stroke-ids": " ".join(operation.stroke_ids),
                },
            )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)

