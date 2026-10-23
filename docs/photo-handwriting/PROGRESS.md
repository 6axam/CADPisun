# Photo-to-Handwriting progress

Last updated: 2026-10-23

## Current checkpoint

| Field | Value |
|---|---|
| Branch | `feat/photo-to-handwriting` |
| Base | `main` at `05cbc014fc6d97d052f55e56a00e32eeee942a59` |
| Completed | 2 / 25 tasks |
| Last completed | TASK 01 — Canonical photo import model |
| Next | TASK 02 — Photo import UI |
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

## TASK 01 — Canonical photo import model

Status: `[x]` DONE

Completion commit: `PENDING_RECORD`

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

**TASK 02 — Photo import UI**

- Recommended tier: MEDIUM.
- Complexity: 6/12 (architecture 1, modules 1, algorithms 0, examples 1,
  testing 1, regression risk 1, expected iteration 1).
- Estimated implementation: 7k–14k tokens, roughly 18–35 tool calls, 6–10 files.
- Relative quota pressure: MEDIUM.
- Main uncertainty: fitting original/corrected comparison, zoom/rotation and
  diagnostics into Handwriting Studio without regressing its dense existing UI.
- Natural split if needed: workspace/viewer first, then import persistence and
  headless interaction tests. Both are required before TASK 02 can be DONE.

Recommended message at the next boundary:

> Рекомендую переключить Codex на MEDIUM, потому что следующая задача — обычный
> PySide6 workspace поверх уже готового import contract и headless UI-тесты.
> Сильная модель здесь не нужна.
