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

### Documentation checks

`git diff --check` passed. All local Markdown links in `docs/frankenstein/` resolve. The staged-file review confirms that Phase 00 changes only documentation outside the read-only `sources/` mirror.

## Required phase evidence

Every completed phase appends:

- exact focused test command and result;
- full-suite result when the change crosses module boundaries;
- relevant performance measurement rather than an estimate;
- generated artifact hashes for end-to-end milestones;
- CI run URL and per-platform status after push.

