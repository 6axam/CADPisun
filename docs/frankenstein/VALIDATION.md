# Project Frankenstein — validation record

## Environment

- Host checked: Linux (Arch/Omarchy), 2026-10-14
- Python: 3.12.12
- uv: 0.12.23
- PySide6: 6.12.0
- Qt test platform: `offscreen`
- Dependency source: committed `uv.lock`

No local Windows execution has been performed for Project Frankenstein. Windows support must be reported from GitHub Actions or a real Windows host, with the distinction stated explicitly.

## Commands and results

### Phase 00 baseline

```bash
uv sync --locked --python 3.12.12 --extra dev --extra import-svg --extra gui-dev
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Result: `150 passed in 13.38s`.

### Phase 01 raw capture format

```bash
uv run pytest -q tests/capture/test_capture_format.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `10 passed in 0.37s`; full regression `160 passed in 12.44s`.

### Phase 02 Qt pointer capture

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/gui/test_capture_widget.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `4 passed in 0.52s`; full regression `164 passed in 12.40s`.
The automated suite used Qt mouse events and controlled pen-event translation;
no physical tablet/touch hardware was available, so hardware-specific event
delivery remains a release validation item.

### Phase 03 integrated Handwriting Studio

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/gui/test_capture_widget.py tests/gui/test_studio.py tests/gui/test_shell.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `15 passed in 3.27s`; full regression `167 passed in 12.18s`.
The integration test saves a two-stroke Ukrainian sample, leaves and returns to
the workspace, constructs a fresh Studio instance, and reopens byte-verified raw
data from the user-data directory.

### Phase 04 queues and coverage

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/capture/test_queue.py tests/gui/test_studio.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `7 passed in 1.24s`; full regression `171 passed in 13.81s`.
The five-token test uses the UI workflow, persists queue progress, reconstructs
the Studio, verifies zero missing tokens, then rejects one hash and verifies
coverage decreases without deleting the raw capture.

### Phase 05 variant management

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/capture/test_drafts.py tests/gui/test_studio.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `7 passed in 1.29s`; full regression `174 passed in 12.65s`.
The acceptance test records three geometrically different `м` samples, renders
three thumbnails, selects one preferred, reopens it, tombstones another, and
verifies that every immutable raw file still exists after Studio restart.

### Phase 06 stroke normalization and processing

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/capture/test_processing.py tests/gui/test_capture_widget.py tests/gui/test_studio.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `18 passed in 2.56s`; full regression `183 passed in 13.86s`.
Acceptance evidence covers two tolerances linked to one raw SHA-256, certified
per-stroke error limits, deterministic output, Line/Quadratic/Cubic fitting,
duplicate filtering, corner/loop/mark preservation, immutable round-trip,
tamper rejection, Raw/Processed overlay, parameter invalidation, undo, and
reopen. The resampling budget is rejected before allocating an excessive
derived point array. Persistence also rejects a derivative when its verified
raw capture/sample source is absent. No physical tablet/touch hardware was used.

The confirmed hot path was repeated point-to-polyline distance evaluation. A
profile of the strict 0.35 px fixture initially spent 7.324 s in a helper that
allocated a `Point2` for every projection. Direct scalar squared-distance
evaluation reduced the unprofiled seven-run median to `0.5574s` (individual
runs 0.5506–0.5706 s) without changing the error bound or serialized result.

### Phase 07 shared metrics and GlyphFrame normalization

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/capture/test_metrics.py tests/gui/test_studio.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `12 passed in 3.00s`; full regression `189 passed in 15.40s`.
The core acceptance test normalizes `а`, `м`, `н`, `о`, and `и` through one
shared guide profile, verifies baseline/x-height mapping and proves that the
short `о` is not independently stretched. Further checks cover manual advance,
left/right bearings, baseline offset, gu→mm preview, contiguous metric profile
revisions, analytical bound validation, source/hash verification, tamper
rejection, GUI preview, and restart recovery.

