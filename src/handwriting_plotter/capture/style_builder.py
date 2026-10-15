"""Build immutable test-only StylePacks from reviewed capture drafts."""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from pydantic import Field, field_validator
import regex

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes
from handwriting_plotter.styles.models import GlyphVariantFile, StyleManifest
from handwriting_plotter.styles.repository import FileStyleRepository

from .annotation import (
    AnnotationStore,
    GlyphAnnotation,
    annotation_to_glyph_variant,
    validate_ligature_fallback,
)
from .drafts import DraftCatalog
from .metrics import NormalizedGlyph, NormalizedRepository

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REVISION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")


class StylePackBuildRequest(StrictModel):
    style_id: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=256)
    author_id: str = Field(min_length=1, max_length=128)
    user_confirmed_review: bool = False
    scripts: tuple[str, ...] = ("Cyrillic",)

    @field_validator("style_id")
    @classmethod
    def safe_style_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("INVALID_STYLE_ID")
        return value

    @field_validator("revision")
    @classmethod
    def semantic_revision(cls, value: str) -> str:
        if not _REVISION.fullmatch(value):
            raise ValueError("INVALID_STYLE_REVISION")
        return value


@dataclass(frozen=True, slots=True)
class StylePackBuildReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    variant_ids: tuple[str, ...]
    coverage: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class PublishedStylePack:
    style_id: str
    revision: str
    revision_hash: str
    package_path: Path
    coverage: tuple[str, ...]


