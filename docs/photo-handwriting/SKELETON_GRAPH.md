# TASK 13A: raw skeleton and topological graph

## Algorithm and connectivity decision

Foreground uses 8-connectivity; background uses 4-connectivity, including a
virtual exterior background frame. Pixel coordinates are integer centers in
the existing `line-crop-px-top-left` frame. An edge between diagonal pixels is
retained only when neither intervening orthogonal pixel is foreground. This
removes redundant graph shortcuts around filled corners while preserving
diagonal foreground connectivity. A diagonal-only contact remains an explicitly
ambiguous pixel connection, not evidence of an actual handwriting join.

The installed `opencv-python-headless` lacks `ximgproc.thinning`; scikit-image
is not installed. No new scientific-stack dependency is introduced into the
default package. The selected algorithm is a bounded, Qt-free Zhang–Suen
variant (`guarded-zhang-suen/1`), implemented from its two directional deletion
conditions with a sequential digital-simple-point guard and endpoint retention.
It is deliberately versioned separately from unmodified parallel Zhang–Suen.

Before each actual deletion, the guard checks one foreground 8-component in the
3×3 neighbor ring and one background 4-component adjacent to the center. It
refuses endpoints and the last pixel of a component. Components cannot be
joined because the algorithm only deletes foreground pixels. Sequential
rechecking prevents a simultaneous candidate batch from deleting an entire
small component. After convergence, foreground components and background holes
are independently checked; any mismatch refuses the result.

