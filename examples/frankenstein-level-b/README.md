# Project Frankenstein — Level B integration review

[`review-bundle/`](review-bundle/) is the reproducible first end-to-end
personal-style gate for CADPisun. It contains six immutable pointer captures for
five Ukrainian letters (`а, м, и, н, о`), including two `м` variants, plus every
derived and generated artifact required to audit the pipeline.

The pointer traces are deterministic **synthetic integration fixtures**. They
exercise the same repositories, validators, StylePack publisher, Document
Workspace backend, SVG writer, MotionPlan and virtual G-code round trip as user
input. They do not demonstrate human handwriting quality, tablet behavior or a
physical plotter. `BLK-STYLE-001` therefore remains open.

Regenerate the bundle from public APIs without editing JSON:

```bash
QT_QPA_PLATFORM=offscreen uv run python tools/generate_frankenstein_level_b.py \
  examples/frankenstein-level-b/review-bundle --overwrite
```

The generator builds the bundle twice through fresh repositories, saves the
desktop project with its validated cache, reopens it, builds it again, parses
both SVG exports and verifies the virtual G-code round trip. It publishes the
directory atomically only after every check succeeds. The same command under
different `PYTHONHASHSEED` values must produce byte-identical files.

Start with these files:

- [`validation.json`](review-bundle/validation.json) — explicit checks and
  limitations;
- [`review-bundle.json`](review-bundle/review-bundle.json) — SHA-256 and size
  for every payload;
- [`stylepack/manifest.json`](review-bundle/stylepack/manifest.json) — immutable
  test-only style revision;
- [`generated/page-0001.svg`](review-bundle/generated/page-0001.svg) —
  production geometry;
- [`generated/page-0001.preview.svg`](review-bundle/generated/page-0001.preview.svg)
  — travel and stroke diagnostics;
- [`generated/page-0001.gcode`](review-bundle/generated/page-0001.gcode) —
  simulation-only virtual G-code;
- [`project.hplot.json`](review-bundle/project.hplot.json) — reopenable project
  with explicit `frankenstein-synthetic@0.1.0` reference and validated cache.
