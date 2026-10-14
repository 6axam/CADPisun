# Project Frankenstein — progress

Last updated: 2026-10-14.

## Current checkpoint

- Branch: `codex/frankenstein-handwriting-studio`
- Base commit: `011ec7a3764fd637765aeb38dd815ec5f1b047bd`
- Phase: 02 — Qt pointer capture engine
- Last completed phase: 01 — raw handwriting data model
- Phase 00 commit: `7d0f875`
- Phase 01 commit: see the commit named `feat: add versioned raw handwriting capture format` (recorded at the next checkpoint).
- Next concrete action: translate mouse/tablet/touch events into ordered raw strokes and suppress synthesized mouse duplicates.

## Validation ledger

| Date | Scope | Result |
|---|---|---|
| 2026-10-14 | Baseline, Python 3.12.12, `QT_QPA_PLATFORM=offscreen`, locked dev/import-svg/gui-dev extras | 150 passed in 13.38 s |
| 2026-10-14 | Phase 01 focused capture-format suite | 10 passed in 0.37 s |
| 2026-10-14 | Phase 01 full Linux headless regression | 160 passed in 12.44 s |

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

### Phase 02 — IN_PROGRESS

- Reusable capture widget remains isolated under `gui/`.
- Raw points remain in a fixed logical-pixel frame; no simplification runs in event handlers.
- Tablet/mouse source arbitration needs a regression test for synthesized mouse events.