class PersonalStylePackBuilder:
    """Validate a mutable draft and publish one new immutable user revision."""

    def __init__(self, studio_root: Path, user_style_root: Path | None = None) -> None:
        self.studio_root = studio_root
        self.user_style_root = user_style_root or studio_root / "styles"
        self.annotations = AnnotationStore(studio_root)
        self.normalized = NormalizedRepository(studio_root)

    def _approved_variants(
        self,
        request: StylePackBuildRequest,
        catalog: DraftCatalog,
    ) -> tuple[list[GlyphVariantFile], StylePackBuildReport]:
        errors: list[str] = []
        warnings = ("TEST_ONLY_STYLE", "SELF_REVIEWED_PUBLICATION")
        if not request.user_confirmed_review:
            errors.append("USER_REVIEW_CONFIRMATION_REQUIRED")
        if catalog.style_id != request.style_id:
            errors.append("STYLE_DRAFT_ID_MISMATCH")

        accepted = {
            item.capture_sha256: item
            for item in catalog.variants
            if item.review_status == "accepted" and not item.deleted
        }
        if not accepted:
            errors.append("NO_ACCEPTED_VARIANTS")
        try:
            annotations = self.annotations.list_all()
        except Exception as exc:
            report = StylePackBuildReport(
                (*errors, f"ANNOTATION_STORE_INVALID:{exc}"), warnings, (), ()
            )
            return [], report

        variants: list[GlyphVariantFile] = []
        sources: list[tuple[GlyphAnnotation, NormalizedGlyph]] = []
        profile_hashes: set[str] = set()
        for annotation in annotations:
            if annotation.review_status != "reviewed":
                continue
            try:
                glyph = self.normalized.load(
                    annotation.source_processed_sha256,
                    annotation.source_normalized_sha256,
                )
            except Exception as exc:
                errors.append(f"NORMALIZED_SOURCE_INVALID:{annotation.variant_id}:{exc}")
                continue
            draft = accepted.get(glyph.source_capture_sha256)
            if draft is None or draft.variant_id != annotation.variant_id:
                continue
            if glyph.metric_profile.style_id != catalog.style_id:
                errors.append(f"METRIC_STYLE_MISMATCH:{annotation.variant_id}")
                continue
            try:
                variant = annotation_to_glyph_variant(annotation, glyph)
            except Exception as exc:
                errors.append(f"ANNOTATION_INVALID:{annotation.variant_id}:{exc}")
                continue
            provenance = variant.provenance.model_copy(update={
                "author_id": request.author_id,
                "reviewed_by": request.author_id,
                "review_record_id": (
                    f"self-review:{annotation.source_normalized_sha256}:r{annotation.revision}"
                ),
            })
            variants.append(variant.model_copy(update={
                "review_status": "approved",
                "provenance": provenance,
            }))
            sources.append((annotation, glyph))
            profile_hashes.add(glyph.metric_profile_sha256)

        accepted_ids = {item.variant_id for item in accepted.values()}
        built_ids = {variant.variant_id for variant in variants}
        for variant_id in sorted(accepted_ids - built_ids):
            errors.append(f"ACCEPTED_VARIANT_NOT_REVIEWED:{variant_id}")
        if not variants:
            errors.append("NO_REVIEWED_VARIANTS")
        if len(profile_hashes) > 1:
            errors.append("MIXED_STYLE_METRIC_PROFILES")
        if len([variant.variant_id for variant in variants]) != len(built_ids):
            errors.append("DUPLICATE_VARIANT_ID")
        individual_keys = {
            variant.key for variant in variants if len(regex.findall(r"\X", variant.key)) == 1
        }
        for annotation, glyph in sources:
            if len(regex.findall(r"\X", annotation.label)) <= 1:
                continue
            fallback = validate_ligature_fallback(annotation, glyph, individual_keys)
            errors.extend(f"{annotation.variant_id}:{item}" for item in fallback.errors)
            warnings = (*warnings, *(f"{annotation.variant_id}:{item}" for item in fallback.warnings))
        for variant in variants:
            if "isolated" not in variant.context_tags and not any(
                other.key == variant.key and "isolated" in other.context_tags
                for other in variants
            ):
                errors.append(f"MISSING_ISOLATED_CONTEXT:{variant.key}")
        report = StylePackBuildReport(
            tuple(dict.fromkeys(errors)),
            warnings,
            tuple(sorted(built_ids)),
            tuple(sorted({variant.key for variant in variants})),
        )
        return variants, report

    def validate(
        self,
        request: StylePackBuildRequest,
        catalog: DraftCatalog,
    ) -> StylePackBuildReport:
        return self._approved_variants(request, catalog)[1]

    def publish(
        self,
        request: StylePackBuildRequest,
        catalog: DraftCatalog,
        *,
        expected_parent_revision: str | None = None,
    ) -> PublishedStylePack:
        glyphs, report = self._approved_variants(request, catalog)
        if not report.passed:
            raise ValueError("STYLE_DRAFT_INVALID:" + ",".join(report.errors))
        annotations = {
            item.variant_id: item
            for item in self.annotations.list_all()
            if item.review_status == "reviewed"
        }
        first = annotations[glyphs[0].variant_id]
        profile = self.normalized.load(
            first.source_processed_sha256, first.source_normalized_sha256
        ).metric_profile

        draft_parent = self.studio_root / "drafts" / "stylepacks" / request.style_id
        draft_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{request.revision}-", dir=draft_parent))
        package = staging / "package"
        try:
            (package / "glyphs").mkdir(parents=True)
            (package / "licenses").mkdir()
            (package / "review").mkdir()
            file_hashes: dict[str, str] = {}
            glyph_files: list[str] = []
            for index, glyph in enumerate(sorted(glyphs, key=lambda item: (item.key, item.variant_id)), 1):
                relative = f"glyphs/{index:04d}-{sha256(glyph.variant_id.encode()).hexdigest()[:12]}.json"
                content = canonical_json_bytes(glyph.model_dump(mode="json"))
                (package / relative).write_bytes(content)
                glyph_files.append(relative)
                file_hashes[relative] = sha256(content).hexdigest()
            license_relative = "licenses/personal-test-only.txt"
            license_content = (
                "Personal handwriting capture for local test-only use.\n"
                "Redistribution is not granted by this record.\n"
            ).encode("utf-8")
            (package / license_relative).write_bytes(license_content)
            file_hashes[license_relative] = sha256(license_content).hexdigest()
            review_files = {
                "review/coverage.json": {
                    "style_id": request.style_id,
                    "revision": request.revision,
                    "test_only": True,
                    "keys": report.coverage,
                    "count": len(report.coverage),
                    "variant_ids": report.variant_ids,
                    "review_scope": "local-user technical sample acceptance",
                },
                "review/pairs.json": {
                    "style_id": request.style_id,
                    "revision": request.revision,
                    "test_only": True,
                    "tested_pairs": (),
                    "warning": "Pair preview is not a complete product acceptance review.",
                },
                "provenance.json": {
                    "style_id": request.style_id,
                    "revision": request.revision,
                    "test_only": True,
                    "production_eligible": False,
                    "source_method": "online_capture",
                    "author_id": request.author_id,
                    "generator": "PersonalStylePackBuilder",
                    "source_normalized_sha256": tuple(sorted(
                        item.source_normalized_sha256
                        for item in annotations.values()
                        if item.variant_id in report.variant_ids
                    )),
                },
            }
            for relative, payload in review_files.items():
                content = canonical_json_bytes(payload)
                (package / relative).write_bytes(content)
                file_hashes[relative] = sha256(content).hexdigest()
            manifest = StyleManifest.model_validate({
                "format": "hp-style",
                "schema_version": "1.0",
                "style_id": request.style_id,
                "revision": request.revision,
                "display_name": request.display_name,
                "scripts": request.scripts,
                "license_record": {
                    "license_id": "personal-test-only",
                    "name": "Personal test-only capture",
                    "redistribution_allowed": False,
                },
                "glyph_frame": "GlyphFrame",
                "metrics": {
                    "x_height_gu": profile.x_height_gu,
                    "ascender_gu": profile.ascender_gu,
                    "descender_gu": profile.descender_gu,
                    "space_advance_gu": profile.space_advance_gu,
                    "line_gap_gu": profile.line_gap_gu,
                    "supported_x_height_mm": profile.supported_x_height_mm,
                },
                "coverage": report.coverage,
                "glyph_files": tuple(glyph_files),
                "join_rules": {},
                "variation_policy": {},
                "file_hashes": file_hashes,
                "approved": False,
                "production_eligible": False,
                "test_only": True,
            }, strict=True)
            (package / "manifest.json").write_bytes(
                canonical_json_bytes(manifest.model_dump(mode="json"))
            )
            repository = FileStyleRepository(self.user_style_root)
            snapshot = repository.publish(package, expected_parent_revision=expected_parent_revision)
            return PublishedStylePack(
                request.style_id,
                request.revision,
                snapshot.revision_hash,
                repository.style_path(request.style_id, request.revision),
                report.coverage,
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

