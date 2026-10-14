from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from handwriting_plotter.gui.main_window import MainWindow


def test_text_content_edit_does_not_rebuild_tree_or_canvas_overlays(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    item = window.controller.snapshot.objects[0]
    tree_refreshes = 0
    canvas_refreshes = 0
    original_tree_refresh = window._refresh_tree
    original_canvas_refresh = window.canvas.set_object_frames

    def count_tree(*args, **kwargs):
        nonlocal tree_refreshes
        tree_refreshes += 1
        return original_tree_refresh(*args, **kwargs)

    def count_canvas(*args, **kwargs):
        nonlocal canvas_refreshes
        canvas_refreshes += 1
        return original_canvas_refresh(*args, **kwargs)

    monkeypatch.setattr(window, "_refresh_tree", count_tree)
    monkeypatch.setattr(window.canvas, "set_object_frames", count_canvas)

    try:
        window.controller.update_text_object(item.object_id, text="Changed")

        assert tree_refreshes == 0
        assert canvas_refreshes == 0
    finally:
        window.controller.reset(window.controller.snapshot)


def test_only_affected_gui_structure_is_refreshed(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    item = window.controller.snapshot.objects[0]
    tree_refreshes = 0
    canvas_refreshes = 0
    original_tree_refresh = window._refresh_tree
    original_canvas_refresh = window.canvas.set_object_frames

    def count_tree(*args, **kwargs):
        nonlocal tree_refreshes
        tree_refreshes += 1
        return original_tree_refresh(*args, **kwargs)

    def count_canvas(*args, **kwargs):
        nonlocal canvas_refreshes
        canvas_refreshes += 1
        return original_canvas_refresh(*args, **kwargs)

    monkeypatch.setattr(window, "_refresh_tree", count_tree)
    monkeypatch.setattr(window.canvas, "set_object_frames", count_canvas)

    try:
        window.controller.update_text_object(item.object_id, name="Renamed")
        assert (tree_refreshes, canvas_refreshes) == (1, 0)

        window.controller.update_text_object(item.object_id, frame_width_mm=61.0)
        assert (tree_refreshes, canvas_refreshes) == (1, 1)
    finally:
        window.controller.reset(window.controller.snapshot)
