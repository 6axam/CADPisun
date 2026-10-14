"""Portable desktop project model, persistence, and undoable state."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from handwriting_plotter.application.service import GenerationResult
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
    seed: int = Field(default=1, ge=0, lt=2**64)
    realism: float = Field(default=0.35, ge=0, le=1)


class DisplaySettings(StrictModel):
    show_travel: bool = False
    show_markers: bool = False


class ProjectSnapshot(StrictModel):
    format: Literal["hp-desktop-project"] = "hp-desktop-project"
    schema_version: Literal["1.1"] = "1.1"
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


class CachedArtifact(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_base64: str


class GenerationCache(StrictModel):
    format: Literal["hp-desktop-generation-cache"] = "hp-desktop-generation-cache"
    schema_version: Literal["1.0"] = "1.0"
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(min_length=1)
    page_count: int = Field(ge=1)
    test_only_style: bool
    artifacts: dict[str, CachedArtifact]


@dataclass(frozen=True, slots=True)
class LoadedProject:
    snapshot: ProjectSnapshot
    generation_result: GenerationResult | None = None
    cache_warning: str | None = None


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


def _source_sha256(snapshot: ProjectSnapshot) -> str:
    return sha256(project_bytes(snapshot)).hexdigest()


def _encode_generation_cache(snapshot: ProjectSnapshot, result: GenerationResult) -> dict:
    artifacts = {
        name: CachedArtifact(
            sha256=sha256(content).hexdigest(),
            data_base64=base64.b64encode(content).decode("ascii"),
        )
        for name, content in sorted(result.files.items())
    }
    return GenerationCache(
        source_sha256=_source_sha256(snapshot),
        document_id=result.document_id,
        page_count=result.page_count,
        test_only_style=result.test_only_style,
        artifacts=artifacts,
    ).model_dump(mode="json")


def _decode_generation_cache(snapshot: ProjectSnapshot, raw: object) -> GenerationResult:
    cache = GenerationCache.model_validate(raw, strict=True)
    if cache.source_sha256 != _source_sha256(snapshot):
        raise ValueError("GENERATION_CACHE_SOURCE_MISMATCH")
    files: dict[str, bytes] = {}
    for name, artifact in cache.artifacts.items():
        try:
            content = base64.b64decode(artifact.data_base64, validate=True)
        except ValueError as exc:
            raise ValueError(f"GENERATION_CACHE_INVALID_BASE64:{name}") from exc
        if sha256(content).hexdigest() != artifact.sha256:
            raise ValueError(f"GENERATION_CACHE_HASH_MISMATCH:{name}")
        files[name] = content
    required = {
        "page-0001.svg",
        "page-0001.preview.svg",
        "page-0001.plan.json",
        "page-0001.gcode",
        "report.json",
    }
    missing = sorted(required - files.keys())
    if missing:
        raise ValueError("GENERATION_CACHE_MISSING_ARTIFACTS:" + ",".join(missing))
    report = strict_json_loads(files["report.json"])
    if not isinstance(report, dict) or report.get("document_id") != cache.document_id:
        raise ValueError("GENERATION_CACHE_REPORT_MISMATCH")
    if report.get("page_count") != cache.page_count:
        raise ValueError("GENERATION_CACHE_PAGE_COUNT_MISMATCH")
    return GenerationResult(cache.document_id, cache.page_count, files, report, cache.test_only_style)


def project_file_bytes(snapshot: ProjectSnapshot, result: GenerationResult | None = None) -> bytes:
    data = snapshot.model_dump(mode="json")
    if result is not None:
        data["generation_cache"] = _encode_generation_cache(snapshot, result)
    return canonical_json_bytes(data) + b"\n"


def load_project_file(path: Path) -> LoadedProject:
    data = strict_json_loads(path.read_bytes())
    if not isinstance(data, dict) or data.get("format") != "hp-desktop-project":
        raise ValueError("NOT_A_DESKTOP_PROJECT")
    version = data.get("schema_version")
    if version not in {"1.0", "1.1"}:
        raise ValueError("UNSUPPORTED_PROJECT_SCHEMA")
    cache_data = data.pop("generation_cache", None)
    if version == "1.0":
        data["schema_version"] = "1.1"
    snapshot = ProjectSnapshot.model_validate_json(canonical_json_bytes(data), strict=True)
    if cache_data is None:
        return LoadedProject(snapshot)
    try:
        result = _decode_generation_cache(snapshot, cache_data)
    except (TypeError, ValueError) as exc:
        return LoadedProject(snapshot, cache_warning=str(exc))
    return LoadedProject(snapshot, result)


def load_project(path: Path) -> ProjectSnapshot:
    return load_project_file(path).snapshot


def save_project(path: Path, snapshot: ProjectSnapshot, result: GenerationResult | None = None) -> None:
    """Atomically replace a project file in its destination directory."""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(project_file_bytes(snapshot, result))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _sync_directory(path: Path) -> None:
    """Persist a directory entry on platforms that allow directory handles."""

    if os.name == "nt":
        return
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


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
