# Photo-to-Handwriting progress

Last updated: 2026-10-27

## Current checkpoint

| Field | Value |
|---|---|
| Branch | `feat/photo-to-handwriting` |
| Base | `main` at `05cbc014fc6d97d052f55e56a00e32eeee942a59` |
| Completed | 15 / 25 parent tasks |
| Last completed | TASK 13B — Conservative graph cleanup, spur filtering and diagnostics; parent TASK 13 DONE |
| Next | TASK 14 — Stroke direction and pen lifts; not started |
| Actual remaining Codex quota | Unknown; the runtime did not report it |


## TASK 13B — Conservative graph cleanup, spur filtering and diagnostics

Status: `[x]` DONE. TASK 13A and 13B are complete; parent TASK 13 is `[x] DONE`
under the raw-topology plus explicit-cleanup contract. TASK 14 was not started.

Completion commit: `8ff041811e758c25c1df31c15a6717f89b439919`.

- Added Qt-free, frozen `SkeletonCleanupPolicy`, `SkeletonCleanupLimits`,
  `SpurCandidate`, `SkeletonCleanup` and content-addressed cleanup records.
  The implementation reuses TASK 13A adjacency, component/topology and graph
  extraction; it does not create a second thinning/segmentation pipeline.
- Default cleanup preserves every raw pixel/node/edge/component and only
  proposes short endpoint-to-junction branches as ambiguous. A short branch
  can be a real letter feature or attached mark. No classifier, calibrated
  confidence, automatic deletion or geometric smoothing is claimed.
- Explicit raw-edge selections perform bounded single-pass filtering.
  Independent dots, short components, loops and junction pixels cannot be
  selected for deletion. Affected original junctions retain at least two
  incident links. Whole-operation component identity, digital holes and
  per-component cycle checks refuse unsafe selections. Regenerated canonical
  chains remove redundant degree-two graph nodes while retaining exact pixels;
  there is no cascading pruning or pen-order inference.
- Derived IDs can differ from raw IDs; candidates/decisions always reference
  the immutable raw record hash and raw edge IDs. Source/crop/mask/review/frame
  provenance and original InkComponent ownership survive canonical reordering.
  Store/reopen recompute the derived result; active reopen delegates existing
  source, segmentation, review, crop, mask and offset invalidation checks.
- Added bounded diagnostic SVG with raw-ink background, retained chains,
  compact junctions/internal-hole metadata, isolated marks, anchored cycles,
  ambiguous raw candidates and explicit removals. Optional actual input mask
  must match raw input integrity checks. No review text is embedded. Qt SVG
  integration verifies PNG pixel colors/positions; a synthetic before/after
  PNG was separately rendered and visually inspected. No GUI controls were
  added or claimed; the API prepares diagnostics for later manual correction.
- Candidate/removal/work/workspace/record/SVG caps and cancellation refuse
  partial success. Workspace values are admission estimates, distinct from
  RSS, VMS and OS hard quotas. No dependencies, project formats, StylePacks,
  HTR models, exports or private data were changed. No TASK 14 work, inferred
  stroke directions, pen lifts or G-code from these graphs were implemented.

Focused Linux/headless Qt checks:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_skeleton_cleanup.py tests/learning/test_skeleton.py \
  tests/learning/test_skeleton_photo.py tests/gui/test_skeleton_overlay.py
```

Result: `72 passed in 3.91s`; `31` new cases (30 Qt-free cleanup + one Qt
rendering), plus extended existing photo/stale-reference checks. Cases include
T/X support, loop-tail removal and deterministic cycle anchoring, protected
dots/short strokes, exact geometry/coverage, canonical component reordering,
selection-order determinism, anti-cascade behavior, immutable reopen, forged
geometry/provenance/counters, corrupt/missing raw records, strict bounded JSON,
SVG limits, cancellation and resource refusal. Two sets of 32 fixed-seed masks
check exact no-op geometry and independently flood-filled topology after
admitted selections; prior TASK 13A exhaustive/seeded cases remain intact.
These synthetic checks are not a real-handwriting accuracy measurement.

One isolated Python 3.12.12 process reused the previous 800×100 synthetic
rectangle: 9,120 input foreground pixels, 754 raw skeleton pixels, 2 nodes,
1 edge, 0 candidates/removals. Cleanup (including raw integrity validation)
took 0.042616 seconds and 85,191 work units. Cleanup workspace estimate:
3,736,576 bytes. Measured **whole-process peak RSS** including preceding
extraction/store: 45,552 KiB (~44.5 MiB); not cleanup-only RAM or virtual memory.
This is one local sample, not a speed or memory guarantee for real pages.

Final checks:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Result: `433 passed in 32.39s` on Linux, no failures/skips reported.

```bash
uv run python -m compileall -q src tests
```

```bash
uv lock --check
```

```bash
git diff --check
```

All passed; lock resolves 26 packages. Wheel and sdist built successfully with
`uv build --out-dir /tmp/cadpisun-task13b-build`. Windows was not run. All new
fixtures/artifacts are synthetic; no private photographs, masks, transcripts,
predictions or model weights were read or published.

Contract/API/limitations: [SKELETON_GRAPH.md](SKELETON_GRAPH.md).

Next TASK 14 is estimated at 12/12 and approximately 18k–40k tokens, with high
uncertainty. Begin with bounded competing traversal hypotheses and synthetic
acceptance cases for crossings/loops, explicitly distinguishing inferred
movement from observed pen trajectory. GPT-6.1 Sol at `xhigh` is a reasonable
cost-conscious starting model for the combined graph/ambiguity work; this is
an engineering recommendation, not a quota guarantee. Routine documentation
edits can use Luna. See [OpenAI Docs model selection](https://developers.openai.com/api/docs/guides/model-selection).
The percentage of the user's subscription quota cannot be inferred from a
token estimate. Stop at this completed TASK 13 checkpoint.

## TASK 13A — Topology-preserving thinning and raw graph extraction

Status: `[x]` DONE. At this historical checkpoint parent TASK 13 was
`[>] IN_PROGRESS` and TASK 13B `[ ] TODO`. Current completion is recorded above.
TASK 14, traversal/direction, pen lifts and G-code were not started.

Completion commit: `da1170242d74200413dda33e53542cd1ddfe91b4`.

- Fixed foreground-8/background-4 semantics with virtual exterior background.
  `guarded-zhang-suen/1` uses two directional candidate phases and sequential
  simple-point/endpoint checks before actual deletion. The installed OpenCV
  lacks ximgproc thinning; scikit-image is absent. No new optional/default
  dependency was added. The variant is explicitly distinguished from parallel
  Zhang–Suen. Before/after component identity and hole counts must agree.
- Added Qt-free `SkeletonGraph`, `SkeletonNode`, `SkeletonEdge`,
  `SkeletonComponent`, topology/provenance/resource models and immutable
  persistence. Photo entry/reopen reuse TASK 12's verified line crop/mask,
  source/review checks, binary-mask digest and source-frame offsets. Pure-mask
  extraction is also available without transcription/HTR.
- Graph links retain diagonal-only contacts but omit corner shortcuts with
  an existing orthogonal route. Connected high-degree pixels and filled 2×2
  cells form compact junction regions, whose complete pixels are retained.
  Internal topology uses full-raster adjacency and excludes filled plaquette
  faces from cycle counts. This avoids false triangles/square cycles and
  double-counting loops at junction-region boundaries.
- Every raw skeleton pixel belongs to a node region or an ordered chain.
  Degree-two closed components get a canonical minimum-row/column anchor and
  explicit self-loop edge. Junction regions can retain internal holes as typed
  metadata plus exact pixels. Nodes, components, edges and chain orientations
  have canonical IDs/order. Ordering an undirected edge for serialization
  does not infer pen movement or traversal through an intersection.
- Original masks remain immutable. All independent components, dots, tiny
  strokes, endpoint branches and raw skeleton pixels survive without pruning
  or smoothing. Filled junction regions may remain wider than a chain. This
  is not guaranteed metric medial-axis geometry, letter segmentation or a
  reconstruction of true stroke structure.
- Limits bound raster/foreground sizes, component/node/edge/coordinate counts,
  deletion rounds, work units, estimated workspace and record bytes. Budget or
  cancellation refusal returns no partial successful graph and stores nothing.
  Workspace admission is an allocation estimate, not an RSS/virtual-memory
  metric or an OS hard limit.

Focused Linux checks:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_skeleton.py tests/learning/test_skeleton_photo.py \
  tests/learning/test_word_alignment.py tests/learning/test_word_alignment_integrity.py \
  tests/learning/test_grapheme_alignment.py tests/gui/test_alignment_overlay.py
```

