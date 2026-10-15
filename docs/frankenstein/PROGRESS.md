# Project Frankenstein — progress

Last updated: 2026-10-15.

## Current checkpoint

- Branch: `codex/frankenstein-handwriting-studio`
- Base commit: `011ec7a3764fd637765aeb38dd815ec5f1b047bd`
- Phase: 10 — personal StylePack builder
- Last completed phase: 09 — multi-character samples and ligatures
- Phase 00 commit: `7d0f875`
- Phase 01 commit: `67fa1cf`
- Phase 02 commit: `417f362`
- Phase 03 commit: `1dd1204`
- Phase 04 commit: `f0ca242`
- Phase 05 commit: `5b0bc0c`
- Phase 06 commit: `b33b48c`
- Phase 07 commit: `f08da52`
- Phase 08 commit: `65ecc97`
- Phase 09 commit: see the commit named `feat: support recorded cursive ligatures` (recorded at the next checkpoint).
- Next concrete action: assemble reviewed annotations and normalized derivatives into an immutable, loadable test-only StylePack revision.

## Validation ledger

| Date | Scope | Result |
|---|---|---|
| 2026-10-14 | Baseline, Python 3.12.12, `QT_QPA_PLATFORM=offscreen`, locked dev/import-svg/gui-dev extras | 150 passed in 13.38 s |
| 2026-10-14 | Phase 01 focused capture-format suite | 10 passed in 0.37 s |
| 2026-10-14 | Phase 01 full Linux headless regression | 160 passed in 12.44 s |
| 2026-10-14 | Phase 02 focused Qt capture suite | 4 passed in 0.52 s |
| 2026-10-14 | Phase 02 full Linux headless regression | 164 passed in 12.40 s |
| 2026-10-14 | Phase 03 focused Studio/Qt shell suite | 15 passed in 3.27 s |
| 2026-10-14 | Phase 03 full Linux headless regression | 167 passed in 12.18 s |
| 2026-10-14 | Phase 04 queue/Studio focused suites | 7 passed in 1.24 s |
| 2026-10-14 | Phase 04 full Linux headless regression | 171 passed in 13.81 s |
| 2026-10-14 | Phase 05 draft/variant focused suites | 7 passed in 1.29 s |
| 2026-10-14 | Phase 05 full Linux headless regression | 174 passed in 12.65 s |
| 2026-10-15 | Phase 06 processing/Qt focused suites | 18 passed in 2.56 s |
| 2026-10-15 | Phase 06 full Linux headless regression | 183 passed in 13.86 s |
| 2026-10-15 | Phase 06 strict-tolerance processing benchmark | median 0.5574 s over 7 runs |
| 2026-10-15 | Phase 07 metrics/Studio focused suites | 12 passed in 3.00 s |
| 2026-10-15 | Phase 07 full Linux headless regression | 189 passed in 15.40 s |
| 2026-10-15 | Phase 08 annotation/Studio focused suites | 12 passed in 3.48 s |
| 2026-10-15 | Phase 08 full Linux headless regression | 194 passed in 13.76 s |
| 2026-10-15 | Phase 09 ligature/PenPlan focused suite | 5 passed in 0.53 s |
| 2026-10-15 | Phase 09 full Linux headless regression | 195 passed in 16.86 s |

The first test attempt could not start because the existing local environment did not contain the dev extra (`pytest` executable absent). `uv sync --locked --python 3.12.12 --extra dev --extra import-svg --extra gui-dev` restored the locked environment; this was an environment prerequisite, not a failing project test.

## Phase history

### Phase 00 — DONE

- Traced document generation, StylePack loading, shaping, Qt coordinates, worker lifetime, cached artifacts, and reusable geometry.
- Chose a composite read catalog with explicit source locations and a dedicated writable user root.
- Kept `FileStyleRepository` as the single integrity and publication boundary.
- Audited the five named donor projects at exact commits. No donor source was copied.
- Added the persistent execution, decision, validation, source-audit, and architecture-audit records.

### Phase 01 — DONE

- Required schema: `hp-capture/1.0`.
- Required invariants: ordered unique strokes and points, finite coordinates, optional monotonic time, honest optional pressure, explicit coordinate frame and guide dimensions.
- Required persistence: strict canonical JSON, maximum size/point budgets, source hash verification, atomic create, and no in-place overwrite.

Implemented all listed invariants in Qt-free `capture` models and a content-addressed repository. The synthetic two-stroke fixture is explicitly marked and round-trips without changing point order or coordinates.

### Phase 02 — DONE

- Reusable capture widget remains isolated under `gui/`.
- Raw points remain in a fixed logical-pixel frame; no simplification runs in event handlers.
- Tablet/mouse source arbitration has a regression test for synthesized mouse events.

The widget captures mouse, tablet/stylus and a practical single-touch stream,
uses process-monotonic elapsed time, records pressure only when the pointing
device exposes that capability, locks its raw frame across resizes, and keeps
undo/redo at whole-stroke granularity. The synthesized-mouse regression proves
that a tablet event cannot create a duplicate mouse stroke.

### Phase 03 — DONE

- Added a real Document/Studio workspace switch without replacing the document controller.
- Persisted raw samples under the platform application-data root.
- Wired save, clear, undo/redo, guide/point diagnostics, and sample retrieval.
- Added English and Ukrainian UI strings for every visible Studio action.

