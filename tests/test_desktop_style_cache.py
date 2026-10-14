from __future__ import annotations

from handwriting_plotter.application.desktop import (
    CompositionRequest,
    CompositionTextBlock,
    DesktopApplicationAdapter,
)
from handwriting_plotter.layout.pages import PageSpec


def _request() -> CompositionRequest:
    blocks = tuple(
        CompositionTextBlock(
            object_id=f"block-{index}",
            name=f"Block {index}",
            text="Alpha",
            x_mm=15.0,
            y_mm=15.0 + index * 30.0,
            x_height_mm=3.5,
            line_pitch_mm=9.0,
            style_id="test-technical-v1",
            style_revision="1.0.0",
            seed=index,
            realism=0.35,
        )
        for index in range(3)
    )
    return CompositionRequest("style-cache-test", PageSpec(), blocks)


def test_style_revision_is_loaded_once_per_build_and_reverified_next_build(monkeypatch) -> None:
    adapter = DesktopApplicationAdapter()
    original_load = adapter.style_repository.load
    calls: list[tuple[str, str]] = []

    def counted_load(style_id: str, revision: str):
        calls.append((style_id, revision))
        return original_load(style_id, revision)

    monkeypatch.setattr(adapter.style_repository, "load", counted_load)

    adapter.build(_request())
    assert calls == [("test-technical-v1", "1.0.0")]

    adapter.build(_request())
    assert calls == [
        ("test-technical-v1", "1.0.0"),
        ("test-technical-v1", "1.0.0"),
    ]