Result: `89 passed`, including `41` new TASK 13A tests. The tests independently
flood-fill foreground/background and compare per-component holes, ordered
geometry, pixel/link coverage and cycle rank; all 512 local 3×3 patterns and
128 seeded 8×8 masks are included. Other cases cover exact straight/diagonal
chains, T/X, single/double loops, thick rings/junctions, points above `і`/`ї`,
boundary pixels, idempotence, deterministic IDs, immutable reopen, damaged
records, input mutation refusal and resource/stale-reference failures. No
private photos, masks, transcripts, model files or results were used/published.

One isolated-process synthetic resource sample (Python 3.12.12): 800×100 pixels,
9,120 input foreground pixels → 754 raw skeleton pixels, 2 nodes, 1 edge and
0 cycles; 7 rounds, 1,226,200 work units, 0.484 seconds. Admission workspace
estimate: 37,999,616 bytes; measured peak process RSS: 45,148 KiB. This sample
is not a performance or quality guarantee for real handwriting.

Detailed contract and limitations: [SKELETON_GRAPH.md](SKELETON_GRAPH.md).

Final verification: full Linux/headless Qt `402 passed in 27.02s`;
`uv run python -m compileall -q src tests`, `uv lock --check` (26 packages),
`git diff --check` and wheel/sdist builds passed. Windows was not run.
At that checkpoint TASK 13A was complete; parent TASK 13 remained in progress
because cleanup, spur filtering, dedicated diagnostics and final verification
belonged to TASK 13B. Estimated next task then: 9–10/12, approximately 10k–20k tokens;
GPT-6.1 Sol `xhigh` is the recommended planning model. First specify conservative
cleanup acceptance tests that distinguish real small marks from removable
spurs while retaining the raw graph. No TASK 13B work was started here.

## TASK 12B — Grapheme, joins and ligatures alignment

Status: `[x]` DONE. TASK 12 is now complete under the hypothesis/uncertainty
contract; real-handwriting alignment accuracy is unmeasured. TASK 13 had not
started at that checkpoint; current TASK 13A status is recorded above.

Completion commit: `948a0eca45b7cda6949c3da9abb550a3b1ec601c`.

- Added Qt-free `GraphemeToken`, `GraphemeInkGroup`, `UnresolvedJoin`,
  `GraphemeHypothesis`, `GraphemeAlignment` and resource-limit models. Unicode
  `\X` partitions the exact TASK 12A text into extended grapheme clusters;
  word-span references and code-point offsets remain unchanged. Only a saved
  `accepted` human review can enter this stage.
- Reused TASK 12A's verified source/crop/mask loading, `WordAlignment`,
  `BinaryInkMask` and `InkComponent`. No second segmentation or HTR path was
  added. The graph advances monotonically over graphemes and whole component
  groups; overlapping X envelopes remain indivisible, protecting detached dots
  above a body stroke. Separate atoms can be grouped with one grapheme, and
  one connected cursive component can cover several graphemes or words.
- Every parent word alternative keeps a coarse safe hypothesis. Bounded
  refinements offer competing groupings, including an off-body dot assigned
  to either adjacent grapheme or retained in a shared group. Joined graphemes
  carry explicit unresolved joins. No shape recognizer, confidence or exact
  letter cuts are invented. Punctuation without TASK 12A word geometry stays
  unresolved; its ink is explicitly retained as residual components.
