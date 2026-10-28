"""Append-only explicit selection of offline hypotheses; no online conversion."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
import uuid

from pydantic import Field

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from .repository import PhotoRepository
from .trajectories import TrajectoryLimitError, TrajectoryRecord, TrajectoryRepository
from .transcription_review import ReviewConflict

MAX_REVIEW_BYTES = 16_384
MAX_REVIEW_HISTORY = 256


class TrajectoryDecision(StrictModel):
    format: Literal["hp-trajectory-decision"] = "hp-trajectory-decision"
    schema_version: Literal["1.0"] = "1.0"
    revision_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    revision_number: int = Field(ge=1, le=256)
    created_at_utc: str = Field(min_length=1, max_length=64)
    run_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    hypothesis_id: str = Field(pattern=r"^h-[0-9]+$")
    action: Literal["accept", "reject"]
    acknowledged_offline_uncertainty: Literal[True]
    evidence_origin: Literal["offline_inferred"] = "offline_inferred"
    parent_revision_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class TrajectoryDecisionRecord:
    sha256: str
    path: Path
    decision: TrajectoryDecision


class TrajectoryReviewRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs = TrajectoryRepository(root)

    def _path(self, directory: str, digest: str, filename: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("INVALID_TRAJECTORY_REVIEW_HASH")
        root = self.root.resolve()
        target = (root / directory / digest[:2] / digest / filename).resolve()
        if root not in target.parents:
            raise ValueError("TRAJECTORY_REVIEW_PATH_OUTSIDE_DATA_ROOT")
        return target

    def path_for(self, digest: str) -> Path:
        return self._path("trajectory-decisions", digest, "decision.json")

    def _link(self, run_digest: str, parent: str | None) -> Path:
        if parent is not None:
            self.path_for(parent)  # validate before using as a filename
        return self._path("trajectory-decision-links", run_digest, f"{parent or 'root'}.next")

    @staticmethod
    def _validate_choice(record: TrajectoryDecisionRecord, run: TrajectoryRecord) -> None:
        event = record.decision
        if event.run_sha256 != run.sha256:
            raise ValueError("TRAJECTORY_DECISION_RUN_MISMATCH")
        candidate = next((h for h in run.run.hypotheses if h.hypothesis_id == event.hypothesis_id), None)
        if candidate is None:
            raise ValueError("TRAJECTORY_HYPOTHESIS_NOT_FOUND")
        if event.action == "accept" and (candidate.status != "proposed" or not candidate.constraints_satisfied
                                          or not candidate.strokes or any(s.kind == "unresolved_region" for s in candidate.strokes)):
            raise ValueError("UNRESOLVED_TRAJECTORY_CANNOT_BE_ACCEPTED")

    def _read(self, digest: str) -> TrajectoryDecisionRecord:
        path = self.path_for(digest)
        with path.open("rb") as stream:
            content = stream.read(MAX_REVIEW_BYTES + 1)
        if len(content) > MAX_REVIEW_BYTES:
            raise TrajectoryLimitError("TRAJECTORY_REVIEW_RECORD_LIMIT")
        if sha256(content).hexdigest() != digest:
            raise ValueError("TRAJECTORY_DECISION_HASH_MISMATCH")
        strict_json_loads(content)
        return TrajectoryDecisionRecord(digest, path, TrajectoryDecision.model_validate_json(content, strict=True))

    def load(self, digest: str) -> TrajectoryDecisionRecord:
        record = self._read(digest)
        run = self.runs.load(record.decision.run_sha256)
        current = record
        for _ in range(MAX_REVIEW_HISTORY):
            self._validate_choice(current, run)
            parent = current.decision.parent_revision_sha256
            if parent is None:
                if current.decision.revision_number != 1:
                    raise ValueError("TRAJECTORY_DECISION_CHAIN_MISMATCH")
                return record
            previous = self._read(parent)
            if previous.decision.revision_number + 1 != current.decision.revision_number:
                raise ValueError("TRAJECTORY_DECISION_CHAIN_MISMATCH")
            current = previous
        raise TrajectoryLimitError("TRAJECTORY_REVIEW_HISTORY_LIMIT")

    def latest_for_run(self, run_sha256: str) -> TrajectoryDecisionRecord | None:
        run = self.runs.load(run_sha256)
        latest = None
        for index in range(MAX_REVIEW_HISTORY + 1):
            link = self._link(run_sha256, None if latest is None else latest.sha256)
            if not link.exists():
                return latest
            if index == MAX_REVIEW_HISTORY:
                raise TrajectoryLimitError("TRAJECTORY_REVIEW_HISTORY_LIMIT")
            with link.open("rb") as stream:
                content = stream.read(65)
            if len(content) != 64:
                raise ValueError("INVALID_TRAJECTORY_DECISION_LINK")
            digest = content.decode("ascii")
            record = self._read(digest)
            if record.decision.parent_revision_sha256 != (None if latest is None else latest.sha256):
                raise ValueError("TRAJECTORY_DECISION_CHAIN_MISMATCH")
            if record.decision.revision_number != index + 1:
                raise ValueError("TRAJECTORY_DECISION_CHAIN_MISMATCH")
            self._validate_choice(record, run)
            latest = record
        raise TrajectoryLimitError("TRAJECTORY_REVIEW_HISTORY_LIMIT")

    def append(
        self, *, run_sha256: str, hypothesis_id: str, action: Literal["accept", "reject"],
        expected_parent_revision_sha256: str | None, acknowledge_offline_uncertainty: bool,
    ) -> TrajectoryDecisionRecord:
        if acknowledge_offline_uncertainty is not True:
            raise ValueError("OFFLINE_UNCERTAINTY_ACKNOWLEDGEMENT_REQUIRED")
        run = self.runs.load(run_sha256)
        latest = self.latest_for_run(run_sha256)
        if (None if latest is None else latest.sha256) != expected_parent_revision_sha256:
            raise ReviewConflict("TRAJECTORY_REVIEW_REVISION_CONFLICT")
        number = 1 if latest is None else latest.decision.revision_number + 1
        if number > MAX_REVIEW_HISTORY:
            raise TrajectoryLimitError("TRAJECTORY_REVIEW_HISTORY_LIMIT")
        event = TrajectoryDecision(
            revision_id=str(uuid.uuid4()), revision_number=number,
            created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            run_sha256=run_sha256, hypothesis_id=hypothesis_id, action=action,
            acknowledged_offline_uncertainty=True, parent_revision_sha256=expected_parent_revision_sha256,
        )
        content = canonical_json_bytes(event.model_dump(mode="json"))
        digest = sha256(content).hexdigest()
        record = TrajectoryDecisionRecord(digest, self.path_for(digest), event)
        self._validate_choice(record, run)
        PhotoRepository._store_immutable(record.path, content, "TRAJECTORY_DECISION_HASH_MISMATCH")
        # One immutable successor slot per parent provides atomic optimistic
        # concurrency. A crash before publication may leave a harmless orphan
        # content record; it never silently changes the published selection.
        try:
            PhotoRepository._store_immutable(self._link(run_sha256, expected_parent_revision_sha256),
                                             digest.encode("ascii"), "TRAJECTORY_REVIEW_REVISION_CONFLICT")
        except ValueError as exc:
            if str(exc) != "TRAJECTORY_REVIEW_REVISION_CONFLICT":
                raise
            raise ReviewConflict(str(exc)) from exc
        return record
