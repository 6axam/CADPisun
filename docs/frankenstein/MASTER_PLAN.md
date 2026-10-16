# Project Frankenstein — execution plan

This file is the durable execution index for the personal-handwriting workflow. The detailed requirements remain in the user-approved Project Frankenstein brief; this table records dependency order, acceptance evidence, and implementation state.

States: `TODO`, `IN_PROGRESS`, `DONE`, `BLOCKED`.

| Phase | Deliverable | Depends on | Acceptance evidence | State |
|---|---|---|---|---|
| 00 | Architecture and source audit | current `main` | baseline tests, integration map, licensed source audit | DONE |
| 01 | Canonical `hp-capture/1.0` raw format | 00 | strict round-trip, malformed/resource-limit tests | DONE |
| 02 | Qt pointer capture engine | 01 | two directed strokes preserved; mouse/tablet duplicate guard | DONE |
| 03 | Integrated Handwriting Studio | 02 | save, leave, return, reopen sample | DONE |
| 04 | Capture queues and coverage | 03 | five-token capture without manual filenames | DONE |
| 05 | Variant management | 04 | three `м` variants browsable and selectable | DONE |
| 06 | Directed-stroke processing | 01, 05 | two tolerances, bounded deviation, shared raw source | DONE |
| 07 | Common glyph metrics | 06 | coherent `а м н о и` baseline/x-height | DONE |
| 08 | Join annotation | 07 | pair preview reports join/lift/rejection | DONE |
| 09 | Recorded ligatures | 08 | captured `ма` selected through PenPlan | DONE |
| 10 | Personal StylePack publication | 05–09 | immutable test-only revision appears in normal picker | DONE |
| 11 | Complete Level B workflow | 10 | `мама мимо мана мина` → SVG and virtual G-code | DONE |
| 12 | Natural variation v2 | 11 | deterministic bounded variation and anti-repeat tests | TODO |
| 13 | GUI realism controls | 12 | controls persist and regenerate deterministic output | TODO |
| 14 | Multi-page composition | 13 | page navigation and complete artifact export | TODO |
| 15 | Safe travel optimization | 14 | no draw-order/reversal change; measured travel comparison | TODO |
| 16 | Virtual calibration | 15 | persisted simulation-only calibration profile | TODO |
| 17 | Stabilization and release | 16 | Linux/Windows CI, docs, performance and recovery checks | TODO |

## Delivery rules

- Each phase starts with a reproducing or acceptance test and ends with the relevant test suite.
- Raw recordings are immutable. Edits create metadata or processed derivatives linked by SHA-256.
- Capture/processing/domain code remains Qt-free; Qt event translation and widgets stay under `gui/`.
- Built-in packages remain immutable. Drafts and user StylePacks live in a platform application-data directory.
- Published user revisions use the existing StylePack schema and `FileStyleRepository` integrity verification.
- Synthetic data is always marked as such. It can prove the pipeline but cannot establish handwriting quality or independent review.
- Hardware transport, OCR, and mandatory neural dependencies remain outside this execution plan.

