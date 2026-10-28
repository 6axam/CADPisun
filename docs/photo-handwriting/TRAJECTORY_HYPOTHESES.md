# TASK 14 — Offline direction, trail and pen-lift hypotheses

## Contract and epistemic boundary

Input is an immutable TASK 13A `SkeletonGraphRecord`, optionally paired with
one explicitly selected TASK 13B `SkeletonCleanupRecord`. Geometry, adjacency,
compact junction regions, source component ownership and provenance remain
owned by those stages. This module does not rerun thinning, modify raw ink,
guess text, or load HTR/benchmark data.

Output is `hp-trajectory-hypotheses/1.0`, algorithm
`bounded-port-pairing/1`, with **`evidence_origin=offline_inferred`**. It does
not become `online_capture` when a human accepts it. A static photograph does
not identify actual direction, start, stroke order, retracing, pauses or pen
lifts. All accepted/proposed routes remain reconstructions, not observations.
No confidence/probability, timestamps per point, pressure or velocity is
invented. Actual direction/order/DTW quality stays unmeasured without paired
online traces from independently held-out writing sessions.

This task supplies a Qt-free inference/review API and diagnostic SVG. It does
not add Studio buttons or the broader correction UI assigned to TASK 16, nor
the sample bank/StylePack publication of TASK 15/17. There is no conversion to
PenPlan, hardware commands or G-code.

## Typed results

| Type | Contents |
|---|---|
| `TrajectoryConstraints` | Explicit user-required/forbidden port joins and fixed edge directions |
| `PortPair` | Two ports of one graph node; `e-N:a`/`e-N:b` refer to canonical edge endpoints |
| `DirectedSkeletonEdge` | Existing edge ID and forward/reverse/unresolved direction |
| `InferredStroke` | Ordered edge references, or a retained isolated mark/unresolved region; actual endpoint pixels, component, closed-geometry flag |
| `JunctionPassage` | Proposed port pairing, node ID, local turn cost and single-pixel/unresolved-region geometry |
| `InferredPenLift` | Proposed transfer between two ordered strokes, endpoint pixels and component/separate-trail reason; `observed=false` |
| `TrajectoryHypothesis` | Ordered strokes, proposed joins/lifts, heuristic cost, explicit status/order state and unresolved geometry references |
| `TrajectoryRun` | Raw/cleanup hashes, complete source provenance/frame, node-region references, limits/constraints, alternatives and search diagnostics |
| `TrajectoryDecision` | Human accept/reject event, exact run/hypothesis, parent revision, revision number, UUID/time and explicit uncertainty acknowledgement |

All models are frozen and Qt-free. The default package still imports without
OpenCV, NumPy, Qt, PyTorch or Transformers. Frames and integer endpoint pixels
use TASK 13's `line-crop-px-top-left`; the unchanged crop offsets/frame reference
map back through existing source transforms. No millimetre scale is assumed.

## Bounded search and geometric ranking

1. Resolve/validate the exact raw record and optional cleanup digest. Cleanup
   provenance and canonical geometry are checked against the raw graph.
2. Give each graph edge two ports (`a`/`b`). A port tangent is a secant from
   the actual endpoint to up to three chain samples away; a tiny closed chain
   returning to its start uses its first actual adjacent sample instead.
3. At a junction, enumerate bounded partial port matchings. A port may remain
   open, allowing a stroke end/lift rather than forcing continuity. Required
   joins consume their ports; forbidden joins are excluded. Invalid, repeated,
   cross-node or conflicting constraints refuse before search.
4. Rank local configurations by the sum of `(1 + dot(tangent_a, tangent_b))/2`
   plus `0.35` per unpaired port. Opposing outgoing tangents favour a smoother
   continuation. This is a local angular-curvature proxy, not learned writing
   behaviour or calibrated quality. A synthetic cycle anchor has known graph
   closure and contributes zero configuration cost; it is not a detected pen
   start. A forbidden anchor closure may instead leave its ports open.
