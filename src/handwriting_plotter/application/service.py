"""Shared application service for CLI and future UI boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from handwriting_plotter.adapters.gcode.parser import compare_decoded, decode_virtual_gcode
from handwriting_plotter.adapters.gcode.virtual_xyz import emit_virtual_gcode
from handwriting_plotter.adapters.svg.preview import write_preview_svg
from handwriting_plotter.adapters.svg.writer import write_production_svg
from handwriting_plotter.domain.models import canonical_json_bytes
from handwriting_plotter.layout.pages import PageSpec, layout_document
from handwriting_plotter.motion.limits import validate_motion_limits
from handwriting_plotter.motion.planning import plan_virtual_page
from handwriting_plotter.motion.profiles import load_profile
from handwriting_plotter.motion.registration import virtual_registration
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.storage.files import publish_bundle
from handwriting_plotter.storage.serialization import primitive
from handwriting_plotter.strokes.compile import compile_page
from handwriting_plotter.strokes.simulate import simulate_pen_plan
from handwriting_plotter.styles.models import StyleSnapshot
from handwriting_plotter.styles.repository import FileStyleRepository
from handwriting_plotter.text.coverage import check_coverage
from handwriting_plotter.text.normalize import normalize
from handwriting_plotter.version import ENGINE_VERSION

from .resources import style_root as default_style_root
from .resources import virtual_profile_path


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    style_id: str = "test-technical-v1"
    style_revision: str = "1.0.0"
    seed: int = 1
    realism: float = 0.35
    page_spec: PageSpec = PageSpec()

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or not 0 <= self.seed < 2**64:
            raise ValueError("seed must be unsigned 64-bit")


@dataclass(frozen=True, slots=True)
class GenerationResult:
    document_id: str
    page_count: int
    files: dict[str, bytes]
    report: dict[str, Any]
    test_only_style: bool


def read_utf8_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="strict")


class HandwritingPlotterService:
    def __init__(self, styles: Path | None = None, profile: Path | None = None) -> None:
        self.style_repository = FileStyleRepository(styles or default_style_root())
        self.profile_path = profile or virtual_profile_path()

    def load_style(self, request: GenerationRequest) -> StyleSnapshot:
        return self.style_repository.load(request.style_id, request.style_revision)

    def inspect(self, text: str, request: GenerationRequest) -> dict[str, Any]:
        document = normalize(text)
        style = self.load_style(request)
        coverage = check_coverage(document, style)
        return {
            "passed": coverage.passed,
            "normalized_text": document.normalized_text,
            "grapheme_count": len(document.graphemes),
            "style_id": style.manifest.style_id,
            "style_revision": style.manifest.revision,
            "test_only_style": style.manifest.test_only,
            "missing": [primitive(item) for item in coverage.missing],
        }

    def build(self, text: str, request: GenerationRequest) -> GenerationResult:
        document = normalize(text)
        style = self.load_style(request)
        coverage = check_coverage(document, style)
        if not coverage.passed:
            missing = ",".join(f"{item.key}@{item.original_spans}" for item in coverage.missing)
            raise ValueError("MISSING_GLYPH:" + missing)
        pages = layout_document(
            document,
            style,
            seed=request.seed,
            page_spec=request.page_spec,
            variation=VariationSpec(request.realism),
        )
        profile = load_profile(self.profile_path)
        if profile.pen_width_mm != request.page_spec.pen_width_mm:
            raise ValueError("PEN_WIDTH_PROFILE_MISMATCH")
        files: dict[str, bytes] = {
            "input.txt": text.encode("utf-8"),
            "request.json": canonical_json_bytes({
                "engine_version": ENGINE_VERSION,
                "style_id": request.style_id,
                "style_revision": request.style_revision,
                "seed": request.seed,
                "realism": request.realism,
                "page_spec": asdict(request.page_spec),
            }),
            "style-manifest.json": canonical_json_bytes(style.manifest.model_dump(mode="json")),
        }
        page_reports: list[dict[str, Any]] = []
        for page in pages.pages:
            if not page.lines:
                page_reports.append({"page_id": page.page_id, "empty": True})
                continue
            pen_plan = compile_page(page, pages.document_id)
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
            stem = f"page-{page.index + 1:04d}"
            files[f"{stem}.plan.json"] = canonical_json_bytes(primitive(pen_plan))
            files[f"{stem}.motion.json"] = canonical_json_bytes(primitive(motion))
            files[f"{stem}.svg"] = write_production_svg(page, pen_plan)
            files[f"{stem}.preview.svg"] = write_preview_svg(page, pen_plan)
            files[f"{stem}.gcode"] = command.content
            page_reports.append({
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
            })
        report = {
            "document_id": pages.document_id,
            "complete": pages.complete,
            "page_count": len(pages.pages),
            "source_coverage_count": len(pages.source_coverage),
            "style": {
                "style_id": style.manifest.style_id,
                "revision": style.manifest.revision,
                "revision_hash": style.revision_hash,
                "test_only": style.manifest.test_only,
                "production_eligible": style.manifest.production_eligible,
            },
            "machine": {
                "profile_id": profile.profile_id,
                "profile_revision_hash": profile.revision_hash,
                "simulation_only": profile.simulation_only,
                "hardware_verified": False,
            },
            "pages": page_reports,
            "diagnostics": list(pages.diagnostics),
            "blockers": ["BLK-STYLE-001"] if style.manifest.test_only else [],
        }
        files["report.json"] = canonical_json_bytes(report)
        artifact_records = [
            {"path": path, "sha256": sha256(content).hexdigest(), "bytes": len(content)}
            for path, content in sorted(files.items())
        ]
        manifest = {
            "format": "hp-job-bundle",
            "schema_version": "1.0",
            "document_id": pages.document_id,
            "complete": True,
            "engine_version": ENGINE_VERSION,
            "style_revision_hash": style.revision_hash,
            "simulation_only": True,
            "hardware_verified": False,
            "artifacts": artifact_records,
        }
        files["job-manifest.json"] = canonical_json_bytes(manifest)
        return GenerationResult(pages.document_id, len(pages.pages), files, report, style.manifest.test_only)

    def generate(self, text: str, output: Path, request: GenerationRequest, *, overwrite: bool = False) -> GenerationResult:
        result = self.build(text, request)
        publish_bundle(output, result.files, overwrite=overwrite)
        return result

