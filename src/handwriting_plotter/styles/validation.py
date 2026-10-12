"""Cross-file invariants for a StylePack snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from .coverage import CoverageReport, compare_coverage
from .models import GlyphVariant, StyleManifest


@dataclass(frozen=True, slots=True)
class StyleValidationReport:
    coverage: CoverageReport
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.coverage.passed and not self.errors


def validate_style(manifest: StyleManifest, variants: tuple[GlyphVariant, ...]) -> StyleValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.schema_version != "1.0":
        errors.append("UNSUPPORTED_SCHEMA_VERSION")
    variant_ids = [variant.variant_id for variant in variants]
    if len(variant_ids) != len(set(variant_ids)):
        errors.append("DUPLICATE_VARIANT_ID")
    keys = {variant.key for variant in variants}
    for key in keys:
        if not any(variant.key == key and "isolated" in variant.context_tags for variant in variants):
            errors.append(f"MISSING_ISOLATED_CONTEXT:{key}")
    if len(manifest.coverage) != len(set(manifest.coverage)):
        errors.append("DUPLICATE_COVERAGE_KEY")
    if len(manifest.glyph_files) != len(set(manifest.glyph_files)):
        errors.append("DUPLICATE_GLYPH_FILE")
    coverage = compare_coverage(manifest.coverage, {variant.key for variant in variants})
    if not manifest.license_record.redistribution_allowed:
        warnings.append("LICENSE_RESTRICTS_REDISTRIBUTION")
    if manifest.test_only:
        warnings.append("TEST_ONLY_STYLE")
    if manifest.production_eligible and (not manifest.approved or manifest.test_only):
        errors.append("INVALID_PRODUCTION_ELIGIBILITY")
    return StyleValidationReport(coverage, tuple(errors), tuple(warnings))