5. Combine configurations in a bounded beam; follow paired ports to create
   edge-disjoint trails. Every original/selected edge occurs **exactly once**.
   No duplicate traversal is invented to force an Euler tour. Pure cycles
   retain their canonical anchor and both possible directions.
6. Jointly explore trail directions and ordering with another beam, enforcing
   fixed user edge directions. Pen-up distance divided by `max(width,height)`
   ranks ordering variants. Final cost adds `0.7` per proposed lift. Distinct
   port configurations receive alternative slots before more direction/order
   variants of one configuration; final selected alternatives are cost sorted.

The constants are provisional, versioned engineering heuristics. There are no
trained or empirically calibrated stroke-order weights. Tie breaking and IDs
are deterministic serialization conventions, not assertions about writing
direction or text reading order. Beam truncation is explicit; the alternatives
are neither exhaustive nor guaranteed globally optimal. A small cap can omit
an otherwise plausible pairing/direction. User constraints apply to the chosen
raw/cleanup graph IDs, so a changed cleanup must not reuse old IDs silently.

An open chain has two directions. T/X intersections can be paired differently
or split into additional strokes. Detached dots remain independent marks with
alternative positions in the proposed order; their association with letters
is not inferred here. `closed` means equal geometric start/end pixels, not
evidence of observed temporal loop closure.

### Compact regions and coverage

Edges are references to their complete existing pixel chains, never fabricated
interpolated arrays. A proposed passage through a multi-pixel junction retains
`geometry=unresolved_region`; the region's full source pixels and internal holes
remain in its graph. **No straight bridge through a junction is generated.**
Such references require later manual geometric work before a complete drawable
trajectory can be claimed. All node-region IDs remain in the run for coverage.
A region with no external edge becomes an explicit unresolved placeholder,
not an arbitrary hidden traversal. Empty runs and placeholder-only/incomplete
region routes cannot be accepted as reconstructed trajectories.

### Safe fallback and resource limits

Defaults (hard caps in parentheses): 128 (512) search edges, 256 (1024) search
nodes, at most 8 ports/node, 8 (32) local options, beam 16 (32), 8 (16) output
hypotheses, 20,000 (100,000) search expansions, 256 MiB estimated workspace.
Parent graph validation retains its existing count/work/record bounds.
Eight-port partial matchings are finite and search-budgeted; route expansions
also consume the same counter before construction. No unbounded permutation
enumeration or edge retracing occurs.

If admitted graph complexity or search expansions exceed their limits, return
one complete **unresolved** coverage record: all edges, all node regions and
all marks remain, edge directions are unknown, ordering is unresolved,
`ranking_cost=null`, and no ordered pen-lift sequence is asserted. An unresolved
record cannot be accepted by the review API. Cancellation and insufficient
workspace admission instead raise `TrajectoryLimitError` with no successful
partial record. No hidden automatic parameter retries occur.

`fallback_reason=constraint_coverage` means no constraint-valid route was found
in retained configurations; this is not a proof of logical infeasibility and
does not claim a resource budget was exhausted. `search_limit` and
`graph_complexity` set `budget_exhausted=true`; all fallback kinds explicitly
mark alternatives truncated.

Workspace admission starts with `8*raster_pixels + 4096*raw_skeleton_pixels +
65536` bytes for bounded parent/validation/reference structures. If edge/node
counts allow search, add `64*beam_width*(edge_count+node_count)^2`, plus 262,144
bytes for a nonempty search graph. This includes the expanded order beam's
tuples, not just raster memory. It is an estimate, not measured RSS/VMS or an
OS-enforced quota. Cancellation is cooperative at search transitions and before
parent validation; it is not a hard deadline for filesystem/parent operations.
JSON/SVG reads/outputs are independently capped at 16 MiB.

## Persistence, active references and human confirmation

