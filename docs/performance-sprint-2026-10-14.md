# GUI reliability sprint: performance measurements

Measurements were taken on Linux 7.2.5 (x86-64), Python 3.12.12 and
PySide6 6.12.0 with `QT_QPA_PLATFORM=offscreen`. They are local diagnostic
measurements, not cross-platform benchmarks.

## StylePack loading

The baseline generated six text blocks that all referenced
`test-technical-v1@1.0.0`. It called `FileStyleRepository.load` six times and
took 499.601 ms. Twenty direct verified loads took 1530.467 ms. This confirmed
that repeated manifest parsing, file reads and SHA-256 verification were a
material cost.

The optimized build loads each `(style_id, revision)` once and reuses the
immutable `StyleSnapshot` for the rest of that build. The same six-block run
called `load` once and took 127.079 ms. The cache is deliberately scoped to one
build, so a later build reads and verifies the StylePack again. The regression
test checks both properties.

## Project Explorer and Canvas refresh

The baseline used a synthetic project with 150 text objects. Twenty direct
refreshes averaged 2.133 ms for Project Explorer and 2.459 ms for Canvas object
overlays. Twenty text edits averaged 7.434 ms end to end because every edit
rebuilt both structures even though text content changes neither structure.

The optimized path compares small structural signatures. It rebuilds Project
Explorer only when displayed names, visibility or object membership changes,
and rebuilds Canvas overlays only when visible frame or grid geometry changes.
Twenty text edits in the same project averaged 3.068 ms end to end, a 58.7%
reduction in this local run. Regression tests also verify that renaming refreshes
only the tree and changing a text frame refreshes only Canvas overlays.
