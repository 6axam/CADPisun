# Project Frankenstein — Level B acceptance report

Acceptance date: 2026-10-16. Code milestone: `c097de9`. The evidence in this
report establishes the software-testable Level B personal-handwriting workflow.
It does not establish Level C handwriting quality or hardware readiness.

## Implementation summary

Phases 00–11 are complete:

1. architecture and external-source audit;
2. canonical immutable `hp-capture/1.0` records;
3. Qt mouse, stylus and touch capture with duplicate-event protection;
4. an integrated Handwriting Studio workspace;
5. persistent capture queues, coverage and variant management;
6. bounded directed-stroke processing;
7. shared style metrics and GlyphFrame normalization;
8. manual join, mark and pen-lift annotation;
9. explicit recorded multi-grapheme ligatures;
10. reviewed, immutable, test-only personal StylePack publication;
11. normal A4 document generation, SVG, MotionPlan, virtual G-code and project
    reopen through the published user revision.

Phases 12–17 remain planned follow-up work: natural variation v2, GUI realism
controls, multi-page composition, safe travel optimization, virtual calibration,
and release stabilization. None is required to reproduce the accepted Level B
vertical path. OCR, ML, a hardware sender and a new glyph editor remain outside
this work.

The architecture now has an immutable source chain:

```text
raw capture -> processed strokes -> normalized GlyphFrame -> reviewed annotation
            -> immutable user StylePack -> normal document pipeline
            -> PenPlan -> SVG / MotionPlan -> virtual G-code
```

Every derivative names and verifies its source SHA-256. Editable queue and draft
metadata stay separate from raw data. Packaged and user StylePacks are exposed
through a composite read catalog, while publication remains confined to the
platform application-data directory and delegates integrity checks to the
existing `FileStyleRepository`. Explicit missing style references remain
missing rather than silently selecting another revision.

The external-source audit records the ideas studied and their pinned revisions:

- VHS (AGPL-3.0): capture queues, coverage and pointer workflow;
- Penstroke (MIT): multiple variants and bounded variation concepts;
- Google Ink Stroke Modeler (Apache-2.0): timestamped pointer-event and staged
  processing concepts;
- vpype (MIT): future pen-up routing concepts;
- Mistral SingleLine (SIL OFL-1.1): open-path and shared-metric structure.

No donor source or font asset was copied, adapted, bundled, or added as a runtime
dependency. The implementation is independent PySide6/Python code under the
project's MIT license. Exact sources, licenses and boundaries are recorded in
[`source-audit.md`](source-audit.md). Runtime dependencies remain the pinned
packages declared in [`pyproject.toml`](../../pyproject.toml): Pydantic and
regex for the core, with optional PySide6, defusedxml and svg.path features.

## Demonstration

The tracked [`examples/frankenstein-level-b/`](../../examples/frankenstein-level-b/README.md)
directory is the review entry point. It contains:

- a [Handwriting Studio screenshot](../../examples/frankenstein-level-b/handwriting-studio-synthetic.png)
  rendered from the current Qt widget with an explicitly synthetic trace;
- [six raw captures](../../examples/frankenstein-level-b/review-bundle/captures/),
  processed and normalized derivatives, and reviewed annotations for five
  Ukrainian keys, including two `м` variants;
- the published [test-only StylePack manifest](../../examples/frankenstein-level-b/review-bundle/stylepack/manifest.json)
  and its provenance, review, license and payload hashes;
- the input words `мама`, `мимо`, `мана`, and `мина` in
  [`input.txt`](../../examples/frankenstein-level-b/review-bundle/generated/input.txt);
- [production SVG](../../examples/frankenstein-level-b/review-bundle/generated/page-0001.svg),
  [diagnostic SVG](../../examples/frankenstein-level-b/review-bundle/generated/page-0001.preview.svg),
  [PenPlan](../../examples/frankenstein-level-b/review-bundle/generated/page-0001.plan.json),
  [MotionPlan](../../examples/frankenstein-level-b/review-bundle/generated/page-0001.motion.json),
  and [virtual G-code](../../examples/frankenstein-level-b/review-bundle/generated/page-0001.gcode);
- a [reopenable desktop project](../../examples/frankenstein-level-b/review-bundle/project.hplot.json)
  with its validated generation cache;
- machine-readable [acceptance results](../../examples/frankenstein-level-b/review-bundle/validation.json)
  and a [SHA-256 review manifest](../../examples/frankenstein-level-b/review-bundle/review-bundle.json).

