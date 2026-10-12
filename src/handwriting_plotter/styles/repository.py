"""Filesystem StylePack loader and atomic immutable publication."""

from __future__ import annotations

import os
import shutil
import tempfile
import unicodedata
from hashlib import sha256
from pathlib import Path

import regex

from handwriting_plotter.domain.models import canonical_hash, canonical_json_bytes, strict_json_loads
from handwriting_plotter.geometry.bounds import curve_bounds

from .models import GlyphVariantFile, StyleManifest, StyleSnapshot, to_variant
from .validation import validate_style


def _safe_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("PATH_OUTSIDE_STYLE")
    return candidate


class FileStyleRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def style_path(self, style_id: str, revision: str) -> Path:
        if not style_id or not revision or any(part in {"", ".", ".."} for part in Path(style_id, revision).parts):
            raise ValueError("invalid style reference")
        return _safe_child(self.root, f"{style_id}/{revision}")

    def load(self, style_id: str, revision: str) -> StyleSnapshot:
        package = self.style_path(style_id, revision)
        manifest_path = package / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("STYLE_NOT_FOUND")
        manifest_data = strict_json_loads(manifest_path.read_bytes())
        manifest = StyleManifest.model_validate_json(canonical_json_bytes(manifest_data), strict=True)
        if manifest.style_id != style_id or manifest.revision != revision:
            raise ValueError("STYLE_REFERENCE_MISMATCH")
        if manifest.schema_version != "1.0":
            raise ValueError("UNSUPPORTED_SCHEMA_VERSION")
        license_path = _safe_child(package, f"licenses/{manifest.license_record.license_id}.txt")
        if not license_path.is_file() or not license_path.read_text(encoding="utf-8").strip():
            raise ValueError("LICENSE_RECORD_MISSING")
        required_hashed = set(manifest.glyph_files) | {f"licenses/{manifest.license_record.license_id}.txt"}
        if not required_hashed <= set(manifest.file_hashes):
            raise ValueError("MISSING_FILE_HASH")
        total_size = 0
        for relative, expected in manifest.file_hashes.items():
            item = _safe_child(package, relative)
            if not item.is_file():
                raise ValueError(f"HASH_MISMATCH:{relative}")
            content = item.read_bytes()
            total_size += len(content)
            if sha256(content).hexdigest() != expected:
                raise ValueError(f"HASH_MISMATCH:{relative}")
        if total_size > 100 * 1024 * 1024 or len(manifest.glyph_files) > 100_000:
            raise ValueError("RESOURCE_LIMIT")
        parsed: list[GlyphVariantFile] = []
        for relative in manifest.glyph_files:
            glyph_path = _safe_child(package, relative)
            glyph_data = strict_json_loads(glyph_path.read_bytes())
            item = GlyphVariantFile.model_validate_json(canonical_json_bytes(glyph_data), strict=True)
            if item.review_status != "approved":
                raise ValueError(f"UNREVIEWED_SAMPLE:{item.variant_id}")
            if item.provenance.license_id != manifest.license_record.license_id:
                raise ValueError(f"LICENSE_RECORD_MISMATCH:{item.variant_id}")
            if unicodedata.normalize("NFC", item.key) != item.key or len(regex.findall(r"\X", item.key)) > 8:
                raise ValueError(f"INVALID_GLYPH_KEY:{item.variant_id}")
            parsed.append(item)
        variants = tuple(to_variant(item) for item in parsed)
        for variant in variants:
            for stroke in variant.strokes:
                for segment in stroke.segments:
                    bounds = curve_bounds(segment)
                    if bounds.min_y < manifest.metrics.descender_gu or bounds.max_y > manifest.metrics.ascender_gu:
                        raise ValueError(f"GLYPH_OUTSIDE_ENVELOPE:{variant.variant_id}")
        report = validate_style(manifest, variants)
        if not report.passed:
            raise ValueError("STYLE_VALIDATION_FAILED:" + ",".join((*report.errors, *report.coverage.missing)))
        by_key: dict[str, list] = {}
        for variant in sorted(variants, key=lambda item: (item.key, item.variant_id)):
            by_key.setdefault(variant.key, []).append(variant)
        revision_hash = canonical_hash({"manifest": manifest_data, "files": manifest.file_hashes})
        return StyleSnapshot.frozen(manifest, by_key, revision_hash)

    def publish(self, source: Path, *, expected_parent_revision: str | None = None) -> StyleSnapshot:
        source_data = strict_json_loads((source / "manifest.json").read_bytes())
        source_manifest = StyleManifest.model_validate_json(canonical_json_bytes(source_data), strict=True)
        target = self.style_path(source_manifest.style_id, source_manifest.revision)
        if target.exists():
            raise ValueError("REVISION_CONFLICT")
        style_root = target.parent
        if expected_parent_revision is not None and style_root.exists():
            latest = style_root / "latest"
            if not latest.is_file() or latest.read_text(encoding="ascii").strip() != expected_parent_revision:
                raise ValueError("REVISION_CONFLICT")
        style_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".publish-", dir=style_root))
        try:
            shutil.copytree(source, staging / "package", dirs_exist_ok=True)
            staged_repo = FileStyleRepository(staging)
            staged_target = staging / source_manifest.style_id / source_manifest.revision
            staged_target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / "package", staged_target)
            snapshot = staged_repo.load(source_manifest.style_id, source_manifest.revision)
            os.replace(staged_target, target)
            latest_tmp = style_root / ".latest.tmp"
            latest_tmp.write_text(source_manifest.revision + "\n", encoding="ascii")
            os.replace(latest_tmp, style_root / "latest")
            return snapshot
        finally:
            shutil.rmtree(staging, ignore_errors=True)

