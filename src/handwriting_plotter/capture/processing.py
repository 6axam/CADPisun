"""Deterministic raw-capture processing with a checked geometric error budget."""

from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Segment, Stroke
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment
from handwriting_plotter.styles.models import (
    CubicModel,
    LineModel,
    PointModel,
    QuadraticModel,
    SegmentModel,
    StrokeModel,
    to_segment,
)

from .models import CaptureSample
from .repository import CaptureRepository

MAX_PROCESSED_BYTES = 32 * 1024 * 1024
MAX_PROCESSING_POINTS = 2_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProcessingParameters(StrictModel):
    """All values that can affect deterministic processed geometry."""

    algorithm: Literal["cadpisun-directed-fit-v1"] = "cadpisun-directed-fit-v1"
    max_deviation_px: float = Field(default=1.0, ge=0.05, le=100.0)
    duplicate_epsilon_px: float = Field(default=0.01, ge=0.0, le=10.0)
    resample_spacing_px: float = Field(default=1.0, ge=0.05, le=100.0)
    smoothing_passes: int = Field(default=0, ge=0, le=8)
    corner_angle_deg: float = Field(default=42.0, ge=5.0, le=175.0)

    @field_validator(
        "max_deviation_px", "duplicate_epsilon_px", "resample_spacing_px", "corner_angle_deg"
    )
    @classmethod
    def finite_parameters(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("processing parameter must be finite")
        return value


class StrokeProcessingReport(StrictModel):
    stroke_id: str = Field(min_length=1, max_length=128)
    raw_points: int = Field(ge=2)
    duplicate_filtered_points: int = Field(ge=1)
    resampled_points: int = Field(ge=1)
    output_segments: int = Field(ge=1)
    measured_max_deviation_px: float = Field(ge=0)
    certified_max_deviation_px: float = Field(ge=0)
    measurement_resolution_px: float = Field(gt=0)
    fitting: Literal["bezier", "polyline", "point-mark"]


class ProcessedCapture(StrictModel):
    """Immutable derivative; the raw capture remains the source of truth."""

    format: Literal["hp-processed-capture"] = "hp-processed-capture"
    schema_version: Literal["1.0"] = "1.0"
    processed_id: str = Field(min_length=1, max_length=128)
    source_capture_sha256: str
    source_sample_id: str = Field(min_length=1, max_length=128)
    coordinate_unit: Literal["logical_px"] = "logical_px"
    frame_width: float = Field(gt=0)
    frame_height: float = Field(gt=0)
    parameters: ProcessingParameters
    strokes: tuple[StrokeModel, ...]
    reports: tuple[StrokeProcessingReport, ...]

    @field_validator("source_capture_sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("INVALID_CAPTURE_HASH")
        return value

    @model_validator(mode="after")
    def consistent_geometry(self) -> ProcessedCapture:
        if not self.strokes:
            raise ValueError("processed capture must contain strokes")
        if tuple(item.id for item in self.strokes) != tuple(item.stroke_id for item in self.reports):
            raise ValueError("processed reports must match stroke order")
        for stroke, report in zip(self.strokes, self.reports, strict=True):
            segments = tuple(to_segment(segment) for segment in stroke.segments)
            for previous, current in zip(segments, segments[1:], strict=False):
                if previous.p1 != current.p0:
                    raise ValueError(f"discontinuous processed stroke {stroke.id}")
            if report.certified_max_deviation_px > self.parameters.max_deviation_px + 1e-9:
                raise ValueError("PROCESSING_DEVIATION_EXCEEDED")
        return self

    def to_strokes(self) -> tuple[Stroke, ...]:
        """Return runtime geometry; coordinates remain in capture logical pixels."""
        return tuple(
            Stroke(
                item.id,
                tuple(to_segment(segment) for segment in item.segments),
                item.source_refs,
                item.role,
                item.direction_provenance,
            )
            for item in self.strokes
        )


def _point_data(point: Point2) -> PointModel:
    return PointModel(x=point.x, y=point.y)


def _segment_data(segment: Segment) -> SegmentModel:
    if isinstance(segment, Line):
        return LineModel(kind="line", p0=_point_data(segment.p0), p1=_point_data(segment.p1))
    if isinstance(segment, Cubic):
        return CubicModel(
            kind="cubic", p0=_point_data(segment.p0), c1=_point_data(segment.c1),
            c2=_point_data(segment.c2), p1=_point_data(segment.p1),
        )
    if isinstance(segment, Quadratic):
        return QuadraticModel(
            kind="quadratic", p0=_point_data(segment.p0), c1=_point_data(segment.c1),
            p1=_point_data(segment.p1),
        )
    raise TypeError("unsupported fitted segment")


def _deduplicate(points: list[Point2], epsilon: float) -> list[Point2]:
    result = [points[0]]
    for point in points[1:-1]:
        if point.distance_to(result[-1]) > epsilon:
            result.append(point)
    if points[-1].distance_to(result[-1]) > epsilon:
        result.append(points[-1])
    elif len(result) > 1:
        # The captured endpoint is authoritative even when it is very close.
        result[-1] = points[-1]
    return result


def _resample(points: list[Point2], spacing: float) -> list[Point2]:
    """Sample each source edge and retain every original vertex exactly."""
    if len(points) < 2:
        return points[:]
    result = [points[0]]
    for start, end in zip(points, points[1:], strict=False):
        distance = start.distance_to(end)
        if distance == 0:
            continue
        parts = max(1, math.ceil(distance / spacing))
        result.extend(start.lerp(end, index / parts) for index in range(1, parts + 1))
    return result


def _turn_angle(previous: Point2, point: Point2, following: Point2) -> float:
    ax, ay = point.x - previous.x, point.y - previous.y
    bx, by = following.x - point.x, following.y - point.y
    a_length, b_length = math.hypot(ax, ay), math.hypot(bx, by)
    if a_length == 0 or b_length == 0:
        return 180.0
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (a_length * b_length)))
    return math.degrees(math.acos(cosine))