The acceptance gate parsed both SVG files, verified 19 source graphemes and 16
PenPlan draws, round-tripped the virtual G-code, reopened the project and its
cache, then rebuilt byte-identical output through fresh repositories. Runs under
two different `PYTHONHASHSEED` values produced the same 49-file, 388 KiB bundle.
The stable StylePack revision hash is
`1aada21a94f0c51632c17d03d2cd40f985a0950ddb0415c56e2bcf7fcda81301`.

## Performance

The baseline before Frankenstein changes was 150 tests in 13.38 seconds. Phase
06 profiling identified repeated point-to-polyline distance calculations as the
processing hot path: the strict 0.35 px fixture initially spent 7.324 seconds in
a helper that allocated a `Point2` for every projection. Scalar squared-distance
evaluation reduced the seven-run median to 0.5574 seconds (0.5506–0.5706
seconds) without changing the certified error bound or serialized output.

The final local suite completed 200 tests in 16.63 seconds. Measurements used
Arch/Omarchy Linux, Python 3.12.12, uv 0.12.23, PySide6 6.12.0, the committed
lockfile and Qt's `offscreen` platform. GitHub-hosted CI completed its entire
job in 48 seconds on Ubuntu and 1 minute 11 seconds on Windows; these job times
include setup and are operational evidence rather than processing benchmarks.

No remaining Level B bottleneck was observed in the measured fixture. Larger
alphabets, long pages and high-point-count physical tablet captures still need
representative performance measurements before Level C.

## Quality

Local validation passed `200` tests. The focused deterministic Level B suite
passed `2` tests in 2.39 seconds, and regeneration under distinct process hash
seeds produced no directory difference. The full commands and phase-by-phase
results are in [`VALIDATION.md`](VALIDATION.md).

[GitHub Actions run 38866286365](https://github.com/6axam/CADPisun/actions/runs/38866286365)
is green for both `ubuntu-latest · Python 3.12` and
`windows-latest · Python 3.12` at code commit `c097de9`. The Windows result is
headless automated CI; no manual Windows GUI session is claimed.

Known limits are explicit:

- the review bundle uses synthetic pointer traces and makes no handwriting
  quality claim;
- the test StylePack covers only `а`, `м`, `и`, `н`, and `о`;
- the pack is `approved=false`, `test_only=true`, and
  `production_eligible=false`;
- no physical stylus/tablet event delivery or real plotter was tested;
- virtual G-code is only for the simulation profile;
- human capture, visual review, complete alphabet coverage and full-page
  readability remain required for Level C;
- `BLK-STYLE-001` remains open.

## Git

The work is on `codex/frankenstein-handwriting-studio`, based on `main` commit
`011ec7a`. It was pushed to `origin` and published as
[pull request #4](https://github.com/6axam/CADPisun/pull/4).

| Phase | Commit | Change |
|---|---|---|
| 00 | `7d0f875` | architecture and source audit |
| 01 | `67fa1cf` | versioned raw capture format |
| 02 | `417f362` | directed Qt pointer capture |
| 03 | `1dd1204` | integrated Studio workspace |
| 04 | `f0ca242` | queues and coverage |
| 05 | `5b0bc0c` | capture variant management |
| 06 | `b33b48c` | directed-stroke processing |
| 07 | `f08da52` | shared glyph metrics |
| 08 | `65ecc97` | joins and pen-lift annotation |
| 09 | `59e05ad` | recorded ligatures |
| 10 | `918543d` | immutable personal StylePack publication |
| 11 | `c097de9` | complete personal handwriting workflow |

## User instructions

Install and start the desktop application using [`INSTALL.md`](../../INSTALL.md),
then follow this path without editing JSON or running developer scripts:

1. Start `uv run hplot-gui` and open **Handwriting Studio**.
2. Enter a personal style name, choose the Ukrainian queue, and write each
   requested character. Use **Save & Next** and record extra variants where
   needed.
3. Reopen questionable variants, compare them, mark the preferred input and
   remove or reject poor samples from the draft.
4. For each accepted sample, choose **Process**, set the shared guides with
   **Use guides for style**, then choose **Normalize**.
5. Assign body/mark roles and join or pen-lift constraints. Use **Preview pair**
   to inspect actual join-engine decisions, then save and accept the reviewed
   annotation.
6. Enter a new semantic revision and reviewer ID, confirm that every accepted
   sample was inspected, run **Validate draft**, and choose
   **Publish immutable revision**.
7. Return to **Document**, create or select a text object, enter the test words,
   select the newly published style revision and generate the page.
8. Inspect production and diagnostic previews, then export SVG and virtual
   G-code. Save the `*.hplot.json` project, close the application and reopen it
   to confirm the same text and explicit style revision are restored.

The detailed controls, storage behavior and recovery rules are documented in
[`docs/gui-usage.md`](../gui-usage.md).
