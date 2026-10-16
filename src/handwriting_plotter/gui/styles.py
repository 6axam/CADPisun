"""StylePack catalog presented by the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from handwriting_plotter.application.resources import style_root
from handwriting_plotter.styles.repository import FileStyleRepository


@dataclass(frozen=True, slots=True)
class StyleSummary:
    style_id: str
    revision: str
    display_name: str
    test_only: bool
    production_eligible: bool
    valid: bool
    detail: str
    source: str = "built-in"

    @property
    def reference(self) -> tuple[str, str]:
        return self.style_id, self.revision


def discover_styles(user_root: Path | None = None) -> tuple[StyleSummary, ...]:
    roots = ((style_root(), "built-in"),)
    if user_root is not None:
        roots = (*roots, (user_root, "user"))
    result: list[StyleSummary] = []
    references: dict[tuple[str, str], list[tuple[Path, str]]] = {}
    for root, source in roots:
        for manifest_path in sorted(root.glob("*/*/manifest.json")):
            reference = (manifest_path.parent.parent.name, manifest_path.parent.name)
            references.setdefault(reference, []).append((root, source))
    for (style_id, revision), matches in sorted(references.items()):
        if len(matches) != 1:
            result.append(StyleSummary(
                style_id, revision, style_id, True, False, False,
                f"AMBIGUOUS_STYLE_REFERENCE:{style_id}@{revision}", "ambiguous",
            ))
            continue
        root, source = matches[0]
        try:
            snapshot = FileStyleRepository(root).load(style_id, revision)
            manifest = snapshot.manifest
            result.append(StyleSummary(
                style_id=style_id,
                revision=revision,
                display_name=manifest.display_name,
                test_only=manifest.test_only,
                production_eligible=manifest.production_eligible,
                valid=True,
                detail=f"Validated · {len(snapshot.variants_by_key)} glyph keys · {source}",
                source=source,
            ))
        except Exception as exc:  # catalog must expose broken packs instead of hiding them
            result.append(StyleSummary(
                style_id, revision, style_id, True, False, False, str(exc), source
            ))
    return tuple(result)
