# Photo-to-Handwriting progress

Last updated: 2026-10-23

## Current checkpoint

| Field | Value |
|---|---|
| Branch | `feat/photo-to-handwriting` |
| Base | `main` at `05cbc014fc6d97d052f55e56a00e32eeee942a59` |
| Completed | 1 / 25 tasks |
| Last completed | TASK 00 — Repository and research audit |
| Next | TASK 01 — Canonical photo import model |
| Actual remaining Codex quota | Unknown; the runtime did not report it |

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

## Open blockers and gates

| ID | Scope | State | Unblock condition |
|---|---|---|---|
| PH-BLK-001 | Genuine handwriting quality | BLOCKED for real-quality claims | User supplies local photos with rights/consent plus verified transcriptions and visual review |
| PH-BLK-002 | HTR winner | DEFERRED to TASK 09 | Identical CADPisun benchmark crops, checksummed weights, measured CPU time/RAM/CER/WER |
| PH-BLK-003 | Historical stroke order | PERMANENT uncertainty | Only paired online recordings can measure order; photo-only results stay `offline_inferred` |
| PH-BLK-004 | HandwritingDatasetGen code reuse | BLOCKED | Upstream adds a compatible explicit license; until then use papers/behavior as references only |
| PH-BLK-005 | Windows CV/ML behavior | UNVERIFIED | Windows CI/runtime tasks execute the implemented provider and image fixtures |

None of these blocks TASK 01.

## Next task estimate

**TASK 01 — Canonical photo import model**

- Recommended tier: MEDIUM.
- Complexity: 6/12 (architecture 1, modules 1, algorithms 0, examples 1,
  testing 1, regression risk 1, expected iteration 1).
- Estimated implementation: 6k–12k tokens, roughly 15–30 tool calls, 5–8 files.
- Relative quota pressure: MEDIUM.
- Main uncertainty: choosing strict decoded-pixel/decompression limits that work
  consistently through the Qt image adapter on Linux and Windows.
- Natural split if needed: models/repository first, real decoder/security tests
  second. Both are required before TASK 01 can be DONE.

Recommended message at the next boundary:

> Рекомендую переключить Codex на MEDIUM, потому что следующая задача — строго
> типизированные модели, безопасное файловое хранение и известные тесты импорта.
> Сильная модель здесь не нужна.