- Limits apply globally across a run: at most 512 graphemes, 256 inherited
  components, 4,096 graph nodes, 20,000 evaluated DP transitions by default
  (hard maximum 50,000), 2,048 candidate edges by default, 16 output
  hypotheses, three paths per node and eight items per local edge. Budget
  exhaustion returns recorded coarse alternatives. Input/output limits
  refuse explicitly if representing every parent alternative would be impossible.
- Content-addressed `hp-grapheme-alignment/1.0` records link the parent word
  record, source, crop, selected mask, binary-mask digest, accepted review,
  algorithm, text and source-frame translation. Atomic immutable writes reuse
  `PhotoRepository`; schema/reference/coverage checks run on write and read.
  `load_current()` additionally verifies the current review/assets/word record.
- Added diagnostic SVG with embedded exact crop, word boxes, grapheme/shared
  group boxes, unresolved-join counts and a text/offset ledger. It is independent
  of document production exports and G-code. Three synthetic overlays were
  rendered and visually inspected; a headless Qt SVG regression also verifies
  that the source ink remains visible.

Focused Linux check:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_grapheme_alignment.py tests/gui/test_alignment_overlay.py \
  tests/learning/test_word_alignment.py tests/learning/test_word_alignment_integrity.py \
  tests/learning/test_transcription_review.py tests/learning/test_line_regions.py \
  tests/learning/test_ink_masks.py tests/gui/test_photo_import_gui.py
```

Result: `72 passed`, including `26` new grapheme/overlay cases. Evidence covers
fully synthetic connected cursive, multiple detached marks for `ї`, ambiguous
dot ownership, repeated letters, false breaks, crossing ink, empty regions,
Unicode/emoji clusters, budget refusals, immutable reopen and all stale inputs.
It is not a quality evaluation on the user's photographs. Private data and
model files were not read, changed or added to Git.

API, examples, bounds and limitations: [GRAPHEME_ALIGNMENT.md](GRAPHEME_ALIGNMENT.md).

Final verification: full Linux/headless Qt `361 passed in 24.98s`;
`uv run python -m compileall -q src tests`, `uv lock --check` (26 packages),
`git diff --check` and wheel/sdist builds passed. Windows was not run.

Next-stage estimate: TASK 13 remains 12/12 complexity, approximately 18k–35k
tokens. The difficult cases are topology-preserving thinning, collapsed
crossing/junction regions, loops and short marks that must survive cleanup.
Recommended planning model: GPT-6.1 Sol with `xhigh`; first establish graph
invariants and synthetic fixtures, then adapter/diagnostics. This is an estimate
for a future run, not an instruction to start it here.

## TASK 12A — Word and text-span alignment

Status: `[x]` DONE — the first, deliberately non-letter-level half of TASK 12.
Its original checkpoint left TASK 12 in progress; TASK 12B above now closes it.

Completion commit: `5d8a29f9188506b7e91e60daa0ae18804bcc182f`

### Implemented behavior

- `word-spans-components/2` partitions reviewed text exactly into `word`,
  `whitespace`, and `punctuation` spans, preserving offsets, repeated text,
  Ukrainian apostrophes, hyphens, punctuation, spaces and line breaks.
- The existing selected raw/cleaned ink-mask artifact and existing persisted
  `line` region are verified and cropped through a narrow OpenCV adapter. It
  performs no cleanup or morphology: one-pixel dots and small punctuation remain
  foreground components.
- The Qt-free core extracts 8-connected components and creates a bounded set of
  horizontal-gap grouping variants. It aligns contiguous word spans and grouped
  areas deterministically. Connected words and false component breaks become
  alternatives or shared larger regions, not invented word/letter boundaries.
- Each content-addressed `hp-word-alignment/1.0` record carries source manifest,
  line ID, HTR crop SHA-256, selected mask SHA-256, human review revision,
  reviewed-text hash, `line-crop-px-top-left` coordinates, all geometry
  candidates and ranked optimization costs. Costs are explicitly not confidence.
- An alignment refuses a changed source manifest/line/crop or a newer human
  review revision. It neither changes originals, masks, HTR runs nor review
  records. Alignment data, like all photo data, is local and excluded from Git.
- A visual overlay is intentionally deferred: TASK 12A prioritizes the typed
  immutable core; TASK 12B can render word candidates only after its grapheme
  ambiguity model is defined.

Focused Linux checks:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_word_alignment.py \
  tests/learning/test_word_alignment_integrity.py \
  tests/learning/test_transcription_review.py \
  tests/learning/test_line_regions.py \
  tests/learning/test_ink_masks.py \
  tests/gui/test_photo_import_gui.py
```

Result after verification fixes: `46 passed`. The suite covers span ranges, apostrophes/hyphens/newlines,
repeated/connected words, absent ink, tiny diacritics, false visual breaks,
immutable persistence, stale review/crop rejection and reuse of the existing
photo/mask/line pipeline.

### TASK 12A verification and fixes

Verification fix commit: `9bcd35e7466a01366322f0c7b6e1bcf24b403e67`.

