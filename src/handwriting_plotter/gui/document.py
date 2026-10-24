"""Portable desktop project model, persistence, and undoable state."""

from __future__ import annotations

import base64
import os
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from .notebook_templates import NotebookPageTemplate

from handwriting_plotter.application.service import GenerationResult
from handwriting_plotter.domain.models import (
    StrictModel,
    canonical_json_bytes,
    strict_json_loads,
)


TEXT_COLOR_GROUPS: tuple[str, ...] = (
    "#1F2937", "#DC2626", "#EA580C", "#CA8A04",
    "#16A34A", "#0D9488", "#0891B2", "#2563EB",
    "#4F46E5", "#7C3AED", "#C026D3", "#DB2777",
    "#6B7280", "#92400E", "#65A30D", "#0F766E",
)


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
    kind: Literal["text"] = "text"
    object_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    text: str = ""
    visible: bool = True
    x_mm: float = Field(default=15.0, ge=0, lt=210)
    y_mm: float = Field(default=15.0, ge=0, lt=297)
    frame_x_mm: float = Field(default=15.0, ge=0, lt=210)
    frame_y_mm: float = Field(default=15.0, ge=0, lt=297)
    frame_width_mm: float = Field(default=60.0, gt=0, le=210)
    frame_height_mm: float = Field(default=30.0, gt=0, le=297)
    x_height_mm: float = Field(default=3.5, gt=0, le=30)
    line_pitch_mm: float = Field(default=9.0, gt=0, le=100)
    character_spacing_mm: float = Field(default=0.0, ge=0, le=30)
    rotation_deg: float = Field(default=0.0, ge=-180, le=180)
    display_diameter_mm: float = Field(default=3.0, ge=1, le=20)
    color_group: int = Field(default=0, ge=0, lt=16)
    style_id: str = Field(default="test-technical-v1", min_length=1)
    style_revision: str = Field(default="1.0.0", min_length=1)
    seed: int = Field(default=1, ge=0, lt=2**64)
    realism: float = Field(default=0.35, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def default_frame_origin_to_text(cls, value):  # noqa: ANN001
        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("frame_x_mm", value.get("x_mm", 15.0))
            value.setdefault("frame_y_mm", value.get("y_mm", 15.0))
        return value

    @model_validator(mode="after")
    def frame_fits_a4(self) -> "TextObject":
        if self.frame_x_mm + self.frame_width_mm > 210:
            raise ValueError("text object frame exceeds page width")
        if self.frame_y_mm + self.frame_height_mm > 297:
            raise ValueError("text object frame exceeds page height")
        return self


class GridObject(StrictModel):
    kind: Literal["grid"] = "grid"
    object_id: str = Field(min_length=1)
    name: str = Field(default="Grid", min_length=1, max_length=120)
    visible: bool = True
    x_mm: float = Field(default=15.0, ge=0, lt=297)
    y_mm: float = Field(default=15.0, ge=0, lt=297)
    width_mm: float = Field(default=180.0, gt=0, le=297)
    height_mm: float = Field(default=267.0, gt=0, le=297)
    cell_width_mm: float = Field(default=5.0, ge=1.0, le=297)
    cell_height_mm: float = Field(default=5.0, ge=1.0, le=297)
    line_style: Literal["solid", "dashed", "dash_dot"] = "solid"
    color: str = Field(default="#8BA1BD", pattern=r"^#[0-9A-Fa-f]{6}$")
    snap_enabled: bool = True

    @model_validator(mode="after")
    def grid_fits_a4(self) -> "GridObject":
        if self.x_mm + self.width_mm > 210:
            raise ValueError("grid exceeds page width")
        if self.y_mm + self.height_mm > 297:
            raise ValueError("grid exceeds page height")
        return self


class ArtworkObject(StrictModel):
    """Portable visual reference; never converted to plotter strokes implicitly."""

    kind: Literal["artwork"] = "artwork"
    object_id: str = Field(min_length=1)
    name: str = Field(default="Artwork", min_length=1, max_length=120)
    visible: bool = True
    media_type: Literal[
        "image/svg+xml", "image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"
    ]
    data_base64: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    x_mm: float = Field(default=15.0, ge=0, lt=297)
    y_mm: float = Field(default=15.0, ge=0, lt=297)
    width_mm: float = Field(default=80.0, gt=0, le=297)
    height_mm: float = Field(default=80.0, gt=0, le=297)
    opacity: float = Field(default=0.7, ge=0.05, le=1.0)

    @model_validator(mode="after")
    def artwork_is_valid(self) -> "ArtworkObject":
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
        except ValueError as exc:
            raise ValueError("invalid artwork base64") from exc
        if sha256(raw).hexdigest() != self.sha256:
            raise ValueError("artwork SHA-256 mismatch")
        if self.x_mm + self.width_mm > 210:
            raise ValueError("artwork exceeds page width")
        if self.y_mm + self.height_mm > 297:
            raise ValueError("artwork exceeds page height")
        return self

    def content(self) -> bytes:
        return base64.b64decode(self.data_base64, validate=True)


ProjectObject = Annotated[TextObject | GridObject | ArtworkObject, Field(discriminator="kind")]


class DisplaySettings(StrictModel):
    show_travel: bool = False
    show_markers: bool = False


class ProjectSnapshot(StrictModel):
    format: Literal["hp-desktop-project"] = "hp-desktop-project"
    schema_version: Literal["1.6"] = "1.6"
    project_id: str = Field(min_length=1)
    name: str = Field(default="Untitled", min_length=1, max_length=120)
    page: PageSettings = PageSettings()
    notebook_template: NotebookPageTemplate | None = None
    objects: tuple[ProjectObject, ...] = ()
    display: DisplaySettings = DisplaySettings()

    @field_validator("objects")
    @classmethod
    def unique_object_ids(cls, value: tuple[ProjectObject, ...]) -> tuple[ProjectObject, ...]:
        ids = [item.object_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate object id")
        return value

    @model_validator(mode="after")
    def objects_fit_current_page(self) -> "ProjectSnapshot":
        for item in self.objects:
            if isinstance(item, TextObject):
                right, bottom = item.frame_x_mm + item.frame_width_mm, item.frame_y_mm + item.frame_height_mm
            else:
                right, bottom = item.x_mm + item.width_mm, item.y_mm + item.height_mm
            if right > self.page.width_mm + 1e-9 or bottom > self.page.height_mm + 1e-9:
                raise ValueError("object exceeds current page dimensions")
        return self


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
    if version not in {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"}:
        raise ValueError("UNSUPPORTED_PROJECT_SCHEMA")
    cache_data = data.pop("generation_cache", None)
    if version in {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5"}:
        migrated_objects = []
        for item in data.get("objects", []):
            migrated = dict(item)
            migrated.setdefault("kind", "text")
            if migrated["kind"] == "text":
                if version in {"1.0", "1.1", "1.2"}:
                    migrated.setdefault("frame_x_mm", migrated.get("x_mm", 15.0))
                    migrated.setdefault("frame_y_mm", migrated.get("y_mm", 15.0))
                    migrated.setdefault("frame_width_mm", min(60.0, 210.0 - migrated["frame_x_mm"]))
                    migrated.setdefault("frame_height_mm", min(30.0, 297.0 - migrated["frame_y_mm"]))
                migrated.setdefault("character_spacing_mm", 0.0)
                migrated.setdefault("rotation_deg", 0.0)
                migrated.setdefault("display_diameter_mm", 3.0)
                migrated.setdefault("color_group", 0)
            migrated_objects.append(migrated)
        data["objects"] = migrated_objects
        data["schema_version"] = "1.6"
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
    MERGE_WINDOW_SECONDS = 1.5

    def __init__(
        self,
        controller: "DocumentController",
        before: ProjectSnapshot,
        after: ProjectSnapshot,
        text: str,
        merge_key: str | None = None,
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._before = before
        self._after = after
        self._merge_key = merge_key
        self._updated_at = time.monotonic()

    def id(self) -> int:  # noqa: A003 - Qt API
        return 1 if self._merge_key is not None else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt API
        if not isinstance(other, _ReplaceSnapshotCommand):
            return False
        if self._controller is not other._controller or self._merge_key != other._merge_key:
            return False
        if other._updated_at - self._updated_at > self.MERGE_WINDOW_SECONDS:
            return False
        self._after = other._after
        self._updated_at = other._updated_at
        return True

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

    def apply(self, snapshot: ProjectSnapshot, description: str, merge_key: str | None = None) -> None:
        if snapshot == self.snapshot:
            return
        self.undo_stack.push(
            _ReplaceSnapshotCommand(self, self.snapshot, snapshot, description, merge_key)
        )

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
        count = sum(isinstance(item, TextObject) for item in self.snapshot.objects) + 1
        item = TextObject(object_id=str(uuid4()), name=f"Text {count}", text="New text")
        self.apply(self.snapshot.model_copy(update={"objects": self.snapshot.objects + (item,)}), "Add text object")
        return item

    def add_grid_object(self) -> GridObject:
        count = sum(isinstance(item, GridObject) for item in self.snapshot.objects) + 1
        item = GridObject(object_id=str(uuid4()), name=f"Grid {count}")
        self.apply(self.snapshot.model_copy(update={"objects": self.snapshot.objects + (item,)}), "Add grid object")
        return item

    def add_artwork_object(self, item: ArtworkObject) -> ArtworkObject:
        if any(existing.object_id == item.object_id for existing in self.snapshot.objects):
            raise ValueError("duplicate artwork object id")
        self.apply(
            self.snapshot.model_copy(update={"objects": self.snapshot.objects + (item,)}),
            "Import artwork",
        )
        return item

    def remove_text_object(self, object_id: str) -> None:
        self.remove_objects({object_id})

    def remove_text_objects(self, object_ids: set[str]) -> None:
        self.remove_objects(object_ids)

    def remove_objects(self, object_ids: set[str]) -> None:
        objects = tuple(item for item in self.snapshot.objects if item.object_id not in object_ids)
        if len(objects) == len(self.snapshot.objects):
            return
        description = "Delete object" if len(self.snapshot.objects) - len(objects) == 1 else "Delete objects"
        self.apply(self.snapshot.model_copy(update={"objects": objects}), description)

    def update_text_object(
        self,
        object_id: str,
        *,
        undo_merge_key: str | None = None,
        **changes,
    ) -> None:  # noqa: ANN003
        if not any(isinstance(item, TextObject) and item.object_id == object_id for item in self.snapshot.objects):
            raise KeyError(object_id)
        self._update_object(object_id, changes, "Edit text object", merge_key=undo_merge_key)

    def update_grid_object(self, object_id: str, **changes) -> None:  # noqa: ANN003
        if not any(isinstance(item, GridObject) and item.object_id == object_id for item in self.snapshot.objects):
            raise KeyError(object_id)
        self._update_object(object_id, changes, "Edit grid object")

    def update_artwork_object(self, object_id: str, **changes) -> None:  # noqa: ANN003
        if not any(isinstance(item, ArtworkObject) and item.object_id == object_id for item in self.snapshot.objects):
            raise KeyError(object_id)
        self._update_object(object_id, changes, "Edit artwork")

    def _update_object(
        self,
        object_id: str,
        changes: dict,
        description: str,
        *,
        merge_key: str | None = None,
    ) -> None:
        objects = tuple(
            item.model_copy(update=changes) if item.object_id == object_id else item
            for item in self.snapshot.objects
        )
        validated = ProjectSnapshot.model_validate(
            self.snapshot.model_copy(update={"objects": objects}).model_dump(mode="python"), strict=True
        )
        self.apply(validated, description, merge_key)

    def move_objects(self, object_ids: set[str], dx_mm: float, dy_mm: float) -> None:
        if not object_ids or (abs(dx_mm) <= 1e-9 and abs(dy_mm) <= 1e-9):
            return
        known_ids = {item.object_id for item in self.snapshot.objects}
        if not object_ids <= known_ids:
            raise KeyError(sorted(object_ids - known_ids)[0])
        objects = tuple(
            item.model_copy(update=(
                {
                    "x_mm": item.x_mm + dx_mm,
                    "y_mm": item.y_mm + dy_mm,
                    "frame_x_mm": item.frame_x_mm + dx_mm,
                    "frame_y_mm": item.frame_y_mm + dy_mm,
                }
                if isinstance(item, TextObject)
                else {"x_mm": item.x_mm + dx_mm, "y_mm": item.y_mm + dy_mm}
            )) if item.object_id in object_ids else item
            for item in self.snapshot.objects
        )
        validated = ProjectSnapshot.model_validate(
            self.snapshot.model_copy(update={"objects": objects}).model_dump(mode="python"), strict=True
        )
        self.apply(validated, "Move object" if len(object_ids) == 1 else "Move objects")

    def move_text_objects(self, object_ids: set[str], dx_mm: float, dy_mm: float) -> None:
        self.move_objects(object_ids, dx_mm, dy_mm)

    def update_page(self, **changes) -> None:  # noqa: ANN003
        page = PageSettings.model_validate(self.snapshot.page.model_copy(update=changes).model_dump(), strict=True)
        self.apply(self.snapshot.model_copy(update={"page": page}), "Edit page")

    def set_notebook_template(self, template: NotebookPageTemplate | None) -> None:
        """Set visual paper and synchronise the A4 page geometry with its orientation."""

        if template is None:
            self.apply(self.snapshot.model_copy(update={"notebook_template": None}), "Clear notebook template")
            return
        width, height = template.page_size_mm
        page = PageSettings.model_validate(
            self.snapshot.page.model_copy(update={
                "width_mm": width, "height_mm": height,
                "margin_left_mm": template.margin_left_mm, "margin_right_mm": template.margin_right_mm,
                "margin_top_mm": template.margin_top_mm, "margin_bottom_mm": template.margin_bottom_mm,
            }).model_dump(), strict=True
        )
        self.apply(
            self.snapshot.model_copy(update={"page": page, "notebook_template": template}),
            "Set notebook template",
        )
