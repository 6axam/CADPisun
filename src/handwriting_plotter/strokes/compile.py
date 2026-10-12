"""Compile authored execution groups to logical pen operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from handwriting_plotter.geometry.curves import Point2, Segment
from handwriting_plotter.layout.pages import Page


@dataclass(frozen=True, slots=True)
class EnsurePenUp:
    op_id: str
    op: Literal["ensure_pen_up"] = "ensure_pen_up"


@dataclass(frozen=True, slots=True)
class TravelTo:
    op_id: str
    target: Point2
    source_refs: tuple[str, ...]
    op: Literal["travel_to"] = "travel_to"


@dataclass(frozen=True, slots=True)
class PenDown:
    op_id: str
    op: Literal["pen_down"] = "pen_down"


@dataclass(frozen=True, slots=True)
class Draw:
    op_id: str
    stroke_ids: tuple[str, ...]
    segments: tuple[Segment, ...]
    source_refs: tuple[str, ...]
    op: Literal["draw"] = "draw"


@dataclass(frozen=True, slots=True)
class PenUp:
    op_id: str
    op: Literal["pen_up"] = "pen_up"


@dataclass(frozen=True, slots=True)
class Checkpoint:
    op_id: str
    scope: Literal["word", "page"]
    op: Literal["checkpoint"] = "checkpoint"


PenOperation: TypeAlias = EnsurePenUp | TravelTo | PenDown | Draw | PenUp | Checkpoint


@dataclass(frozen=True, slots=True)
class PenPlan:
    format: Literal["hp-pen-plan"]
    schema_version: Literal["1.0"]
    units: Literal["mm"]
    frame: Literal["PageFrame"]
    page_id: str
    operations: tuple[PenOperation, ...]
    source_document_hash: str


def compile_page(page: Page, source_document_hash: str) -> PenPlan:
    operations: list[PenOperation] = [EnsurePenUp("op-000000")]

    def op_id() -> str:
        return f"op-{len(operations):06d}"

    for line in page.lines:
        for word in line.words:
            for group in word.groups:
                if not group.strokes:
                    raise ValueError("EMPTY_EXECUTION_GROUP")
                segments = tuple(segment for stroke in group.strokes for segment in stroke.segments)
                for previous, current in zip(segments, segments[1:], strict=False):
                    if previous.p1 != current.p0:
                        raise ValueError("DISCONTINUOUS_EXECUTION_GROUP")
                operations.append(TravelTo(op_id(), segments[0].p0, group.source_refs))
                operations.append(PenDown(op_id()))
                operations.append(Draw(op_id(), tuple(stroke.id for stroke in group.strokes), segments, group.source_refs))
                operations.append(PenUp(op_id()))
            operations.append(Checkpoint(op_id(), "word"))
    operations.append(Checkpoint(op_id(), "page"))
    return PenPlan("hp-pen-plan", "1.0", "mm", "PageFrame", page.page_id, tuple(operations), source_document_hash)