def _corner_indices(points: list[Point2], threshold: float) -> set[int]:
    corners = {0, len(points) - 1}
    for index in range(1, len(points) - 1):
        if _turn_angle(points[index - 1], points[index], points[index + 1]) >= threshold:
            corners.add(index)
    if len(points) > 2 and points[0] == points[-1]:
        anchor = max(range(1, len(points) - 1), key=lambda index: points[index].distance_to(points[0]))
        corners.add(anchor)
    return corners


def _smooth(points: list[Point2], passes: int, protected: set[int]) -> list[Point2]:
    result = points[:]
    for _ in range(passes):
        previous = result
        result = previous[:]
        for index in range(1, len(previous) - 1):
            if index not in protected:
                result[index] = Point2(
                    (previous[index - 1].x + 2 * previous[index].x + previous[index + 1].x) / 4,
                    (previous[index - 1].y + 2 * previous[index].y + previous[index + 1].y) / 4,
                )
    return result


def _distance_to_line(point: Point2, start: Point2, end: Point2) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return point.distance_to(start)
    t = max(0.0, min(1.0, ((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator))
    offset_x = point.x - (start.x + t * dx)
    offset_y = point.y - (start.y + t * dy)
    return math.hypot(offset_x, offset_y)


def _rdp_indices(points: list[Point2], start: int, end: int, tolerance: float) -> list[int]:
    if end <= start + 1:
        return [start, end]
    farthest = -1.0
    farthest_index = start
    for index in range(start + 1, end):
        distance = _distance_to_line(points[index], points[start], points[end])
        if distance > farthest:
            farthest, farthest_index = distance, index
    if farthest <= tolerance:
        return [start, end]
    left = _rdp_indices(points, start, farthest_index, tolerance)
    right = _rdp_indices(points, farthest_index, end, tolerance)
    return [*left[:-1], *right]


def _simplify(points: list[Point2], tolerance: float, corners: set[int]) -> tuple[list[Point2], set[int]]:
    boundaries = sorted(corners | {0, len(points) - 1})
    retained: list[int] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        span = _rdp_indices(points, start, end, tolerance)
        retained.extend(span if not retained else span[1:])
    simplified = [points[index] for index in retained]
    protected = {position for position, original in enumerate(retained) if original in corners}
    return simplified, protected


def _fit_segments(points: list[Point2], corners: set[int]) -> tuple[Segment, ...]:
    """Fit local Catmull-Rom cubics; exact corners get zero tangent handles."""
    if len(points) == 3 and 1 not in corners:
        start, midpoint, end = points
        control = Point2(
            2 * midpoint.x - (start.x + end.x) / 2,
            2 * midpoint.y - (start.y + end.y) / 2,
        )
        return (Quadratic(start, control, end),)
    output: list[Segment] = []
    for index, (start, end) in enumerate(zip(points, points[1:], strict=False)):
        before = points[index - 1] if index else start
        after = points[index + 2] if index + 2 < len(points) else end
        c1 = start if index in corners else Point2(
            start.x + (end.x - before.x) / 6,
            start.y + (end.y - before.y) / 6,
        )
        c2 = end if index + 1 in corners else Point2(
            end.x - (after.x - start.x) / 6,
            end.y - (after.y - start.y) / 6,
        )
        if _distance_to_line(c1, start, end) <= 1e-9 and _distance_to_line(c2, start, end) <= 1e-9:
            output.append(Line(start, end))
        else:
            output.append(Cubic(start, c1, c2, end))
    return tuple(output)


def _lines(points: list[Point2]) -> tuple[Line, ...]:
    return tuple(Line(start, end) for start, end in zip(points, points[1:], strict=False) if start != end)


def _sample_polyline(points: list[Point2], resolution: float) -> list[Point2]:
    if len(points) == 1:
        return points[:]
    sampled = [points[0]]
    for start, end in zip(points, points[1:], strict=False):
        pieces = max(1, math.ceil(start.distance_to(end) / resolution))
        sampled.extend(start.lerp(end, index / pieces) for index in range(1, pieces + 1))
    return sampled


def _segment_polyline(segments: tuple[Segment, ...], flatness: float, resolution: float) -> list[Point2]:
    points: list[Point2] = []
    for segment in segments:
        # Flatness controls geometric error. A much shorter chord only creates
        # redundant line segments and makes the symmetric distance check
        # quadratic in thousands of nearly collinear pieces.
        chord = max(2.0, resolution * 8)
        lines, _ = flatten_segment(
            segment,
            flatness,
            FlattenLimits(max_depth=32, max_segments=1_000_000, max_chord_length=chord),
        )
        current = [lines[0].p0, *[line.p1 for line in lines]]
        if points and current[0] == points[-1]:
            points.extend(current[1:])
        else:
            points.extend(current)
    return points


def _distance_to_polyline(point: Point2, polyline: list[Point2]) -> float:
    if len(polyline) == 1:
        return point.distance_to(polyline[0])
    px, py = point.x, point.y
    best_squared = math.inf
    for index in range(len(polyline) - 1):
        start, end = polyline[index], polyline[index + 1]
        dx, dy = end.x - start.x, end.y - start.y
        denominator = dx * dx + dy * dy
        if denominator == 0:
            offset_x, offset_y = px - start.x, py - start.y
        else:
            t = ((px - start.x) * dx + (py - start.y) * dy) / denominator
            if t <= 0:
                offset_x, offset_y = px - start.x, py - start.y
            elif t >= 1:
                offset_x, offset_y = px - end.x, py - end.y
            else:
                offset_x = px - (start.x + t * dx)
                offset_y = py - (start.y + t * dy)
        squared = offset_x * offset_x + offset_y * offset_y
        if squared < best_squared:
            best_squared = squared
            if squared == 0:
                break
    return math.sqrt(best_squared)


def _error_bound(
    source: list[Point2], segments: tuple[Segment, ...], tolerance: float
) -> tuple[float, float, float]:
    resolution = max(0.02, min(0.5, tolerance / 4))
    flatness = max(0.0005, tolerance / 128)
    output_polyline = _segment_polyline(segments, flatness, resolution)
    source_samples = _sample_polyline(source, resolution)
    output_samples = _sample_polyline(output_polyline, resolution)
    measured = max(
        max(_distance_to_polyline(point, output_polyline) for point in source_samples),
        max(_distance_to_polyline(point, source) for point in output_samples),
    )
    # Distance-to-set is 1-Lipschitz along each sampled polyline. Every point is
    # within resolution/2 of a sample; flatness also bounds curve-to-chord error.
    certified = measured + resolution / 2 + flatness
    return measured, certified, resolution


def _point_mark(point: Point2, sample: CaptureSample, tolerance: float) -> tuple[Line, Line]:
    radius = min(0.25, tolerance / 4)
    if point.x + radius <= sample.coordinate_reference.width:
        tip = Point2(point.x + radius, point.y)
    elif point.x - radius >= 0:
        tip = Point2(point.x - radius, point.y)
    elif point.y + radius <= sample.coordinate_reference.height:
        tip = Point2(point.x, point.y + radius)
    else:
        tip = Point2(point.x, point.y - radius)
    return Line(point, tip), Line(tip, point)


def _process_stroke(sample: CaptureSample, index: int, parameters: ProcessingParameters):
    captured = sample.strokes[index]
    raw = [Point2(point.x, point.y) for point in captured.points]
    filtered = _deduplicate(raw, parameters.duplicate_epsilon_px)
    if len(filtered) == 1:
        segments: tuple[Segment, ...] = _point_mark(filtered[0], sample, parameters.max_deviation_px)
        fitting: Literal["bezier", "polyline", "point-mark"] = "point-mark"
        resampled = filtered
    else:
        resampled = _resample(filtered, parameters.resample_spacing_px)
        corners = _corner_indices(resampled, parameters.corner_angle_deg)
        smoothed = _smooth(resampled, parameters.smoothing_passes, corners)
        simplified, simplified_corners = _simplify(
            smoothed, parameters.max_deviation_px * 0.55, corners
        )
        segments = _fit_segments(simplified, simplified_corners)
        fitting = "bezier" if any(isinstance(item, (Quadratic, Cubic)) for item in segments) else "polyline"

    measured, certified, resolution = _error_bound(filtered, segments, parameters.max_deviation_px)
    if certified > parameters.max_deviation_px and len(filtered) > 1:
        corners = _corner_indices(filtered, parameters.corner_angle_deg)
        simplified, _ = _simplify(filtered, parameters.max_deviation_px * 0.5, corners)
        segments = _lines(simplified)
        fitting = "polyline"
        measured, certified, resolution = _error_bound(filtered, segments, parameters.max_deviation_px)
    if certified > parameters.max_deviation_px and len(filtered) > 1:
        segments = _lines(filtered)
        fitting = "polyline"
        measured, certified, resolution = _error_bound(filtered, segments, parameters.max_deviation_px)
    if certified > parameters.max_deviation_px:
        raise ValueError("PROCESSING_DEVIATION_EXCEEDED")
    if segments[0].p0 != filtered[0] or segments[-1].p1 != filtered[-1]:
        raise ValueError("PROCESSING_DIRECTION_CHANGED")

    path_length = sum(a.distance_to(b) for a, b in zip(filtered, filtered[1:], strict=False))
    role = "mark" if fitting == "point-mark" or path_length <= parameters.max_deviation_px * 2 else "body"
    stroke = StrokeModel(
        id=captured.stroke_id,
        segments=tuple(_segment_data(segment) for segment in segments),
        source_refs=(sample.sample_id, captured.stroke_id),
        role=role,
        direction_provenance="captured",
    )
    report = StrokeProcessingReport(
        stroke_id=captured.stroke_id,
        raw_points=len(raw),
        duplicate_filtered_points=len(filtered),
        resampled_points=len(resampled),
        output_segments=len(segments),
        measured_max_deviation_px=measured,
        certified_max_deviation_px=certified,
        measurement_resolution_px=resolution,
        fitting=fitting,
    )
    return stroke, report


def process_sample(
    sample: CaptureSample,
    source_capture_sha256: str,
    parameters: ProcessingParameters = ProcessingParameters(),
) -> ProcessedCapture:
    """Create deterministic directed geometry without mutating the raw sample."""
    if not _SHA256.fullmatch(source_capture_sha256):
        raise ValueError("INVALID_CAPTURE_HASH")
    estimated_points = 0
    for captured in sample.strokes:
        points = captured.points
        estimated_points += 1
        for start, end in zip(points, points[1:], strict=False):
            estimated_points += max(
                1,
                math.ceil(math.hypot(end.x - start.x, end.y - start.y) / parameters.resample_spacing_px),
            )
            if estimated_points > MAX_PROCESSING_POINTS:
                raise ValueError("PROCESSING_POINT_BUDGET_EXCEEDED")
    pairs = tuple(_process_stroke(sample, index, parameters) for index in range(len(sample.strokes)))
    identity = canonical_json_bytes({
        "source_capture_sha256": source_capture_sha256,
        "source_sample_id": sample.sample_id,
        "parameters": parameters.model_dump(mode="json"),
    })
    return ProcessedCapture(
        processed_id=f"processed-{sha256(identity).hexdigest()[:24]}",
        source_capture_sha256=source_capture_sha256,
        source_sample_id=sample.sample_id,
        frame_width=sample.coordinate_reference.width,
        frame_height=sample.coordinate_reference.height,
        parameters=parameters,
        strokes=tuple(item[0] for item in pairs),
        reports=tuple(item[1] for item in pairs),
    )


def serialize_processed(value: ProcessedCapture) -> bytes:
    return canonical_json_bytes(value.model_dump(mode="json"))


def load_processed_bytes(data: bytes) -> ProcessedCapture:
    if len(data) > MAX_PROCESSED_BYTES:
        raise ValueError("PROCESSED_FILE_TOO_LARGE")
    decoded = strict_json_loads(data)
    if not isinstance(decoded, dict):
        raise ValueError("PROCESSED_ROOT_MUST_BE_OBJECT")
    if decoded.get("format") != "hp-processed-capture":
        raise ValueError("UNSUPPORTED_PROCESSED_FORMAT")
    if decoded.get("schema_version") != "1.0":
        raise ValueError("UNSUPPORTED_PROCESSED_SCHEMA")
    return ProcessedCapture.model_validate_json(canonical_json_bytes(decoded), strict=True)


@dataclass(frozen=True, slots=True)
class ProcessedRecord:
    sha256: str
    path: Path
    processed: ProcessedCapture


class ProcessedRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, source_hash: str, digest: str) -> Path:
        if not _SHA256.fullmatch(source_hash) or not _SHA256.fullmatch(digest):
            raise ValueError("INVALID_PROCESSED_HASH")
        return self.root / "processed" / source_hash[:2] / source_hash / f"{digest}.hp-processed.json"

    def store(self, value: ProcessedCapture) -> ProcessedRecord:
        self._verify_source(value)
        content = serialize_processed(value)
        if len(content) > MAX_PROCESSED_BYTES:
            raise ValueError("PROCESSED_FILE_TOO_LARGE")
        digest = sha256(content).hexdigest()
        target = self.path_for(value.source_capture_sha256, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self._verify(target, digest, content)
            return ProcessedRecord(digest, target, value)
        descriptor, staging_name = tempfile.mkstemp(prefix=".processed-", suffix=".tmp", dir=target.parent)
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staging, target)
            except FileExistsError:
                self._verify(target, digest, content)
            if os.name != "nt":
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            staging.unlink(missing_ok=True)
        return ProcessedRecord(digest, target, value)

    def load(self, source_hash: str, digest: str) -> ProcessedCapture:
        target = self.path_for(source_hash, digest)
        content = target.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("PROCESSED_HASH_MISMATCH")
        value = load_processed_bytes(content)
        if value.source_capture_sha256 != source_hash:
            raise ValueError("PROCESSED_SOURCE_MISMATCH")
        self._verify_source(value)
        return value

    def list_for_source(self, source_hash: str) -> tuple[ProcessedRecord, ...]:
        if not _SHA256.fullmatch(source_hash):
            raise ValueError("INVALID_CAPTURE_HASH")
        folder = self.root / "processed" / source_hash[:2] / source_hash
        records: list[ProcessedRecord] = []
        if not folder.is_dir():
            return ()
        for path in sorted(folder.glob("*.hp-processed.json"), key=lambda item: item.stat().st_mtime_ns):
            digest = path.name.removesuffix(".hp-processed.json")
            records.append(ProcessedRecord(digest, path, self.load(source_hash, digest)))
        return tuple(records)

    @staticmethod
    def _verify(path: Path, digest: str, expected: bytes) -> None:
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest or content != expected:
            raise ValueError("PROCESSED_HASH_MISMATCH")

    def _verify_source(self, value: ProcessedCapture) -> None:
        source = CaptureRepository(self.root).load(value.source_capture_sha256)
        if value.source_sample_id not in {sample.sample_id for sample in source.samples}:
            raise ValueError("PROCESSED_SOURCE_MISMATCH")
