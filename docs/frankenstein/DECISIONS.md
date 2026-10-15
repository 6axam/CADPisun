# Project Frankenstein — decisions

## F-ADR-001: Preserve the existing generation core

Status: accepted, 2026-10-14.

Capture and authoring produce the existing `GlyphVariantFile` and `StyleManifest` formats. Runtime generation continues through normalization, coverage, shaping, layout, PenPlan, SVG, MotionPlan, and the virtual G-code round trip. A second font or export format would split integrity rules and project compatibility.

## F-ADR-002: Separate raw, derived, draft, and published data

Status: accepted, 2026-10-14.

Raw `hp-capture/1.0` sessions are content-addressed and immutable. Processing results reference the raw SHA-256 and record parameters. Editable draft metadata may select, reject, annotate, or supersede samples without rewriting raw coordinates. Publication copies only reviewed candidates into a new immutable StylePack revision.

## F-ADR-003: Keep Qt at the UI boundary

Status: accepted, 2026-10-14.

Capture models, validators, repositories, processing, metrics, annotation, and StylePack assembly remain Qt-free. A reusable widget translates `QMouseEvent`, `QTabletEvent`, and supported touch events into those models. This preserves CLI imports without the GUI extra and makes geometry tests deterministic.

## F-ADR-004: Use scene millimetres only for document layout

Status: accepted, 2026-10-14.

The Document Workspace keeps its current QGraphicsScene millimetre coordinate system. Raw capture uses an explicit top-left canvas coordinate frame with logical pixels and records canvas dimensions and device-pixel ratio. Phase 07 performs the explicit transform into `GlyphFrame` glyph units. Resizing never retroactively changes raw coordinates.

## F-ADR-005: Discover built-in and user StylePacks as separate roots

Status: accepted, 2026-10-14.

Packaged assets stay under the installed package/source checkout and remain read-only. The GUI obtains a platform application-data location and supplies a writable `styles/` root. A composite catalog resolves explicit `(style_id, revision)` references, rejects ambiguous duplicates, and delegates every load to `FileStyleRepository`, preserving file-hash, license, schema, coverage, and geometry validation. Publication is permitted only in the user root.

## F-ADR-006: Independently implement donor mechanisms

Status: accepted, 2026-10-14.

VHS is AGPL-3.0, so only its observable workflow and concepts inform this implementation. Penstroke, ink-stroke-modeler, and vpype were inspected for mechanisms but are not copied or added as dependencies. Mistral SingleLine is a font asset under OFL-1.1 and is not imported. This keeps CADPisun's implementation and dependency surface controlled while retaining exact research provenance.

## F-ADR-007: Level B publications remain test-only

Status: accepted, 2026-10-14.

A user may explicitly review a limited personal draft and publish it for technical use, but the generated manifest remains `test_only=true` and `production_eligible=false`. Synthetic fixtures never claim human authorship or independent approval. Product release gates in the existing architecture remain unchanged.

## F-ADR-008: Certify capture processing before persistence

Status: accepted, 2026-10-15.

Processing remains an independently testable Python module and uses the existing
Line, Quadratic, Cubic, and Stroke IR without adding Ink Stroke Modeler's native
runtime. Corner-aware resampling and Douglas–Peucker simplification may propose
geometry, but a symmetric deviation check with an explicit sampling and
flattening margin decides whether it is accepted. The pipeline falls back to
less simplified geometry instead of increasing the requested tolerance. Raw
logical pixels remain their own frame until Phase 07; no false `gu` unit is
assigned to a processed derivative.

## F-ADR-009: Normalize a style from shared guides, never glyph bounds

Status: accepted, 2026-10-15.

The first explicit or captured style metric profile fixes one logical-pixel
frame and shared ascender, x-height, baseline, and descender guides. Every glyph
uses the same uniform `1000 gu / source x-height` scale. Individual analytical
bounds determine only horizontal placement and bearing checks. Manual overrides
may change advance, bearings, or an explicit baseline offset; they never stretch
a glyph to fill its own vertical box. Physical preview uses the architecture's
nominal gu-to-mm conversion and is labeled in millimetres rather than pretending
to be monitor-calibrated 1:1 output.