Canonical content-addressed runs live privately under `trajectory-hypotheses/`.
Writes reuse the atomic no-overwrite/fsync repository writer. Store and archival
load resolve the raw/cleanup records and deterministically recompute all
hypotheses, costs, counters, provenance and diagnostics (except event time).
Schema parsing alone does not establish a valid parent; use repository load or
`validate_parent()`. Duplicate JSON keys/non-finite numbers, corrupted hashes
and forged derived content refuse. Originals, HTR predictions, accepted review
text, raw skeleton and cleanup records remain unchanged.

Active `load_current()` requires the expected raw graph hash and optional
cleanup hash as well as the existing source/review/cropper context. It checks
the selected graph revision, then delegates TASK 13's current source, crop,
selected mask, segmentation, latest review and frame integrity checks. Archived
inference/decision records do not implicitly become current for new ink.

```python
from handwriting_plotter.learning import (
    TrajectoryRepository, TrajectoryReviewRepository, infer_trajectories,
    render_trajectory_overlay_svg,
)

run = infer_trajectories(raw_record, cleanup=selected_cleanup_record)
repository = TrajectoryRepository(photo_repository.root)
stored = repository.store(run)
current = repository.load_current(
    stored.sha256, raw_graph_sha256=raw_record.sha256,
    cleanup_sha256=selected_cleanup_record.sha256,
    photos=photo_repository, source=source, review=review, cropper=cropper,
)
svg = render_trajectory_overlay_svg(
    raw_record, current.run, cleanup=selected_cleanup_record, hypothesis_id="h-0",
)

# Only after a person actually inspected and selected a proposed hypothesis:
decisions = TrajectoryReviewRepository(photo_repository.root)
previous = decisions.latest_for_run(current.sha256)
accepted = decisions.append(
    run_sha256=current.sha256, hypothesis_id="h-0", action="accept",
    expected_parent_revision_sha256=None if previous is None else previous.sha256,
    acknowledge_offline_uncertainty=True,
)
```

The confirmation API is an explicit programmatic human-selection boundary, not
an automatic acceptance step. Its caller must perform active-reference checks
before presenting/accepting current data. Accepted hypotheses with compact
passages still retain that unresolved interior geometry; selection does not
authorize StylePack publication or fill it in. Reject is also available.

Decisions are append-only `hp-trajectory-decision/1.0` records. An immutable
successor slot per `(run,parent)` provides atomic optimistic concurrency;
exactly one concurrent writer can publish the next event. A crash between
content storage and successor publication can leave an unselected orphan,
which archival load may inspect but `latest_for_run()` never treats as current.
Links, hashes, run/hypothesis identity, parent references and increasing revision
numbers are verified. Histories are capped at 256 revisions; the last valid
revision remains readable at the cap. A new run requires a separate review.

## Diagnostics and verification

SVG shows proposed arrows only along actual edge chains, node regions in
orange/cyan, and proposed pen-up travel as red dashed background annotations.
Travel is deliberately painted **under** retained ink/marks; a headless Qt
regression reproduces the tiny-dot occlusion that painting travel last caused.
Fallback views show no direction arrows, selected order labels or pen-up route.
There is no raster/trajectory approximation through an unknown junction region.

Deterministic tests cover chains and both directions, T/X competing pairings,
cycles, detached dots, thick regions/internal holes, 32 fixed-seed masks,
explicit direction/join constraints, infeasible retained configurations,
cleanup/source revision invalidation, coverage/adjacency, budgets, cancellation,
immutable persistence, forged content, corrupt parents, concurrent decisions,
interrupted publication and review caps. Optional Qt tests render PNG pixels.
Synthetic X alternatives were visually inspected separately. No private photos,
transcripts, predictions, masks or model weights are used or published.

Actual direction/order/pen-lift accuracy is still **not measured**. Real
retracing, missing ink, diagonal-contact interpretation and junction interiors
can lie outside this single-cover model. TASK 15 can consume typed candidates
and provenance; it must preserve unresolved groups and require later review.
