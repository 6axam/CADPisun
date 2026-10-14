# Project Frankenstein — progress

Last updated: 2026-10-14.

## Current checkpoint

- Branch: `codex/frankenstein-handwriting-studio`
- Base commit: `011ec7a3764fd637765aeb38dd815ec5f1b047bd`
- Phase: 06 — stroke normalization and processing
- Last completed phase: 05 — glyph variant management
- Phase 00 commit: `7d0f875`
- Phase 01 commit: `67fa1cf`
- Phase 02 commit: `417f362`
- Phase 03 commit: `1dd1204`
- Phase 04 commit: `f0ca242`
- Phase 05 commit: see the commit named `feat: manage multiple captured glyph variants` (recorded at the next checkpoint).
- Next concrete action: implement duplicate filtering, resampling, smoothing, simplification, fitting and measured source deviation.

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

### Phase 06 — IN_PROGRESS

- Keep the processing module Qt-free and derivatives linked to capture SHA-256.
- Certify maximum source-to-result deviation for every processed stroke.
- Preserve direction, boundaries, corners, loops, and small marks without path reversal.

