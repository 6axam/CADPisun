# Project Frankenstein — integration architecture audit

## Existing path from document to artifacts

`MainWindow` owns a `DocumentController`. `gui.backend.composition_request()` converts the immutable `ProjectSnapshot` into a `CompositionRequest`; `GenerationWorker` runs `GuiBackend.build()` off the UI thread. `DesktopApplicationAdapter` normalizes text, loads and verifies an immutable StylePack, checks coverage, shapes and lays out each visible block, compiles one authoritative PenPlan, and derives production SVG, diagnostic SVG, MotionPlan, virtual G-code, and reports. `MainWindow` accepts a worker result only for the current project revision/source hash, displays it, and enables export. Project persistence optionally embeds the complete generated cache with per-artifact SHA-256 validation.

The CLI follows the parallel `HandwritingPlotterService` path and publishes a complete bundle atomically through `storage.files.publish_bundle()`. Capture work must converge on the existing StylePack boundary so both paths remain compatible.

## Style discovery and publication

The current GUI catalog scans only `application.resources.style_root()`, which resolves packaged/source-tree assets. Each manifest is loaded through `FileStyleRepository`, which enforces safe paths, strict JSON/Pydantic schemas, license presence, all declared SHA-256 hashes, resource budgets, approved glyph records, glyph-envelope bounds, and full style validation. `publish()` already stages, validates, and atomically installs an immutable revision.

The missing extension is location-aware cataloging. Phase 10 will introduce:

1. a Qt-free `StyleLocation`/catalog abstraction with separate built-in and user roots;
2. a GUI application-data resolver, using `QStandardPaths.AppDataLocation`, that passes explicit paths into the core;
3. a writable user layout containing `captures/`, `drafts/`, `processed/`, and `styles/`;
4. deterministic duplicate handling for `(style_id, revision)` and clear missing-style diagnostics;
5. publication restricted to the user `styles/` repository while all reads still pass through `FileStyleRepository`.

No user data is written into `application.resources.style_root()` or an installed wheel.

## Glyph resolution and joins

Text normalization and coverage preserve Unicode graphemes. Shaping resolves the longest eligible key from `StyleSnapshot.variants_by_key`, filters contextual variants, and selects deterministically. Join specifications point to real directed body-stroke endpoints and unit tangents. Join validation checks class compatibility, gap, vertical delta, angle, and no-join flags; scheduling preserves body and deferred-mark order. Recorded ligatures therefore become ordinary multi-grapheme StylePack keys and use existing longest-match resolution rather than a replacement engine.

## Coordinate systems

`PageCanvas` uses QGraphicsScene coordinates directly as physical millimetres on a 210 × 297 A4 page. View transforms provide zoom/pan; pointer positions are converted with `mapToScene()`. Style geometry uses explicit `GlyphFrame` glyph units and is transformed during shaping/layout. Machine coordinates arise only after registration.

Handwriting capture needs a separate fixed capture frame. Raw points will store top-left logical canvas coordinates plus width, height, coordinate-unit name, and device-pixel ratio. Phase 07 applies an explicit saved transform from that frame and the shared writing guides into `GlyphFrame`; document-scene and machine units never leak into raw capture.

## Worker and persistence lifecycle

`GenerationWorker` owns an immutable snapshot and revision. Signals return success or structured failure to the main thread; `MainWindow` rejects stale results and single-flights regeneration. Studio processing that can exceed a frame budget will use the same immutable-input/worker-result pattern, with a separate task type and stale-result key. Pointer ingestion and drawing remain synchronous and cheap.

Project saves use atomic replacement and can retain verified generated artifacts. Frankenstein data will use a dedicated repository: immutable raw capture files are atomically created under content-addressed names; draft metadata is atomically replaced; derived files include their raw source hash; published StylePacks use the existing repository transaction.

## Reusable geometry

- `geometry.curves`: finite `Point2`, Line/Quadratic/Cubic, directed `Stroke`, evaluation, split, tangent.
- `geometry.flatten`: bounded De Casteljau flattening and approximation reports.
- `geometry.transforms`: named-frame affine transforms and stroke conversion.
- `geometry.bounds` and `collision`: exact/conservative bounds and geometry checks.
- `styles.models`: strict serialized curve, join, provenance, glyph, and manifest models.
- `shaping.resolve`, `joins`, and `schedule`: longest-key resolution and geometry-aware connected writing.

Phase 06 adds point-specific duplicate filtering, resampling, smoothing, simplification, fitting, and source-to-result deviation measurement. It will reuse the curve IR rather than create another path model.

## New component boundaries

```text
gui/studio/* event adapters and widgets
        ↓
capture/models.py + capture/repository.py        immutable hp-capture/1.0
        ↓
capture/processing.py                            reversible derivatives
        ↓
authoring/drafts.py + metrics.py + annotations.py editable metadata
        ↓
authoring/style_builder.py                       existing hp-glyph/hp-style
        ↓
styles/catalog.py + FileStyleRepository          built-in + user roots
        ↓
existing shaping → layout → PenPlan → SVG/G-code
```

The first implementation step is the Qt-free capture boundary. UI work starts only after its round-trip and rejection behavior are proven.

