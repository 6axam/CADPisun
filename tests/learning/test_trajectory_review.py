"""Synthetic-only human hypothesis selection, archival integrity and CAS."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from handwriting_plotter.learning import (
    BinaryInkMask, SkeletonRepository, TrajectoryLimitError, TrajectoryLimits,
    TrajectoryRepository, TrajectoryReviewRepository, ReviewConflict,
    extract_skeleton, infer_trajectories,
)
from handwriting_plotter.learning.repository import PhotoRepository


@pytest.fixture
def stored(tmp_path):
    mask = BinaryInkMask(20, 10, bytes(int(y == 5 and 2 <= x <= 16) for y in range(10) for x in range(20)))
    raw = SkeletonRepository(tmp_path).store(extract_skeleton(mask))
    return TrajectoryRepository(tmp_path).store(infer_trajectories(raw))


def append(repo, stored, parent=None, **kwargs):
    return repo.append(run_sha256=stored.sha256, hypothesis_id="h-0", action="accept",
                       expected_parent_revision_sha256=parent, acknowledge_offline_uncertainty=True, **kwargs)


def test_explicit_selection_versions_reopens_and_never_becomes_online(tmp_path, stored):
    repo = TrajectoryReviewRepository(tmp_path)
    assert repo.latest_for_run(stored.sha256) is None
    first = append(repo, stored)
    second = repo.append(run_sha256=stored.sha256, hypothesis_id="h-1", action="accept",
                         expected_parent_revision_sha256=first.sha256, acknowledge_offline_uncertainty=True)
    assert first.decision.evidence_origin == second.decision.evidence_origin == "offline_inferred"
    assert first.decision.revision_number == 1 and second.decision.revision_number == 2
    assert repo.load(first.sha256) == first
    assert TrajectoryReviewRepository(tmp_path).latest_for_run(stored.sha256) == second
    assert TrajectoryRepository(tmp_path).load(stored.sha256) == stored
    with pytest.raises(ReviewConflict, match="REVISION_CONFLICT"):
        append(repo, stored, parent=first.sha256)


def test_acknowledgement_unknown_candidate_and_unresolved_acceptance_are_refused(tmp_path, stored):
    repo = TrajectoryReviewRepository(tmp_path)
    with pytest.raises(ValueError, match="ACKNOWLEDGEMENT_REQUIRED"):
        repo.append(run_sha256=stored.sha256, hypothesis_id="h-0", action="accept",
                    expected_parent_revision_sha256=None, acknowledge_offline_uncertainty=False)
    with pytest.raises(ValueError, match="HYPOTHESIS_NOT_FOUND"):
        repo.append(run_sha256=stored.sha256, hypothesis_id="h-999", action="accept",
                    expected_parent_revision_sha256=None, acknowledge_offline_uncertainty=True)
    raw = SkeletonRepository(tmp_path).load(stored.run.raw_graph_sha256)
    fallback = TrajectoryRepository(tmp_path).store(infer_trajectories(raw, limits=TrajectoryLimits(max_search_expansions=1)))
    with pytest.raises(ValueError, match="UNRESOLVED_TRAJECTORY"):
        append(repo, fallback)
    rejection = repo.append(run_sha256=fallback.sha256, hypothesis_id="h-0", action="reject",
                            expected_parent_revision_sha256=None, acknowledge_offline_uncertainty=True)
    assert rejection.decision.action == "reject"


def test_empty_run_cannot_be_accepted(tmp_path):
    raw = SkeletonRepository(tmp_path).store(extract_skeleton(BinaryInkMask(1, 1, b"\0")))
    stored = TrajectoryRepository(tmp_path).store(infer_trajectories(raw))
    with pytest.raises(ValueError, match="UNRESOLVED_TRAJECTORY"):
        append(TrajectoryReviewRepository(tmp_path), stored)


def test_two_writers_publish_exactly_one_successor(tmp_path, stored, monkeypatch):
    repo = TrajectoryReviewRepository(tmp_path)
    barrier = Barrier(2)
    original = PhotoRepository._store_immutable

    def paused(target, content, code):
        if target.suffix == ".next":
            barrier.wait(timeout=10)
        return original(target, content, code)

    monkeypatch.setattr(PhotoRepository, "_store_immutable", staticmethod(paused))

    def writer():
        try:
            return append(repo, stored)
        except ReviewConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: writer(), range(2)))
    assert sum(isinstance(result, ReviewConflict) for result in results) == 1
    winner = next(result for result in results if not isinstance(result, ReviewConflict))
    assert repo.latest_for_run(stored.sha256) == winner


def test_crash_before_successor_publication_leaves_no_selected_state(tmp_path, stored, monkeypatch):
    repo = TrajectoryReviewRepository(tmp_path)
    original = PhotoRepository._store_immutable

    def interrupted(target, content, code):
        if target.suffix == ".next":
            raise OSError("synthetic interrupted publication")
        return original(target, content, code)

    monkeypatch.setattr(PhotoRepository, "_store_immutable", staticmethod(interrupted))
    with pytest.raises(OSError, match="interrupted"):
        append(repo, stored)
    assert repo.latest_for_run(stored.sha256) is None
    monkeypatch.undo()
    first = append(repo, stored)
    assert repo.latest_for_run(stored.sha256) == first


def test_history_cap_keeps_last_valid_revision_readable(tmp_path, stored, monkeypatch):
    import handwriting_plotter.learning.trajectory_review as module

    monkeypatch.setattr(module, "MAX_REVIEW_HISTORY", 2)
    repo = TrajectoryReviewRepository(tmp_path)
    first = append(repo, stored)
    second = append(repo, stored, parent=first.sha256)
    assert repo.latest_for_run(stored.sha256) == second
    assert repo.load(second.sha256) == second
    with pytest.raises(TrajectoryLimitError, match="HISTORY_LIMIT"):
        append(repo, stored, parent=second.sha256)
    assert repo.latest_for_run(stored.sha256) == second


def test_corrupt_decision_or_successor_is_not_silently_ignored(tmp_path, stored, monkeypatch):
    import handwriting_plotter.learning.trajectory_review as module

    repo = TrajectoryReviewRepository(tmp_path)
    event = append(repo, stored)
    monkeypatch.setattr(module, "MAX_REVIEW_BYTES", 16)
    with pytest.raises(TrajectoryLimitError, match="REVIEW_RECORD_LIMIT"):
        repo.load(event.sha256)
    monkeypatch.undo()
    event.path.write_bytes(b"corrupt synthetic decision")
    with pytest.raises(ValueError, match="DECISION_HASH_MISMATCH"):
        repo.latest_for_run(stored.sha256)
    link = repo._link(stored.sha256, None)
    link.write_bytes(b"corrupt synthetic successor")
    with pytest.raises(ValueError, match="INVALID_TRAJECTORY_DECISION_LINK"):
        repo.latest_for_run(stored.sha256)
    with pytest.raises(ValueError, match="INVALID_TRAJECTORY_REVIEW_HASH"):
        repo.path_for("../escape")
