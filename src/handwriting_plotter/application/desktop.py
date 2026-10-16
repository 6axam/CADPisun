"""Application API for composing positioned desktop text objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

from handwriting_plotter.adapters.gcode.parser import compare_decoded, decode_virtual_gcode
from handwriting_plotter.adapters.gcode.virtual_xyz import emit_virtual_gcode
from handwriting_plotter.adapters.svg.preview import write_preview_svg
from handwriting_plotter.adapters.svg.writer import write_production_svg
from handwriting_plotter.domain.models import canonical_hash, canonical_json_bytes
from handwriting_plotter.geometry.bounds import Bounds
from handwriting_plotter.geometry.curves import Stroke
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
    x_height_mm: float
    line_pitch_mm: float
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
        diagnostics: list[str] = []
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
            block_spec = PageSpec(
                width_mm=page_spec.width_mm,
                height_mm=page_spec.height_mm,
                margin_left_mm=block.x_mm,
                margin_right_mm=page_spec.margin_right_mm,
                margin_top_mm=block.y_mm,
                margin_bottom_mm=page_spec.margin_bottom_mm,
                x_height_mm=block.x_height_mm,
                line_pitch_mm=block.line_pitch_mm,
                paragraph_gap_mm=page_spec.paragraph_gap_mm,
                pen_width_mm=page_spec.pen_width_mm,
            )
            laid_out = layout_document(document, style, seed=block.seed, page_spec=block_spec,
                                       variation=VariationSpec(block.realism))
            if len(laid_out.pages) != 1:
                raise ValueError(f"OBJECT_REQUIRES_ONE_PAGE:{block.name}:{len(laid_out.pages)}")
            page = laid_out.pages[0]
            lines.extend(_namespace_line(line, block.object_id) for line in page.lines)
            coverage_count += len(laid_out.source_coverage)
            if page.ink_bounds is not None:
                for other_name, other in object_bounds:
                    if _overlap(page.ink_bounds, other):
                        diagnostics.append(f"OBJECT_BOUNDS_OVERLAP:{other_name}:{block.name}")
                object_bounds.append((block.name, page.ink_bounds))
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
        if not lines:
            raise ValueError("NO_RENDERABLE_TEXT")
        total_bounds: Bounds | None = None
        for line in lines:
            total_bounds = line.ink_bounds if total_bounds is None else total_bounds.union(line.ink_bounds)
        page = Page(0, "page-0000", page_spec, tuple(lines), total_bounds)
        page_document = PageDocument(document_id, (page,), tuple(), True, tuple(diagnostics))
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
        files["page-0001.svg"] = write_production_svg(page, pen_plan)
        files["page-0001.preview.svg"] = write_preview_svg(page, pen_plan)
        files["page-0001.gcode"] = command.content
        styles = [style_records[key] for key in sorted(style_records)]
        report = {
            "document_id": page_document.document_id,
            "complete": True,
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
                "empty": False,
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
            "blockers": ["BLK-STYLE-001"] if any(item["test_only"] for item in styles) else [],
        }
        files["report.json"] = canonical_json_bytes(report)
        artifacts = [
            {"path": path, "sha256": sha256(content).hexdigest(), "bytes": len(content)}
            for path, content in sorted(files.items())
        ]
        files["job-manifest.json"] = canonical_json_bytes({
            "format": "hp-job-bundle", "schema_version": "1.0", "document_id": document_id,
            "complete": True, "engine_version": ENGINE_VERSION, "style_revision_hashes":
            [item["revision_hash"] for item in styles], "simulation_only": True,
            "hardware_verified": False, "artifacts": artifacts,
        })
        return GenerationResult(document_id, 1, files, report, any(item["test_only"] for item in styles))