### Phase 08 manual annotation and join diagnostics

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/capture/test_annotation.py tests/gui/test_studio.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `12 passed in 3.48s`; full regression `194 passed in 13.76s`.
Evidence covers exact multistroke order, body/mark roles, deferred marks,
critical features, geometry-derived entry/exit tangents, invalid tangent/order
rejection, contiguous persisted revisions, and conversion to the existing
draft GlyphVariant format. The real join engine is exercised for an accepted
connector, an explicit forced pen lift, and a gap rejection; Studio renders the
pair and reopens the saved annotation.

### Phase 09 recorded multi-character ligatures

```bash
uv run pytest -q tests/capture/test_annotation.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `5 passed in 0.53s`; full regression `195 passed in 16.86s`.
The acceptance fixture records `ма` as one sequence, stores one manual character
boundary, requires individual `м`/`а` fallback, and builds an existing
multi-grapheme GlyphVariant. Layout of `мама` selects exactly two recorded
ligatures and carries their original stroke through two PenPlan draws; repeated
compilation is byte-model deterministic. Missing fallback is rejected.

### Phase 10 personal StylePack builder

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/capture/test_style_builder.py tests/styles/test_styles.py tests/gui/test_studio.py
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Results: `19 passed in 3.38s`; full regression `198 passed in 17.02s`.
Evidence covers an explicit local-user sample review, source-chain verification,
canonical glyph/review/provenance/license payloads, normal repository reload,
immutable revision conflict, and ambiguous composite-root rejection. The Qt
workflow records and publishes one test sample; a separate integration test
refreshes the normal style picker, retains all built-in styles, selects the
user revision for a text object, and generates through the composite backend.
The published manifest stays non-production and test-only. These tests ran on
Linux with Qt offscreen; no local Windows execution is claimed.

### Phase 11 complete synthetic Level B workflow

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q \
  tests/test_canonical_models.py tests/e2e/test_frankenstein_level_b.py
QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=1 uv run python \
  tools/generate_frankenstein_level_b.py examples/frankenstein-level-b/review-bundle --overwrite
QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=2 uv run python \
  tools/generate_frankenstein_level_b.py /tmp/cadpisun-frankenstein-reopen --overwrite
diff -qr examples/frankenstein-level-b/review-bundle \
  /tmp/cadpisun-frankenstein-reopen
```

Result: `2 passed in 2.39s`; full regression `200 passed in 16.63s`;
cross-process directory diff produced no output.
The generated bundle contains 49 files and 388 KiB. Style revision hash is
`1aada21a94f0c51632c17d03d2cd40f985a0950ddb0415c56e2bcf7fcda81301`;
desktop document ID is `desktop-d8702b16489f62c2c92f`.

Evidence covers six synthetic raw pointer captures, processed and normalized
derivatives, reviewed annotations, two `м` variants, an immutable five-key
StylePack, all four required words, 16 PenPlan draws, parsed production and
diagnostic SVG, MotionPlan, virtual G-code round trip, atomic review-bundle
hashes, project cache reopen, a fresh rebuild, and byte identity under distinct
Python hash seeds. The SVGs were also rendered locally with librsvg for visual
inspection. This is integration evidence only: no physical human input,
tablet, Windows host or plotter was used, and handwriting quality remains open.

### Phase 11 CI

[GitHub Actions run 38866286365](https://github.com/6axam/CADPisun/actions/runs/38866286365)
tested commit `c097de9c0aa2a2e8861bdcc43bc0d73ca6203edf` with Python 3.12:

- `ubuntu-latest · Python 3.12`: success; 48 seconds total job time;
- `windows-latest · Python 3.12`: success; 1 minute 11 seconds total job time.

Both jobs ran the focused Canvas, document editing, export, generation, desktop
polish, selective refresh and shell checks followed by the complete core and
integration suite. The Windows result is headless GitHub-hosted CI evidence;
it is not a claim of a manual Windows GUI or physical-input test.

### Documentation checks

`git diff --check` passed. All local Markdown links in `docs/frankenstein/` resolve. The staged-file review confirms that Phase 00 changes only documentation outside the read-only `sources/` mirror.

## Required phase evidence

Every completed phase appends:

- exact focused test command and result;
- full-suite result when the change crosses module boundaries;
- relevant performance measurement rather than an estimate;
- generated artifact hashes for end-to-end milestones;
- CI run URL and per-platform status after push.