Three regression tests first reproduced defects in the initial implementation:
normalizing in the tokenizer changed input offsets, partition truncation before
ranking could omit the best geometric hypothesis, and equal word/component
counts incorrectly declared a boundary `matched`. Version `/2` preserves exact
input offsets (NFC remains the review store's responsibility), uses K-best
monotone dynamic programming, and labels inferred word areas `ambiguous`.
It always retains a shared whole-line hypothesis when alternatives are capped.
The ranking cost uses relative width/text length and gap cues; it is a layout
prior, never recognition or calibrated confidence.

The photo adapter now verifies the persisted manifest and latest review, reads
the actual content-addressed original PNG crop, verifies its SHA-256 and size,
checks the full selected-mask frame size, and records the translation from crop
pixels to the source frame. Corrupt, missing or stale inputs refuse alignment.
The optional mask identity check at reopen also rejects a changed mask hash.
Persistence reuses the photo repository's atomic no-overwrite/fsync writer.
Record validators reject invalid component bounds, candidate references and
text hashes. Existing `/1` algorithm records remain readable.

Explicit limits are 4 million crop pixels, 256 components, 128 word spans,
4 grouping variants, 50,000 DP transitions per grouping and 16 output
alternatives. A search-budget refusal retains a coarse hypothesis with
`SEARCH_BUDGET_EXHAUSTED`; excessive pixels/components/text produce an explicit
error instead of dropping small marks. The synthetic PNG integration tests also
verify that this path imports no Qt, OpenCV, Torch or Transformers until its
optional adapter is explicitly selected.

The callable API and its current limitations are documented in
[WORD_ALIGNMENT.md](WORD_ALIGNMENT.md). TASK 13 remains unstarted; TASK 12B is
recorded separately above.

Verification checkpoint: focused `46 passed`; full Linux/headless Qt
`335 passed in 25.02s`. `uv run python -m compileall -q src tests`,
`uv lock --check` (26 packages) and `git diff --check` passed. All new test
assets and transcripts are synthetic. No private corpus/model download or
inference was performed. Windows was not run. Packaging configuration did not
change in this checkpoint; the preceding TASK 12A wheel/sdist build remains
the last packaging check.

## TASK 11 — Transcription review UI

Status: `[x]` DONE — local human transcription review; it neither trains nor
invokes an HTR model, and it does not begin character segmentation or stroke
reconstruction.

Completion commit: `a93133dbff79df3095996b493ef01cfac7d3a0b2`

### Implemented workflow

- The Photo workspace shows an adjustable, laptop-safe split review panel for
  each current line crop: the immutable PNG crop, immutable original HTR
  prediction, model/run/crop provenance, explicit confidence availability, an
  editable text field and `unreviewed` / `edited` / `accepted` / `unresolved`
  status. The panel has an ignored size policy and zero minimum so it cannot
  recreate the hidden-page `QStackedWidget` minimum-size failure fixed in the
  TASK 10 checkpoint.
- Empty or failed HTR results remain explicitly absent. A reviewer can enter
  text manually; the UI never invents a replacement prediction. Ukrainian
  letters, apostrophes, punctuation, whitespace and line breaks remain ordinary
  Unicode text and are normalized to NFC on persistence.
- Reviews are local content-addressed `hp-transcription-review/1.0` append-only
  records. Every revision binds source manifest SHA-256, line ID, crop SHA-256,
  original HTR prediction, optional HTR-run SHA-256, parent revision and UTC
  time. HTR run records are never modified. A later HTR run therefore cannot
  overwrite an existing human correction.
- Reading-order changes are independent immutable
  `hp-transcription-reading-order/1.0` revisions. They reorder only references
  to the current line crops; source pixels, regions and HTR output are not
  altered. Optimistic parent-hash checks reject stale review and order writers.
- Reopen restores corrections and status only when manifest, line ID and crop
  hash still match. New segmentation cannot silently receive a correction for a
  previous crop. The editor refuses navigation with unsaved text and refuses a
  save if its manifest has changed.
- Review records are deliberately separate from benchmark ground truth and the
  HTR worker protocol. Personal photos, crop pixels, predictions and weights
  remain in local user data and are not tracked by Git.

Focused Linux checks:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_transcription_review.py \
  tests/gui/test_photo_import_gui.py \
  tests/learning/test_htr_integration.py \
  tests/gui/test_shell.py
```

Result: `35 passed`. The test set covers NFC, immutable/original prediction,
manual unknown text, reopen, HTR-rerun protection, reading-order persistence,
revision conflicts, unsaved-edit navigation, protocol privacy and GUI sizing.

## TASK 10 — HTR integration

Status: `[x]` DONE — optional local provider integration; no model is included
in the application or added to the default environment.

Completion commit: `ecb41e593cb6ab57fccb67ae6c5565f9d595903b`

### Implemented behavior

- Added the versioned `hp-htr-worker/1` JSON subprocess protocol. Its strict
  request can represent only PNG line crops, crop SHA-256 and technical line
  IDs; it has no transcript/ground-truth field and rejects unknown fields.
- The default package uses only standard-library/Pydantic code. The external
  worker imports Torch/OpenCV/Pillow/Transformers lazily, validates the locally
  installed expected model SHA-256, and loads CRNN only through
  `torch.load(weights_only=True)` or TrOCR only through local `safetensors` with
  `trust_remote_code=False`. It never loads both providers in one process.
- Handwriting Studio’s **Import from photo** workflow now has a provider picker,
  provider-Python/model-root fields, timeout, progress, cancellation and a
  per-line result view. CRNN has a 1 GiB limit; TrOCR has 4 GiB. On Unix the
  worker applies that bound with `RLIMIT_AS`; the parent also owns timeout and
  terminate/kill cancellation.
- The selected frame is cropped only at persisted `line` regions. Immutable PNG
  crops are stored as photo derivatives; original photo bytes are never changed.
  Results are separate local content-addressed `hp-htr-run/1.0` records with
  source/crop/model/protocol provenance and reopen correctly for that manifest.
- Neither UI nor persistence invents confidence. Provider text is displayed line
  by line with a clear “not provided” confidence state. Worker failure/cancel
  records remain local and a subsequent fresh job is allowed to run.

### Configuration and verification

The user chooses the already-installed isolated provider Python and the directory
containing the two verified model folders in the UI. `HP_HTR_PYTHON` and
`HP_HTR_MODEL_ROOT` can prefill those fields; no download occurs. A one-line
CRNN local-worker smoke path completed after safe hash/weight verification.
The prior TASK 09 measured TrOCR runtime; no second benchmark or fine-tuning was
run here. A system interruption occurred during an additional TrOCR integration
smoke attempt, so TASK 10 does not claim a new TrOCR performance measurement.

Focused Linux checks:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_htr_integration.py \
  tests/learning/test_htr_benchmark.py \
  tests/gui/test_photo_import_gui.py
```

Result: `21 passed`. They cover protocol privacy, Unicode, missing weights,
timeout, cancellation, crash recovery, result persistence and non-blocking Qt
result display. `compileall` and `git diff --check` also pass.

### Post-TASK 10 verification checkpoint

- The former `test_properties_scroll_and_output_dock_use_non_overlapping_corner`
  failure was a real layout defect, not a flaky assertion: the dense, hidden
  Studio/HTR page propagated its `1361 × 936` minimum through `QStackedWidget`.
  A requested 900 × 620 document window was expanded by Qt to 1893 × 1201, so
  the Properties panel had no reason to scroll. `HandwritingStudio` now has an
  ignored size policy while hidden in the workspace stack; it no longer sets the
  document window minimum. The regression test now also asserts the requested
  900 × 620 geometry before asserting a nonzero Properties scrollbar.
- A single permitted private line crop completed in the new TrOCR subprocess.
  The worker emitted progress/complete, verified the pinned revision and weight
  hash, and did not receive or emit ground truth in the public report. This was
  a functional smoke check only, not a second benchmark.
- Linux `RLIMIT_AS` was independently read back as soft/hard `4,294,967,296`
  bytes in the provider environment. The same 4 GiB address-space limit allowed
  the TrOCR CPU smoke inference to complete. RSS was not used as a substitute
  for the virtual-memory limit.
- Final local Linux result: `QT_QPA_PLATFORM=offscreen uv run pytest -q` passed
  `308`; `python -m compileall -q src tests`, `uv lock --check`, and
  `git diff --check` passed. Windows was not run.

## TASK 09 — HTR model benchmark

Status: `[x]` DONE — bounded private single-page pilot; not an independent
page/session quality claim.

Completion commit: `b9a894bbe76f0751af5544a6e0928c733c899720`

### Private benchmark and safety boundary

- The user-authorized source image, exact transcription, 19 line boxes, model
  downloads, per-line predictions, checksums and raw reports are in a local
  private corpus outside the repository. No photo, transcription, large model
  weight, raw prediction or source hash was added to Git.
- Fifteen manually reviewed line crops formed the tuning partition; four were
  frozen as control. The public benchmark contract now rejects cross-partition
  predictions. This prevents a control transcription from entering provider
  input or selection accounting.
- The split is text-line-level because only one page was supplied. It is a
  useful first pilot but not independent by page or writing session; a second
  separately written and photographed page is needed before reporting that
  quality level.
- `Hukyl/crnn-rukopys` was SHA-256 checked and loaded on CPU only through
  `torch.load(..., weights_only=True)`. `Hukyl/trocr-rukopys` used verified local
  safetensors with `trust_remote_code=False`; providers ran in separate
  processes and never concurrently.

### Measured result

| Candidate/configuration | Selection set | CER / WER | Mean line time | Peak RSS | Outcome |
|---|---:|---:|---:|---:|---|
| CRNN raw reviewed crop + greedy CTC | tuning, 15 | 16.18% / 67.19% | 56.27 ms | ~350 MiB | CPU baseline |
| CRNN CLAHE + rule inpainting + greedy CTC | tuning, 15 | 22.61% / 85.94% | 54.40 ms | ~352 MiB | Rejected; worse |
| TrOCR raw reviewed crop + cached greedy generation | tuning, 15 | **11.11% / 46.88%** | 4.147 s | ~1.76 GiB | Selected |
| Selected TrOCR unchanged | control, 4 (one final run) | 34.92% / 60.00% | 3.681 s | ~1.74 GiB | Target not met |

The requested CER ≤ 5% outcome was not reached. Main visible error classes
were punctuation/hyphen handling, similar Cyrillic glyphs, rule/background
interference and narrow handwriting. Three final crop boxes were corrected by
manual segmentation review before the comparable runs; this did not expose
ground truth to either model. Exactly three configurations were evaluated, then
the selected configuration was run once on control without changing settings.

This task evaluates **HTR** (line image → text), not character/word
**segmentation** and not **stroke reconstruction** (pen paths/order). The latter
remain open work in TASK 12–17. TrOCR is the evidence-based quality candidate
for optional future integration; CRNN is the much faster/lighter fallback. No
provider is integrated into the default application yet.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/learning/test_htr_benchmark.py
```

Focused result: `5 passed`. Full-suite and static checks are recorded at the
final checkpoint after this documentation update. All measurements were on
local Linux; Windows was not executed.

## TASK 18 — Notebook page templates

Status: `[x]` DONE

Completion commit: `5646044a3dc88ad6966f09ae87a3ff6a6bc6b2e9`

### Implemented behavior

- Added portable `hp-desktop-project/1.6` `notebook_template` data with strict
  A4 portrait/landscape geometry, blank/squared/ruled modes, four margins,
  independent pitch and phase offsets in mm, normal/major colors and thicknesses.
  Projects from schema 1.0–1.5 migrate in memory with no template selected.
- Applying a template is undoable, persists with the project and synchronizes
  page orientation and margins. The canvas previews its paper lines in physical
  mm beneath artwork and handwriting, including a landscape A4 scene.
- **File → Notebook Page Template…** edits the settings. **File → Export →
  Notebook Background SVG…** writes a standalone physical A4 background. It is
  deliberately separate from Production/Diagnostic SVG, PenPlan and virtual
  G-code; changing only ink/paper styling does not add plotter operations.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/gui/test_notebook_templates.py \
  tests/gui/test_document.py \
  tests/gui/test_generation.py
```

Focused result: `49 passed in 8.55s`. These tests cover 5 mm/offset geometry,
portrait and landscape A4 SVG dimensions, ruled/blank modes, strict margins,
persistence/migration, undo, canvas preview, UI background export and exclusion
from production SVG/diagnostic SVG/G-code.

Final local Linux checkpoint: `QT_QPA_PLATFORM=offscreen uv run pytest -q` passed
`301`; `uv lock --check`, `python -m compileall -q src tests` and `git diff --check`
also passed. Windows was not executed locally.

## TASK 00 — Repository and research audit

Status: `[x]` DONE

Completion commit: `1363b001591910981a89ca4762876584c71a492b`

### Verified repository baseline

- CADPisun is a Python 3.12 modular monolith with a Qt-free core, optional
  PySide6 desktop UI, immutable StylePacks, deterministic shaping/layout,
  validated PenPlan, SVG, MotionPlan, and simulation-only virtual G-code.
- `HandwritingStudio` already implements immutable `hp-capture/1.0` online
  pointer sessions, processing, shared style metrics, manual annotations,
  append-only draft history, and test-only personal StylePack publication.
- There is no `handwriting_plotter.learning`, photo source model, CV pipeline,
  HTR provider, image-to-text alignment, or offline reconstruction module.
- The document project schema and imported `ArtworkObject` are not suitable as
  training-data storage. Artwork is a document reference layer and is explicitly
  excluded from PenPlan; photo learning needs its own source/derivative graph.
- Root architecture already reserves stage II contracts for immutable source
  assets, image transforms, regions, transcriptions, reconstruction candidates,
  correction events, dataset snapshots, and model records.
- Frankenstein Level B proves the reusable downstream boundary:
  `capture -> processed -> normalized -> reviewed annotation -> StylePack`.
  Offline candidates must adapt to this boundary instead of creating a new font
  or renderer.

### Decisions recorded

- New code belongs in a Qt-free `learning` package plus optional image and HTR
  adapters. GUI code owns presentation only.
- Original photo bytes and derived artifacts are content-addressed. Manifests
  use canonical JSON and safe relative paths; writes are atomic.
- Semantic and geometric information remain parallel until explicit alignment.
- Offline stroke reconstruction stores multiple hypotheses and separate text,
  segmentation, geometry, and order confidence values.
- Existing StylePack publication remains the only route into generation.
- Kraken/TrOCR/CRNN dependencies are not added to the default environment.

### Research completed

The pinned sources, licenses, artifact sizes, algorithm observations, and
integration consequences are in `RESEARCH.md`. Key findings:

- HandwritingDatasetGen documents relevant skeleton graph and traversal ideas,
  but the audited repository has no declared license. Its code cannot be copied.
- Kraken 7.1.1 is Apache-2.0 and supports baseline/region segmentation,
  recognition, character cuts, and newer task APIs, but its large dependency
  stack should stay in an isolated provider environment.
- Ukrainian line recognizers vary from a 43 MB CRNN checkpoint to 1.34 GB and
  2.23 GB TrOCR weights. Published CER values use different datasets and
  preprocessing and are not a CADPisun benchmark.
- OpenCV provides the required deterministic rectification and ruling tools;
  `doc-scan` is an algorithm reference with no license file at the pinned commit.
- VHS remains an AGPL-3.0 workflow reference; no source is copied.

### Verification

Executed from the repository root on Linux:

An inline Python `pathlib` validator confirmed five required files, 25 ordered TASK rows,
clean trailing whitespace, and no missing local Markdown links. No permanent
validation script was added because this task changes documentation only.

```bash
git diff --check
```

Result: passed with no whitespace errors.

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Result: `223 passed in 23.73s`.

No model weights, datasets, or user photographs were downloaded. Windows was
not executed locally during TASK 00.

## TASK 01 — Canonical photo import model

Status: `[x]` DONE

Completion commit: `1a271b0db6bd69f5173b9439d41d0662cbdae96b`

### Implemented behavior

- Added strict Qt-free `hp-notebook-photo/1.0` models for exact original hash,
  import metadata, pixel/optional physical page dimensions, coordinate frames,
  invertible image transforms, bounded canonical parameters, regions, ruling
  placeholders, rights state, and confidence provenance.
- Added content-addressed immutable storage. Original bytes and canonical
  manifests have independent SHA-256 addresses, atomic link/fsync publication,
  tamper detection, idempotent repeat import, safe relative paths, and load/list
  APIs. Changing or deleting the external source after import cannot change the
  stored record.
- Added explicit default limits: 32 MiB encoded bytes, 60 million decoded
  pixels, 20,000 px per side, and 8 MiB manifest. Both decoder and repository
  enforce relevant limits; direct repository calls cannot bypass pixel limits.
- Added an optional `QImageReader` adapter that content-detects and fully decodes
  PNG, JPEG, WebP, BMP, and static GIF without applying hidden EXIF transforms.
  Multi-frame, SVG, PDF, corrupt, unsupported, and oversized inputs are rejected.
- The adapter imports PySide6 only when selected. Importing
  `handwriting_plotter.learning` in the base environment does not load Qt.
- During regression work, Qt 6.12 on the current Linux host segfaulted while
  decoding a tiny TIFF it had encoded. TIFF was removed from the allowlist and
  is not claimed as supported until a separately isolated cross-platform check
  proves it safe.
- `DATA_MODELS.md`, `MODULE_CONTRACTS.md`, and `TECH_STACK.md` now document the
  implemented schema, import boundary, safety limits, and dependency boundary.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/learning/test_photo_import.py
```

Result: `20 passed in 0.74s`. This includes real Qt encode/decode for PNG, JPEG,
WebP, BMP, and a real static GIF fixture; canonical round trip; source mutation;
tampered bytes/manifests; duplicate JSON; unknown schema; file/pixel/dimension
limits; unsafe/canonical paths; symlink escape; transform/region/confidence/scale
invariants; explicit pre-decode TIFF rejection; and the Qt-free core import boundary.

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Result: `243 passed in 23.47s`.

```bash
uv build --out-dir /tmp/cadpisun-task01-build-20261023
```

Result: source distribution and wheel built successfully; wheel inspection
confirmed all `learning` and `adapters/images` modules are packaged.

Linux was executed locally. Windows behavior remains unverified in this task;
the repository CI installs the GUI extra on Windows, but this feature branch has
not yet run a pull-request workflow.

## TASK 02 — Photo import UI

Status: `[x]` DONE

Completion commit: `1ad775128f822a80623c781fe9159657c12d57df`

### Implemented behavior

- Added a dedicated **Import from photo** workflow inside Handwriting Studio.
  It remains separate from the document canvas and from online pointer capture.
- The system file picker accepts the formats actually supported by the TASK 01
  decoder: PNG, JPEG, WebP, BMP, and static GIF. Successful imports use the
  existing bounded decoder and immutable content-addressed repository.
- Original and corrected-preview viewers appear side by side with synchronized
  zoom out/in, 1:1, fit, reset, and 90-degree preview rotation. Rotation never
  mutates exact source bytes or records a transform that has not been produced
  by the future correction pipeline.
- The right viewer explicitly says that perspective correction has not run.
  Diagnostics expose the content-detected format/media type, dimensions,
  encoded size, embedded orientation, display rotation, original SHA-256,
  immutable manifest path, ruling state, and correction state.
- Invalid files produce an inline error while preserving the last verified
  image. The latest verified import is restored from immutable storage when the
  workspace reopens; a missing or tampered record is reported rather than used.
- English and Ukrainian UI text and the desktop usage guide were updated. The
  tabs are positioned beside the workspace so adding photo import does not
  change capture-canvas height or saved guide geometry.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/gui/test_photo_import_gui.py \
  tests/gui/test_studio.py \
  tests/learning/test_photo_import.py
```

Result: `35 passed in 3.43s`. The six new GUI tests cover exact source storage,
side-by-side previews and diagnostics, zoom/rotation/reset without mutation,
invalid input, latest-photo restore, file-picker/Ukrainian text, and isolation
from online capture.

```bash
git diff --check
uv run python -m compileall -q src tests
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Result: `249 passed in 23.37s`; whitespace and bytecode compilation checks
passed.

```bash
uv build --out-dir /tmp/cadpisun-task02-build-jnln3R
```

Result: source distribution and wheel built successfully; wheel inspection
confirmed the new GUI module and its Studio/i18n integration are packaged.

Visual QA used an offscreen 1440×900 full `MainWindow` with a generated ruled
PNG fixture. Both previews, controls, notices, diagnostics, and side workflow
tabs were visible without overlap. The temporary screenshot was not committed.

Linux was executed locally. Windows was not executed during TASK 02.

## TASK 03 — Perspective and page correction

Status: `[x]` DONE

Completion commit: `332b1d75f291858d231ddd654f1296d8733d9173`

### Implemented behavior

- Added Qt-free corner/proposal/correction contracts with clockwise convex
  four-corner validation, bounded output dimensions, forward/inverse 3×3
  matrices, explicit frame IDs, and content-addressed derivative persistence.
- Added optional `photo-cv` with pinned
  `opencv-python-headless==4.13.0.92` and locked NumPy 2.2.6. The adapter uses
  local blur, Canny, morphology, contour/quad filtering, homography, crop, PNG
  encoding, and optional fine deskew. Core/base imports do not load cv2/NumPy.
- All eight recorded orientation values have explicit raster operations and
  matrices. Orientation, homography, and deskew compose into one source-to-
  corrected transform; the inverse is stored and tested.
- Output aspect ratio derives from the selected quadrilateral's opposing edge
  lengths. The implementation never stretches a source to assumed A4 geometry.
- Studio now displays automatic heuristic proposals as four colored draggable
  handles. Manual corners use the identical correction path. No-page results
  recommend the manual fallback and explicitly state that curved pages require
  a future dewarping workflow.
- Applying a correction writes a SHA-256-addressed PNG plus a new immutable
  photo manifest containing the output frame, homography, source page polygon,
  algorithm/version, parameters, and artifact path. Original bytes and earlier
  manifests remain unchanged; identical reapplication is idempotent.
- The last correction restores with its real rectified preview. English and
  Ukrainian UI, install instructions, data/contracts/stack documentation,
  benchmark record, and CI dependency installation were synchronized.

### Verification

```bash
uv run pytest -q tests/learning/test_page_correction.py
```

Result: `13 passed in 1.00s`. Coverage includes corner ordering/rejection,
automatic/no-page proposal, manual persistence, all eight orientation matrices,
homography round trip, optional deskew, immutable source/derivative tampering,
idempotent persistence, and reopen.

```bash
uv lock --check
git diff --check
uv run python -m compileall -q src tests
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Result: `264 passed in 26.49s`; lock, whitespace, and bytecode compilation
checks passed.

```bash
uv build --out-dir /tmp/cadpisun-task03-build-gygCzT
```

Result: sdist and wheel built successfully. Wheel inspection found the new
correction and OpenCV adapter modules. Installing the wheel without extras in a
fresh Python 3.12.12 venv imported `handwriting_plotter.learning` without cv2 or
NumPy.

The committed clean 840×640 synthetic page fixture produced corner RMSE/max
`0 px`; a 12×12 corrected-frame grid produced forward/inverse reprojection RMSE
`1.24442785236e-13 px` and max `2.42835191822e-13 px`. These measurements prove
the clean synthetic path and matrix math only, not real-photo quality.

Visual QA used the full 1440×900 `MainWindow` with an angled generated notebook
page. The automatic handles aligned with the quadrilateral and the 817×530
rectified result, controls, notice, and diagnostics displayed without overlap.
The temporary screenshot was not committed.

Linux was executed locally. Windows was not executed during TASK 03; CI is
configured to install `photo-cv` on Linux and Windows when a pull request runs.

## Open blockers and gates

| ID | Scope | State | Unblock condition |
|---|---|---|---|
| PH-BLK-001 | Genuine handwriting quality | BLOCKED for real-quality claims | User supplies local photos with rights/consent plus verified transcriptions and visual review |
| PH-BLK-002 | HTR winner | DEFERRED to TASK 09 | Identical CADPisun benchmark crops, checksummed weights, measured CPU time/RAM/CER/WER |
| PH-BLK-003 | Historical stroke order | PERMANENT uncertainty | Only paired online recordings can measure order; photo-only results stay `offline_inferred` |
| PH-BLK-004 | HandwritingDatasetGen code reuse | BLOCKED | Upstream adds a compatible explicit license; until then use papers/behavior as references only |
| PH-BLK-005 | Windows CV/ML behavior | UNVERIFIED | Windows CI/runtime tasks execute the implemented provider and image fixtures |

None of these blocks TASK 06.

## TASK 04 — Notebook paper classification

Status: `[x]` DONE

Completion commit: `fd22492b33d826558254accfd861d4813b3abed1`

### Implemented behavior

- Added the Qt-free `RulingClassifier` boundary and immutable persistence for a
  `RulingEstimate`. A proposed result and a manual override create new canonical
  manifests while retaining exact original bytes and existing derivatives.
- Optional `OpenCvRulingClassifier` finds repeated long horizontal and vertical
  line evidence with threshold/morphology operations. It returns only
  blank/squared/ruled/mixed/unknown, a method ID, and heuristic confidence;
  values are not presented as calibrated accuracy.
- Paper analysis in Handwriting Studio uses the latest corrected frame when it
  exists. The workspace exposes the proposal and confidence, localized manual
  selection, diagnostics, saved human override, and restoration of the latest
  override revision.
- No grid/ruling pitch, phase, origin, overlay, physical scale, paper removal,
  OCR, or learning model was added. Geometry fields remain empty by design until
  TASK 05–06.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_ruling_classification.py \
  tests/learning/test_page_correction.py \
  tests/gui/test_photo_import_gui.py
```

Result: `29 passed in 1.51s`. The suite covers all five synthetic classes,
short handwriting over ruled paper, sparse table/dense-mark interference,
unknown content, invalid frame rejection, immutable proposal/override save and
reopen, and classification after rectification.

```bash
uv lock --check
git diff --check
uv run python -m compileall -q src tests
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv build --out-dir /tmp/cadpisun-task04-build
```

Result: lock, whitespace, bytecode compilation, sdist, and wheel passed;
the full local Linux suite was `272 passed in 32.15s`.

Visual QA used an offscreen 1440×960 workspace with a generated ruled page.
Analyze paper, selector, override button, 95% heuristic summary, preview panes,
status, and diagnostics were visible with no overlap. The temporary screenshot
was not committed. Windows was not executed locally.

## TASK 05 — Grid and ruled-line detection

Status: `[x]` DONE

Completion commit: `6b660c4c4a607be2f2cf0ecd208dafe7f2a56777`

### Implemented behavior

- Added a Qt-free geometry-estimator port and optional OpenCV implementation.
  It uses Canny, probabilistic Hough segments, median direction, de-duplicated
  line coordinates, and a bounded periodic fit to derive image-space pitch,
  phase/origin, direction and residual.
- The estimator requires four repeated long lines. It handles the committed
  skew/opaque-mark/crossing-ink fixtures and rejects the sparse table-border
  negative. Only `ruled` and `squared` classifications can own geometry.
- Extended `RulingEstimate` additively with optional angles and residuals;
  pre-existing manifests stay valid. Pixel geometry has no implied physical
  size. Manual geometry creates a human immutable override.
- Studio now offers Detect spacing, aligned magenta overlay, residual summary,
  localized pixel pitch/origin/angle controls, save/reopen and a corrected-frame
  analysis path. Preview rotation hides the overlay until it can align again.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_ruling_classification.py \
  tests/learning/test_ruling_geometry.py \
  tests/gui/test_photo_import_gui.py
```

Result: `21 passed in 2.51s`. Tests cover known 40 px pitch, phase/origin,
directions, grid intersections, occlusion, crossing ink, sparse table negative,
manual persistence and GUI overlay/reopen.

```bash
uv lock --check
git diff --check
uv run python -m compileall -q src tests
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv build --out-dir /tmp/cadpisun-task05-build
```

Result: lock, whitespace, bytecode compilation, sdist, and wheel passed; the
full local Linux suite was `277 passed in 35.56s`.

Visual QA used an offscreen 1440×1000 generated 40 px grid. The magenta overlay
matched the blue source grid, and all measurement/manual controls, summary,
preview panes, status and diagnostics were visible with no overlap. Windows was
not executed locally.

## TASK 06 — Physical-scale calibration

Status: `[x]` DONE

Completion commit: `0347fe7d52e9645b0671d6b29865eb692e5cf11b`

### Implemented behavior

- Added a Qt-free, frame-bound `PhysicalScaleCalibration` that preserves source,
  method, optional axis uncertainties and a declared reference pitch. Detection
  never creates this record: it is saved only through an entered reference or
  the explicit 5 mm notebook preset.
- Added ruling-relative and metric conversions that use the measured normal
  axes, including skewed grids. Ruled pages deliberately leave X physical
  position unknown because only the horizontal rule family was measured.
- Studio now exposes the reference size and two explicit save actions after
  geometry exists. The saved calibration survives reopen and appears in
  diagnostics. Any ruling estimate replacement clears calibration to prevent a
  stale scale from silently using changed geometry.

### Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/learning/test_physical_scale_calibration.py \
  tests/learning/test_ruling_geometry.py \
  tests/learning/test_ruling_classification.py \
  tests/gui/test_photo_import_gui.py
```

Result: `27 passed in 1.98s` during the focused run (one later conversion test
was added before the full run). It covers explicit 5 mm and manual references,
axis availability, rotated axes, strict frame matching, immutable persistence,
GUI persistence/reopen and geometry-change invalidation.

```bash
uv lock --check
git diff --check
uv run python -m compileall -q src tests
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv build --out-dir /tmp/cadpisun-task06-build-2
```

Result: lock, whitespace, bytecode compilation, sdist and wheel passed; the
full local Linux suite was `283 passed in 28.34s`. Visual QA used an offscreen
1326×900 workspace and confirmed the disabled-until-geometry calibration row
fits alongside the existing photo controls. Windows was not executed locally.

## Historical next-task estimate after TASK 06

**TASK 07 — Paper/ink separation**

- Recommended tier: HIGH.
- Complexity: 11/12 (raw/cleaned masks, colored ruling, shadows, intersections,
  provenance, GUI review and synthetic/private fixture boundaries).
- Estimated implementation: 15k–30k tokens and should split algorithm and UI
  if verification becomes too broad.
- Relative quota pressure: HIGH.
- Main uncertainty: preserving every handwriting pixel at rule intersections,
  dots and diacritics without turning synthetic success into a real-photo claim.

Recommended message at the next boundary:

> Рекомендую HIGH: следующая задача должна добавить paper/ink masks с ручной
> проверкой и строгими fixtures, не начиная OCR или выдумывая real-photo quality.
