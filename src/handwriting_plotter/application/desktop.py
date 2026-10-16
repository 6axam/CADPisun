"""Application API for composing positioned desktop text objects."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

from handwriting_plotter.adapters.gcode.parser import compare_decoded, decode_virtual_gcode
from handwriting_plotter.adapters.gcode.virtual_xyz import emit_virtual_gcode
from handwriting_plotter.adapters.svg.preview import write_preview_svg
from handwriting_plotter.adapters.svg.writer import write_production_svg
from handwriting_plotter.domain.models import canonical_hash, canonical_json_bytes
from handwriting_plotter.geometry.bounds import Bounds, curve_bounds
from handwriting_plotter.geometry.curves import Point2, Stroke
from handwriting_plotter.geometry.transforms import Affine2, transform_segment
from handwriting_plotter.layout.lines import PageLine, PlacedExecutionGroup, PlacedWord
from handwriting_plotter.layout.pages import Page, PageDocument, PageSpec, layout_document
from handwriting_plotter.motion.limits import validate_motion_limits
from handwriting_plotter.motion.planning import plan_virtual_page
from handwriting_plotter.motion.profiles import load_profile
from handwriting_plotter.motion.registration import virtual_registration
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.storage.serialization import primitive
from handwriting_plotter.strokes.compile import compile_page
from handwriting_plotter.strokes.simulate import simulate_pen_plan
from handwriting_plotter.styles.repository import CompositeStyleRepository, FileStyleRepository
from handwriting_plotter.text.coverage import check_coverage
from handwriting_plotter.text.normalize import normalize
from handwriting_plotter.version import ENGINE_VERSION

from .resources import style_root as default_style_root
from .resources import virtual_profile_path
from .service import GenerationResult


@dataclass(frozen=True, slots=True)
class CompositionTextBlock:
    object_id: str
    name: str
    text: str
    x_mm: float
    y_mm: float
    frame_x_mm: float
    frame_y_mm: float
    frame_width_mm: float
    frame_height_mm: float
    x_height_mm: float
    line_pitch_mm: float
    character_spacing_mm: float
    rotation_deg: float
    stroke_color: str
    style_id: str
    style_revision: str
    seed: int
    realism: float


@dataclass(frozen=True, slots=True)
class CompositionRequest:
    project_id: str
    page_spec: PageSpec
    blocks: tuple[CompositionTextBlock, ...]


def _namespace_line(line: PageLine, object_id: str) -> PageLine:
    words: list[PlacedWord] = []
    for word in line.words:
        groups: list[PlacedExecutionGroup] = []
        for group in word.groups:
            refs = tuple(f"{object_id}:{ref}" for ref in group.source_refs)
            strokes = tuple(
                Stroke(
                    f"{object_id}/{stroke.id}",
                    stroke.segments,
                    tuple(f"{object_id}:{ref}" for ref in stroke.source_refs),
                    stroke.role,
                    stroke.direction_provenance,
                )
                for stroke in group.strokes
            )
            groups.append(PlacedExecutionGroup(f"{object_id}/{group.group_id}", strokes, refs))
        words.append(PlacedWord(word.shape, word.origin_x_mm, tuple(groups)))
    return PageLine(f"{object_id}/{line.line_id}", line.baseline_y_mm, tuple(words), line.ink_bounds)


def _rotation(angle_deg: float, center_x: float, center_y: float) -> Affine2:
    angle = math.radians(angle_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    return Affine2(
        cosine,
        sine,
        -sine,
        cosine,
        center_x - cosine * center_x + sine * center_y,
        center_y - sine * center_x - cosine * center_y,
        "PageFrame",
        "PageFrame",
    )


def _rotate_line(
    line: PageLine,
    angle_deg: float,
    center_x: float,
    center_y: float,
    pen_width_mm: float,
) -> PageLine:
    if abs(angle_deg) <= 1e-12:
        return line
    transform = _rotation(angle_deg, center_x, center_y)
    words: list[PlacedWord] = []
    segment_bounds: list[Bounds] = []
    for word in line.words:
        groups: list[PlacedExecutionGroup] = []
        for group in word.groups:
            strokes: list[Stroke] = []
            for stroke in group.strokes:
                segments = tuple(transform_segment(segment, transform) for segment in stroke.segments)
                segment_bounds.extend(curve_bounds(segment) for segment in segments)
                strokes.append(Stroke(
                    stroke.id,
                    segments,
                    stroke.source_refs,
                    stroke.role,
                    stroke.direction_provenance,
                ))
            groups.append(PlacedExecutionGroup(group.group_id, tuple(strokes), group.source_refs))
        origin = transform.apply(Point2(word.origin_x_mm, line.baseline_y_mm))
        words.append(PlacedWord(word.shape, origin.x, tuple(groups)))
    bounds = segment_bounds[0]
    for part in segment_bounds[1:]:
        bounds = bounds.union(part)
    bounds = bounds.expanded(pen_width_mm / 2)
    baseline = transform.apply(Point2(center_x, line.baseline_y_mm)).y
    return PageLine(line.line_id, baseline, tuple(words), bounds)


def _inside(inner: Bounds, outer: Bounds, tolerance: float = 1e-9) -> bool:
    return (
        inner.min_x >= outer.min_x - tolerance
        and inner.min_y >= outer.min_y - tolerance
        and inner.max_x <= outer.max_x + tolerance
        and inner.max_y <= outer.max_y + tolerance
    )


def _overlap(first: Bounds, second: Bounds) -> bool:
    return not (
        first.max_x < second.min_x or second.max_x < first.min_x
        or first.max_y < second.min_y or second.max_y < first.min_y
    )


class DesktopApplicationAdapter:
    """Build one authoritative page from ordered positioned blocks."""

    def __init__(self, styles=None, profile=None) -> None:  # noqa: ANN001
        if styles is None or isinstance(styles, (str, bytes)) or hasattr(styles, "__fspath__"):
            self.style_repository = FileStyleRepository(styles or default_style_root())
        elif isinstance(styles, tuple):
            self.style_repository = CompositeStyleRepository(styles)
        else:
            self.style_repository = styles
        self.profile_path = profile or virtual_profile_path()

    def build(self, request: CompositionRequest) -> GenerationResult:
        if not request.blocks:
            raise ValueError("NO_VISIBLE_TEXT_OBJECTS")
        page_spec = request.page_spec
        profile = load_profile(self.profile_path)
        if profile.pen_width_mm != page_spec.pen_width_mm:
            raise ValueError("PEN_WIDTH_PROFILE_MISMATCH")
        request_payload = {
            "engine_version": ENGINE_VERSION,
            "project_id": request.project_id,
            "page_spec": asdict(page_spec),
            "blocks": [asdict(block) for block in request.blocks],
        }
        document_id = "desktop-" + canonical_hash(request_payload)[:20]
        lines: list[PageLine] = []
        coverage_count = 0
        style_records: dict[tuple[str, str], dict[str, Any]] = {}
        loaded_styles: dict[tuple[str, str], Any] = {}
        object_bounds: list[tuple[str, Bounds]] = []
        overflow_object_ids: list[str] = []
        diagnostics: list[str] = []
        stroke_colors = {block.object_id: block.stroke_color for block in request.blocks}
        files: dict[str, bytes] = {
            "input.txt": "\n\n".join(block.text for block in request.blocks).encode("utf-8"),
            "request.json": canonical_json_bytes(request_payload),
        }
        for block in request.blocks:
            if not block.text:
                diagnostics.append(f"EMPTY_TEXT_OBJECT:{block.object_id}")
                continue
            document = normalize(block.text)
            style_key = (block.style_id, block.style_revision)
            style = loaded_styles.get(style_key)
            if style is None:
                # A load verifies every file hash. Reuse the immutable snapshot only
                # inside this build; the next build verifies the package again.
                style = self.style_repository.load(*style_key)
                loaded_styles[style_key] = style
            coverage = check_coverage(document, style)
            if not coverage.passed:
                missing = ",".join(f"{item.key}@{item.original_spans}" for item in coverage.missing)
                raise ValueError(f"MISSING_GLYPH:{block.name}:{missing}")
            key = (block.style_id, block.style_revision)
            style_records[key] = {
                "style_id": block.style_id,
                "revision": block.style_revision,
                "revision_hash": style.revision_hash,
                "display_name": style.manifest.display_name,
                "test_only": style.manifest.test_only,
                "production_eligible": style.manifest.production_eligible,
            }
            manifest_name = f"styles/{block.style_id}@{block.style_revision}.manifest.json"
            files[manifest_name] = canonical_json_bytes(style.manifest.model_dump(mode="json"))
            frame = Bounds(
                block.frame_x_mm,
                block.frame_y_mm,
                block.frame_x_mm + block.frame_width_mm,
                block.frame_y_mm + block.frame_height_mm,
            )
            if not (
                frame.min_x <= block.x_mm < frame.max_x
                and frame.min_y <= block.y_mm < frame.max_y
            ):
                diagnostics.append(f"OBJECT_FRAME_OVERFLOW:{block.object_id}")
                overflow_object_ids.append(block.object_id)
                continue
            block_spec = PageSpec(
                width_mm=page_spec.width_mm,
                height_mm=page_spec.height_mm,
                margin_left_mm=block.x_mm,
                margin_right_mm=page_spec.width_mm - frame.max_x,
                margin_top_mm=block.y_mm,
                margin_bottom_mm=page_spec.height_mm - frame.max_y,
                x_height_mm=block.x_height_mm,
                line_pitch_mm=block.line_pitch_mm,
                character_spacing_mm=block.character_spacing_mm,
                paragraph_gap_mm=page_spec.paragraph_gap_mm,
                pen_width_mm=page_spec.pen_width_mm,
            )
            try:
                laid_out = layout_document(
                    document,
                    style,
                    seed=block.seed,
                    page_spec=block_spec,
                    variation=VariationSpec(block.realism),
                )
            except ValueError as exc:
                if str(exc) not in {
                    "GLYPH_TOO_WIDE",
                    "LINE_TOO_TALL",
                    "LAYOUT_OUT_OF_BOUNDS",
                    "NONBREAKABLE_OVERFLOW",
                }:
                    raise
                diagnostics.append(f"OBJECT_FRAME_OVERFLOW:{block.object_id}")
                overflow_object_ids.append(block.object_id)
                continue
            if len(laid_out.pages) != 1:
                diagnostics.append(f"OBJECT_FRAME_OVERFLOW:{block.object_id}")
                overflow_object_ids.append(block.object_id)
                continue
            block_page = laid_out.pages[0]
            prepared = tuple(
                _rotate_line(
                    _namespace_line(line, block.object_id),
                    block.rotation_deg,
                    frame.min_x + block.frame_width_mm / 2,
                    frame.min_y + block.frame_height_mm / 2,
                    page_spec.pen_width_mm,
                )
                for line in block_page.lines
            )
            block_bounds: Bounds | None = None
            for line in prepared:
                block_bounds = line.ink_bounds if block_bounds is None else block_bounds.union(line.ink_bounds)
            if block_bounds is not None and not _inside(block_bounds, frame):
                diagnostics.append(f"OBJECT_FRAME_OVERFLOW:{block.object_id}")
                overflow_object_ids.append(block.object_id)
                continue
            lines.extend(prepared)
            coverage_count += len(laid_out.source_coverage)
            if block_bounds is not None:
                for other_name, other in object_bounds:
                    if _overlap(block_bounds, other):
                        diagnostics.append(f"OBJECT_BOUNDS_OVERLAP:{other_name}:{block.name}")
                object_bounds.append((block.name, block_bounds))
        if not lines and not overflow_object_ids:
            raise ValueError("NO_RENDERABLE_TEXT")
        total_bounds: Bounds | None = None
        for line in lines:
            total_bounds = line.ink_bounds if total_bounds is None else total_bounds.union(line.ink_bounds)
        page = Page(0, "page-0000", page_spec, tuple(lines), total_bounds)
        complete = not overflow_object_ids
        page_document = PageDocument(document_id, (page,), tuple(), complete, tuple(diagnostics))
        pen_plan = compile_page(page, document_id)
        logical = simulate_pen_plan(pen_plan)
        registration = virtual_registration(page.page_id, profile)
        motion = plan_virtual_page(pen_plan, profile, registration)
        limit_errors = validate_motion_limits(motion, profile)
        if limit_errors:
            raise ValueError("MOTION_VALIDATION_FAILED:" + ",".join(limit_errors))
        command = emit_virtual_gcode(motion)
        decoded = decode_virtual_gcode(command.content, profile)
        comparison = compare_decoded(motion, decoded)
        if comparison:
            raise ValueError("GCODE_ROUNDTRIP_FAILED:" + ",".join(comparison))
        files["page-0001.plan.json"] = canonical_json_bytes(primitive(pen_plan))
        files["page-0001.motion.json"] = canonical_json_bytes(primitive(motion))
        files["page-0001.svg"] = write_production_svg(page, pen_plan, stroke_colors)
        files["page-0001.preview.svg"] = write_preview_svg(page, pen_plan, stroke_colors)
        files["page-0001.gcode"] = command.content
        styles = [style_records[key] for key in sorted(style_records)]
        report = {
            "document_id": page_document.document_id,
            "complete": complete,
            "page_count": 1,
            "source_coverage_count": coverage_count,
            "styles": styles,
            "machine": {
                "profile_id": profile.profile_id,
                "profile_revision_hash": profile.revision_hash,
                "simulation_only": True,
                "hardware_verified": False,
            },
            "pages": [{
                "page_id": page.page_id,
                "empty": not lines,
                "logical": primitive(logical),
                "motion": {
                    "segment_count": motion.approximation_report.segment_count,
                    "max_deviation_mm": motion.approximation_report.max_deviation_mm,
                    "lower_bound_time_s": motion.lower_bound_time_s,
                    "bounds_all_moves": primitive(motion.bounds_all_moves),
                },
                "gcode_sha256": command.sha256,
                "gcode_roundtrip_passed": True,
            }],
            "diagnostics": diagnostics,
            "overflow_object_ids": overflow_object_ids,
            "blockers": ["BLK-STYLE-001"] if any(item["test_only"] for item in styles) else [],
        }
        files["report.json"] = canonical_json_bytes(report)
        artifacts = [
            {"path": path, "sha256": sha256(content).hexdigest(), "bytes": len(content)}
            for path, content in sorted(files.items())
        ]
        files["job-manifest.json"] = canonical_json_bytes({
            "format": "hp-job-bundle", "schema_version": "1.0", "document_id": document_id,
            "complete": complete, "engine_version": ENGINE_VERSION, "style_revision_hashes":
            [item["revision_hash"] for item in styles], "simulation_only": True,
            "hardware_verified": False, "artifacts": artifacts,
        })
        return GenerationResult(document_id, 1, files, report, any(item["test_only"] for item in styles))