References: [Zhang and Suen, 1984](https://doi.org/10.1145/357994.358023),
[scikit-image's documented thinning algorithms](https://scikit-image.org/docs/stable/auto_examples/edges/plot_skeleton.html),
[OpenCV's optional ximgproc thinning API](https://docs.opencv.org/4.x/df/d2d/group__ximgproc.html).

Foreground pixels removed by thinning are recorded by the unchanged input-mask
digest and pixel counts; the complete resulting raw skeleton is retained.
Thinning is a topological representation, not a guarantee of a metric medial
axis or faithful stroke width. TASK 13B owns pruning/cleanup; TASK 14 owns any
future direction or traversal hypotheses.

## Typed raw graph

| Model | Contents |
|---|---|
| `SkeletonGraph` | Versioned provenance, dimensions, exact sparse raw skeleton, binary digests, before/after topology, nodes/edges/components, resource counters |
| `SkeletonNode` | Canonical anchor and full pixel region; endpoint, junction, isolated pixel or cycle anchor; internal hole count |
| `SkeletonEdge` | Undirected node pair, complete ordered adjacent pixels and pixel-chain length; self-loops remain explicit |
| `SkeletonComponent` | Original `InkComponent` bounds/count/ID, surviving pixel count, node/edge IDs, cycle rank |

High-degree neighboring skeleton pixels are grouped into a compact junction
region. Every filled 2×2 cell is included in such a region, including its
degree-two corners: the square's perimeter is not a real background hole.
Every retained external link becomes an edge, with exact junction exit/entry
pixels. Internal junction links can be recovered from the complete raw region;
they are not given an invented pen traversal. The region's internal holes use
the full raster's adjacency and subtract filled faces. A region must not be
re-rasterized in isolation for this calculation: doing so could introduce new
diagonal shortcuts and double-count an external loop.

For a component, `cycle_rank = E - V + 1 + sum(node.internal_holes)`. This must
equal the component's digital background-hole count. A pure degree-two cycle
gets a node at its minimum `(y, x)` pixel and a closed edge returning to that
same pixel. A self-loop attached to a junction can enter/exit different pixels
of the same stored region; `closed` means graph closure, not a drawn straight
connection through the region. Internal holes in a compact region remain
explicit metadata with their raw pixels, rather than being silently erased.

IDs follow surviving row-major geometry (`c-0`, `n-0`, `e-0`, etc.). Original
`InkComponent.component_id` separately retains source ownership if thinning
changes the row-major order. Edge orientation is canonical serialization only:
the lower numeric node ID comes first; self-loops choose the lexicographically
smaller row-major pixel sequence. There is no pen direction, pairwise branch
selection, stroke order, pen lift or toolpath.

All raw pixels must be covered by node regions or edges; every external
adjacency link must occur exactly once. Pixel sequences are not smoothed,
resampled or pruned. Node/edge/component references, geometry, digests, bounds
and cycle counts are revalidated on load. `skeleton_mask()` reconstructs the
exact retained raw raster, including isolated marks.

## Existing photo pipeline and private storage

```python
from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper
from handwriting_plotter.learning import SkeletonRepository, extract_photo_skeleton

# Existing selected PhotoRecord and latest accepted TranscriptionReviewRecord.
cropper = OpenCvLineMaskCropper()
graph = extract_photo_skeleton(
    photos=photo_repository, source=source, review=review, cropper=cropper,
)
repository = SkeletonRepository(photo_repository.root)
stored = repository.store(graph)
restored = repository.load_current(
    stored.sha256, photos=photo_repository, source=source,
    review=review, cropper=cropper,
)
raw_mask = restored.graph.skeleton_mask()
```

This entry point reuses `verified_line_mask()` from TASK 12. It checks actual
PNG crop/selected mask hashes, decoded dimensions, source manifest, line frame
and latest review. The accepted text review binds the line identity; it does
not certify that every pixel in the selected mask is true handwriting. Photo
records retain source/crop/mask/review hashes and the existing frame translation.
Add `crop_left_px`/`crop_top_px` to reach `frame_id`; existing TASK 03 transforms
then map into original source pixels.

`extract_skeleton(BinaryInkMask)` is also available without a transcript or
optional image runtime. Synthetic/pure records explicitly have no photo fields;
only their input binary-mask digest is known. `validate_input(mask)` checks the
digest, surviving subset, original component metadata and component identity.
Extraction does not depend on speculative grapheme boundaries and never splits
connected ink according to a transcript.

Canonical `hp-skeleton-graph/1.0` records live under local `skeleton-graphs/`.
They retain the raw sparse raster directly; `skeleton_sha256` hashes its width,
height and binary bytes using TASK 12's digest convention. Writes reuse the
photo repository's no-overwrite, atomic, fsync writer. Archival `load()` checks
record hash/schema/geometry; active `load_current()` additionally refuses stale
source, segmentation, crop, mask, review or frame offsets. Private source data,
masks and result records stay outside Git. All new fixtures are synthetic.

## Resource bounds and refusal

`SkeletonLimits` defaults: 1,000,000 raster pixels, 50,000 foreground pixels,
256 input components, 8,192 nodes, 16,384 edges, 100,000 total node/edge pixel
entries, 256 thinning rounds, 20,000,000 algorithm work units and a 256 MiB
workspace admission estimate. Hard maxima permit 4,000,000 raster pixels,
200,000 graph entries, 1,024 rounds and 50,000,000 work units, while retaining
the other count caps. Input type/length/binary values are checked before
building large pixel sets. Record reads are bounded to 16 MiB before parsing.

The conservative workspace estimate is `8*raster_pixels + 4096*foreground +
4096` bytes. Together with explicit structure-size limits this is an admission
bound for the algorithm's data structures and validation copies, not measured
RSS/VMS or an OS-enforced memory quota. Counters bound candidate scans, local
connectivity work and graph traversal; they are not a wall-clock deadline.
Optional cooperative cancellation and any exceeded budget raise an explicit
error. No incomplete graph is returned as successful or automatically stored.

## Verification and practical limits

The independent test oracle uses flood fill (foreground-8/background-4) rather
than the implementation's local digital-Euler formula. It compares component
identity and per-component holes, full raster/chain coverage and canonical
geometry. All 512 possible 3×3 patterns and 128 fixed-seed 8×8 masks are tested,
alongside exact straight/diagonal lines, T/X crossings, simple/double loops,
thick rings, connected groups, isolated pixels, `і`/`ї` dots, borders,
idempotence, immutable storage, corruption and budget/cancellation refusal.

This is a deterministic topological skeleton, not a guaranteed geometric medial
axis. Sequential simple-point protection can bias the centerline or shift thick
end caps; compact junction regions may retain filled cells. Diagonal contacts
and junctions remain pixel interpretations with explicit ambiguity diagnostics.
Very noisy/large masks can exceed admission limits. No short branch, isolated
dot, loop or edge is automatically deleted. Graph cleanup, spur filtering,
visual diagnostics and final parent TASK 13 verification belong to TASK 13B,
which has not begun. Accuracy on real photographs remains unmeasured.
