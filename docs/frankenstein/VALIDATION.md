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

### Documentation checks

`git diff --check` passed. All local Markdown links in `docs/frankenstein/` resolve. The staged-file review confirms that Phase 00 changes only documentation outside the read-only `sources/` mirror.

## Required phase evidence

Every completed phase appends:

- exact focused test command and result;
- full-suite result when the change crosses module boundaries;
- relevant performance measurement rather than an estimate;
- generated artifact hashes for end-to-end milestones;
- CI run URL and per-platform status after push.

