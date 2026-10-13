"""Portable desktop project model, persistence, and undoable state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads


class PageSettings(StrictModel):
    width_mm: float = Field(default=210.0, gt=0)
    height_mm: float = Field(default=297.0, gt=0)
    margin_left_mm: float = Field(default=15.0, ge=0)
    margin_right_mm: float = Field(default=15.0, ge=0)
    margin_top_mm: float = Field(default=15.0, ge=0)
    margin_bottom_mm: float = Field(default=15.0, ge=0)
    paragraph_gap_mm: float = Field(default=4.0, ge=0)
    pen_width_mm: float = Field(default=0.35, gt=0)

    @field_validator("margin_bottom_mm")
    @classmethod
    def printable_area_exists(cls, value: float, info) -> float:  # noqa: ANN001
        data = info.data
        if data.get("margin_left_mm", 0) + data.get("margin_right_mm", 0) >= data.get("width_mm", 210):
            raise ValueError("horizontal margins consume page")
        if data.get("margin_top_mm", 0) + value >= data.get("height_mm", 297):
            raise ValueError("vertical margins consume page")
        return value


class TextObject(StrictModel):
    object_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    text: str = ""
    visible: bool = True
    x_mm: float = Field(default=15.0, ge=0, lt=210)
    y_mm: float = Field(default=15.0, ge=0, lt=297)
    x_height_mm: float = Field(default=3.5, gt=0, le=30)
    line_pitch_mm: float = Field(default=9.0, gt=0, le=100)
    style_id: str = Field(default="test-technical-v1", min_length=1)
    style_revision: str = Field(default="1.0.0", min_length=1)
    seed: int = 1
    realism: float = Field(default=0.35, ge=0, le=1)


class DisplaySettings(StrictModel):
    show_travel: bool = False
    show_markers: bool = False


class ProjectSnapshot(StrictModel):
    format: Literal["hp-desktop-project"] = "hp-desktop-project"
    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1)
    name: str = Field(default="Untitled", min_length=1, max_length=120)
    page: PageSettings = PageSettings()
    objects: tuple[TextObject, ...] = ()
    display: DisplaySettings = DisplaySettings()

    @field_validator("objects")
    @classmethod
    def unique_object_ids(cls, value: tuple[TextObject, ...]) -> tuple[TextObject, ...]:
        ids = [item.object_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate object id")
        return value


def default_project() -> ProjectSnapshot:
    return ProjectSnapshot(
        project_id=str(uuid4()),
        objects=(
            TextObject(
                object_id=str(uuid4()),
                name="Text 1",
                text="Handwriting Plotter",
            ),
        ),
    )


def project_bytes(snapshot: ProjectSnapshot) -> bytes:
    return canonical_json_bytes(snapshot.model_dump(mode="json")) + b"\n"


def load_project(path: Path) -> ProjectSnapshot:
    data = strict_json_loads(path.read_bytes())
    if not isinstance(data, dict) or data.get("format") != "hp-desktop-project":
        raise ValueError("NOT_A_DESKTOP_PROJECT")
    if data.get("schema_version") != "1.0":
        raise ValueError("UNSUPPORTED_PROJECT_SCHEMA")
    return ProjectSnapshot.model_validate_json(canonical_json_bytes(data), strict=True)


def save_project(path: Path, snapshot: ProjectSnapshot) -> None:
    """Atomically replace a project file in its destination directory."""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(project_bytes(snapshot))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class _ReplaceSnapshotCommand(QUndoCommand):
    def __init__(self, controller: "DocumentController", before: ProjectSnapshot, after: ProjectSnapshot, text: str) -> None:
        super().__init__(text)
        self._controller = controller
        self._before = before
        self._after = after

    def redo(self) -> None:
        self._controller._replace(self._after)

    def undo(self) -> None:
        self._controller._replace(self._before)


class DocumentController(QObject):
    snapshot_changed = Signal(object, int)
    dirty_changed = Signal(bool)
    path_changed = Signal(object)

    def __init__(self, snapshot: ProjectSnapshot | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.snapshot = snapshot or default_project()
        self.revision = 0
        self.path: Path | None = None
        self.undo_stack = QUndoStack(self)
        self._saved_bytes = project_bytes(self.snapshot)
        self._dirty = False

    @property
    def dirty(self) -> bool:
        return self._dirty

    def apply(self, snapshot: ProjectSnapshot, description: str) -> None:
        if snapshot == self.snapshot:
            return
        self.undo_stack.push(_ReplaceSnapshotCommand(self, self.snapshot, snapshot, description))

    def _replace(self, snapshot: ProjectSnapshot) -> None:
        self.snapshot = snapshot
        self.revision += 1
        dirty = project_bytes(snapshot) != self._saved_bytes
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self.snapshot_changed.emit(snapshot, self.revision)

    def reset(self, snapshot: ProjectSnapshot, path: Path | None = None) -> None:
        self.undo_stack.clear()
        self.snapshot = snapshot
        self.path = path
        self.revision += 1
        self._saved_bytes = project_bytes(snapshot)
        dirty_changed = self._dirty
        self._dirty = False
        if dirty_changed:
            self.dirty_changed.emit(False)
        self.path_changed.emit(path)
        self.snapshot_changed.emit(snapshot, self.revision)

    def mark_saved(self, path: Path) -> None:
        self.path = path
        self._saved_bytes = project_bytes(self.snapshot)
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self.path_changed.emit(path)

    def add_text_object(self) -> TextObject:
        count = len(self.snapshot.objects) + 1
        item = TextObject(object_id=str(uuid4()), name=f"Text {count}", text="New text")
        self.apply(self.snapshot.model_copy(update={"objects": self.snapshot.objects + (item,)}), "Add text object")
        return item

    def remove_text_object(self, object_id: str) -> None:
        objects = tuple(item for item in self.snapshot.objects if item.object_id != object_id)
        if len(objects) == len(self.snapshot.objects):
            return
        self.apply(self.snapshot.model_copy(update={"objects": objects}), "Delete text object")

    def update_text_object(self, object_id: str, **changes) -> None:  # noqa: ANN003
        objects = tuple(
            item.model_copy(update=changes) if item.object_id == object_id else item
            for item in self.snapshot.objects
        )
        if not any(item.object_id == object_id for item in self.snapshot.objects):
            raise KeyError(object_id)
        validated = ProjectSnapshot.model_validate(
            self.snapshot.model_copy(update={"objects": objects}).model_dump(mode="python"), strict=True
        )
        self.apply(validated, "Edit text object")

    def update_page(self, **changes) -> None:  # noqa: ANN003
        page = PageSettings.model_validate(self.snapshot.page.model_copy(update=changes).model_dump(), strict=True)
        self.apply(self.snapshot.model_copy(update={"page": page}), "Edit page")
