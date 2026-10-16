"""Versioned editable metadata for immutable captured variants."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DraftEvent(StrictModel):
    revision: int = Field(ge=1)
    action: Literal["captured", "preferred", "unpreferred", "accepted", "rejected", "deleted", "restored"]
    occurred_at_utc: str


class VariantDraft(StrictModel):
    variant_id: str = Field(min_length=1, max_length=256)
    sample_id: str = Field(min_length=1, max_length=128)
    capture_sha256: str
    label: str = Field(min_length=1, max_length=256)
    context_tag: Literal["isolated", "initial", "medial", "final"] = "isolated"
    review_status: Literal["draft", "accepted", "rejected"] = "draft"
    preferred: bool = False
    deleted: bool = False
    history: tuple[DraftEvent, ...]

    @field_validator("capture_sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("invalid capture hash")
        return value

    @model_validator(mode="after")
    def valid_history(self) -> VariantDraft:
        if not self.history or self.history[0].action != "captured":
            raise ValueError("variant history must start with captured")
        revisions = [event.revision for event in self.history]
        if revisions != list(range(1, len(revisions) + 1)):
            raise ValueError("variant history revisions must be contiguous")
        return self


class DraftCatalog(StrictModel):
    format: Literal["hp-style-draft"] = "hp-style-draft"
    schema_version: Literal["1.0"] = "1.0"
    style_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=256)
    variants: tuple[VariantDraft, ...] = ()

    @model_validator(mode="after")
    def unique_records(self) -> DraftCatalog:
        for values, name in (
            ([item.variant_id for item in self.variants], "variant id"),
            ([item.sample_id for item in self.variants], "sample id"),
            ([item.capture_sha256 for item in self.variants], "capture hash"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")
        preferred_labels = [item.label for item in self.variants if item.preferred and not item.deleted]
        if len(preferred_labels) != len(set(preferred_labels)):
            raise ValueError("multiple preferred variants for one label")
        return self

    def visible_variants(self, label: str) -> tuple[VariantDraft, ...]:
        return tuple(item for item in self.variants if item.label == label and not item.deleted)

    def add(self, variant: VariantDraft) -> DraftCatalog:
        return DraftCatalog(
            style_id=self.style_id,
            display_name=self.display_name,
            variants=(*self.variants, variant),
        )

    def set_preferred(self, variant_id: str, occurred_at_utc: str) -> DraftCatalog:
        target = self._find(variant_id)
        changed: list[VariantDraft] = []
        for item in self.variants:
            preferred = item.variant_id == variant_id
            if item.label == target.label and item.preferred != preferred:
                item = self._event(item, "preferred" if preferred else "unpreferred", occurred_at_utc,
                                   preferred=preferred)
            changed.append(item)
        return DraftCatalog(
            style_id=self.style_id, display_name=self.display_name, variants=tuple(changed)
        )

    def update_status(self, variant_id: str, status: Literal["accepted", "rejected"], occurred_at_utc: str) -> DraftCatalog:
        action = "accepted" if status == "accepted" else "rejected"
        return self._replace(variant_id, action, occurred_at_utc, review_status=status)

    def delete_from_draft(self, variant_id: str, occurred_at_utc: str) -> DraftCatalog:
        return self._replace(variant_id, "deleted", occurred_at_utc, deleted=True, preferred=False)

    def _replace(self, variant_id: str, action: str, occurred_at_utc: str, **changes) -> DraftCatalog:  # noqa: ANN003
        self._find(variant_id)
        variants = tuple(
            self._event(item, action, occurred_at_utc, **changes) if item.variant_id == variant_id else item
            for item in self.variants
        )
        return DraftCatalog(style_id=self.style_id, display_name=self.display_name, variants=variants)

    @staticmethod
    def _event(item: VariantDraft, action: str, occurred_at_utc: str, **changes) -> VariantDraft:  # noqa: ANN003
        data = item.model_dump(mode="python")
        data.update(changes)
        data["history"] = (*item.history, DraftEvent(
            revision=len(item.history) + 1, action=action, occurred_at_utc=occurred_at_utc,
        ))
        return VariantDraft.model_validate(data, strict=True)

    def _find(self, variant_id: str) -> VariantDraft:
        try:
            return next(item for item in self.variants if item.variant_id == variant_id)
        except StopIteration as exc:
            raise KeyError(variant_id) from exc


class DraftStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, style_id: str) -> Path:
        if not _SAFE_ID.fullmatch(style_id):
            raise ValueError("INVALID_STYLE_DRAFT_ID")
        return self.root / "drafts" / "styles" / f"{style_id}.json"

    def load(self, style_id: str) -> DraftCatalog:
        data = strict_json_loads(self.path_for(style_id).read_bytes())
        if not isinstance(data, dict) or data.get("format") != "hp-style-draft":
            raise ValueError("UNSUPPORTED_DRAFT_FORMAT")
        if data.get("schema_version") != "1.0":
            raise ValueError("UNSUPPORTED_DRAFT_SCHEMA")
        return DraftCatalog.model_validate_json(canonical_json_bytes(data), strict=True)

    def save(self, catalog: DraftCatalog) -> Path:
        path = self.path_for(catalog.style_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = canonical_json_bytes(catalog.model_dump(mode="json"))
        descriptor, name = tempfile.mkstemp(prefix=f".{catalog.style_id}-", suffix=".tmp", dir=path.parent)
        staging = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)
        return path