The main window now owns a persistent Document/Studio stack. Studio writes
immutable `hp-capture/1.0` records to the platform application-data root,
shows actual sample counts and validation, and reopens saved records by label
after a new widget/process lifetime. All visible capture, view, guide, language,
search, save, and retrieval controls are connected to real behavior.

### Phase 04 — DONE

- Promoted the glyph list into a persistent configurable queue.
- Added previous/current/next, skip, retry, save-and-next, required variants, and coverage totals.
- Kept queue state as editable metadata outside immutable raw captures.

The persistent queue supports previous/next, skip, retry, save-and-next, open,
reject and resume. Ukrainian, Russian, English and custom token sets share one
strict queue model. Coverage is calculated from actual immutable records after
draft rejection and the required experimental variant count is configurable.
The acceptance test records `а м и н о` in sequence and resumes at `о` in a new
Studio instance.

### Phase 05 — DONE

- Added a visible per-token variant browser with thumbnails and selection.
- Moved context/preferred/rejected/deleted state into a versioned editable draft catalog.
- Preserved raw hashes and review history for every metadata revision.

Three separately captured `м` variants are displayed side by side with rendered
thumbnails. A user can reopen any variant, select one preferred variant, reject
poor input, or remove it from the editable draft. Preferred/review/delete
changes append history events. Deleted captures remain byte-verified in the raw
repository and are recovered in the audit catalog after restart.

### Phase 06 — DONE

- Keep the processing module Qt-free and derivatives linked to capture SHA-256.
- Certify maximum source-to-result deviation for every processed stroke.
- Preserve direction, boundaries, corners, loops, and small marks without path reversal.

The Qt-free pipeline filters consecutive duplicates, resamples while retaining
source vertices, optionally smooths non-corner points, simplifies protected
spans, and fits existing Line/Quadratic/Cubic primitives. Every candidate is
checked against the original directed polyline with a conservative symmetric
error upper bound; a candidate that exceeds the requested tolerance falls back
to less simplified geometry instead of weakening the tolerance.

`hp-processed-capture/1.0` derivatives are canonical, immutable,
content-addressed, parameter-complete, and linked to their verified raw SHA-256.
Studio overlays Raw/Processed geometry, invalidates stale overlays when source
or parameters change, restores saved derivatives, and removes processing
without modifying raw points. The acceptance suite processes one sample at two
tolerances and verifies both links and error limits.

### Phase 07 — DONE

- Keep the raw logical-pixel frame explicit and immutable.
- Map guides and reviewed processed geometry into existing GlyphFrame `gu` conventions.
- Persist advances and side bearings without distorting natural proportions.

`hp-style-metrics/1.0` now fixes a shared logical-pixel frame and common guide
calibration for a draft style. `hp-normalized-glyph/1.0` applies the same
uniform `1000 gu / source x-height` transform to every glyph, stores analytical
bounds and actual bearings, and verifies raw/processed/profile hashes before
persistence. Manual advance, bearing, baseline-offset, and physical-preview
values are explicit and versioned.

The five-glyph acceptance fixture (`а`, `м`, `н`, `о`, `и`) shares one baseline
and x-height reference. Its smaller `о` remains proportionally shorter than
the tall `а`, proving that no per-glyph bounding-box height normalization runs.
Studio provides a real GlyphFrame preview with millimetre dimensions and
restores the immutable normalized derivative after restart.

### Phase 08 — DONE

- Keep annotation manual and auditable; never infer joins from appearance alone.
- Persist stroke roles, mark scheduling and anchor constraints separately from geometry sources.
- Validate annotation against the normalized glyph before publication.

`hp-glyph-annotation/1.0` stores exact normalized/processed source hashes,
original stroke order, manual roles, one body, ordered deferred marks, actual
endpoint tangents, anchor constraints, context tags, critical marks and forced
pen lifts. Contiguous revisions are revalidated against the full immutable
source chain. Conversion produces only a draft existing `GlyphVariantFile`.

Studio exposes functional stroke-role/body/anchor/no-join controls, shows the
derived tangent vectors, and persists/reopens annotation revisions. Pair preview
uses the existing placement and geometry-aware join engine and visually reports
`connected`, intentional `pen_lift`, or `rejected` with the exact engine reason.
Tests cover all three decisions and prove multistroke/mark order is unchanged.

### Phase 09 — DONE

- Treat sequence captures as explicit candidates, never inferred text substitutions.
- Keep individual-glyph fallback mandatory and longest-match behavior deterministic.
- Preserve the recorded sequence as one directed multi-stroke unit with provenance.

Sequence annotations now carry an explicit `unannotated` state or exactly N−1
manual GlyphFrame boundaries. The recorded geometry remains one ordered unit.
`build_recorded_ligature` rejects a candidate unless every constituent grapheme
has an individual fallback and returns the existing multi-key GlyphVariant
format rather than adding string substitution.

The acceptance test captures `ма` as one directed stroke, normalizes and
annotates it, then lays out `мама` with a StyleSnapshot containing both
individual letters and the recorded sequence. Existing longest-match resolution
selects two `ма` variants; the compiled PenPlan contains two preserved draws and
is deterministic. Removing the sequence naturally exercises individual glyphs.

### Phase 10 — IN_PROGRESS

- Build only from reviewed, source-verified normalized annotations.
- Publish through FileStyleRepository with canonical hashes and a new immutable revision.
- Keep Level B output explicitly test-only and production-ineligible.

