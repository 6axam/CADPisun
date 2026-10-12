"""Hash-derived bounded choices and variation parameters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from handwriting_plotter.styles.models import GlyphVariant, StyleSnapshot

from .resolve import GlyphMatch


ALGORITHM_ID = "hash-variation-v1"


@dataclass(frozen=True, slots=True)
class VariationSpec:
    realism: float = 0.35
    algorithm_id: str = ALGORITHM_ID

    def __post_init__(self) -> None:
        if not 0 <= self.realism <= 1:
            raise ValueError("realism must be within [0,1]")
        if self.algorithm_id != ALGORITHM_ID:
            raise ValueError("unsupported variation algorithm")


@dataclass(frozen=True, slots=True)
class EffectiveVariation:
    scale: float
    shear_deg: float
    baseline_offset_mm: float


def hash_unit(seed: int, style_hash: str, occurrence_id: str, parameter: str, candidate_index: int = 0) -> float:
    if not 0 <= seed < 2**64:
        raise ValueError("seed must be unsigned 64-bit")
    payload = [ALGORITHM_ID, str(seed), style_hash, occurrence_id, parameter, candidate_index]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def symmetric(unit: float, amplitude: float) -> float:
    return (2 * unit - 1) * amplitude


def select_variant(
    match: GlyphMatch,
    *,
    seed: int,
    style_hash: str,
    previous_variant_id: str | None,
) -> GlyphVariant:
    candidates = match.candidates
    if len(candidates) > 1 and previous_variant_id is not None:
        filtered = tuple(item for item in candidates if item.variant_id != previous_variant_id)
        if filtered:
            candidates = filtered
    unit = hash_unit(seed, style_hash, match.occurrence_id, "variant", len(candidates))
    return candidates[min(len(candidates) - 1, int(unit * len(candidates)))]


def effective_variation(
    match: GlyphMatch,
    style: StyleSnapshot,
    spec: VariationSpec,
    seed: int,
) -> EffectiveVariation:
    policy = style.manifest.variation_policy
    realism = spec.realism
    return EffectiveVariation(
        1 + symmetric(hash_unit(seed, style.revision_hash, match.occurrence_id, "scale"), policy.max_scale_fraction * realism),
        symmetric(hash_unit(seed, style.revision_hash, match.occurrence_id, "shear"), policy.max_shear_deg * realism),
        symmetric(
            hash_unit(seed, style.revision_hash, match.occurrence_id, "baseline-offset"),
            policy.max_baseline_offset_mm * realism,
        ),
    )

