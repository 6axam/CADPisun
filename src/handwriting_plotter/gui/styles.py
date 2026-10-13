"""StylePack catalog presented by the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def reference(self) -> tuple[str, str]:
        return self.style_id, self.revision


def discover_styles() -> tuple[StyleSummary, ...]:
    root = style_root()
    repository = FileStyleRepository(root)
    result: list[StyleSummary] = []
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        style_id = manifest_path.parent.parent.name
        revision = manifest_path.parent.name
        try:
            snapshot = repository.load(style_id, revision)
            manifest = snapshot.manifest
            result.append(StyleSummary(
                style_id=style_id,
                revision=revision,
                display_name=manifest.display_name,
                test_only=manifest.test_only,
                production_eligible=manifest.production_eligible,
                valid=True,
                detail=f"Validated · {len(snapshot.by_key)} glyph keys",
            ))
        except Exception as exc:  # catalog must expose broken packs instead of hiding them
            result.append(StyleSummary(style_id, revision, style_id, True, False, False, str(exc)))
    return tuple(result)
