# Photo-to-Handwriting master plan

Status: active · Created: 2026-10-23 · Roadmap: TASK 00–24

This plan adds photographed-handwriting learning to CADPisun without replacing
the existing capture, StylePack, shaping, layout, PenPlan, SVG, or virtual
G-code pipeline. Work proceeds one independently verifiable task at a time.

Status values are `[ ]` TODO, `[>]` IN_PROGRESS, `[x]` DONE, and `[!]` BLOCKED.
Completion means that the acceptance criteria and named tests passed; creating a
file alone does not complete a task.

## Fixed boundaries

- Original images and every derived raster/vector artifact are immutable and
  content-addressed. Corrections are versioned metadata and append-only events.
- The semantic stream (transcription and grapheme hypotheses) and geometric
  stream (regions, masks, skeletons, paths) remain separate until an explicit,
  uncertainty-preserving alignment step.
- Photograph-derived stroke order uses provenance `offline_inferred`. It never
  claims to be an `online_capture`.
- Only reviewed candidates may enter a test-only StylePack through the existing
  StylePack builder and integrity checks.
- Core generation remains usable without CV/ML packages. Heavy recognizers run
  through optional adapters in isolated environments and load lazily.
- User handwriting stays local unless a future explicit user action enables a
  remote provider. Large datasets or weights are never downloaded implicitly.
- No task may weaken Unicode fidelity, immutable StylePack revisions, PenPlan
  validation, page bounds, or the simulation-only hardware boundary.

## Additive architecture

```text
photo bytes -> source asset -> rectification -> ruling estimate -> ink masks
            -> regions/lines -> HTR prediction -> corrected transcription
            -> alignment hypotheses -> skeleton graph -> trajectory hypotheses
            -> human review -> existing normalization/annotation/StylePack builder
            -> existing document layout -> PenPlan -> SVG / virtual G-code
```

Planned ownership:

| Area | Responsibility |
|---|---|
| `handwriting_plotter.learning` | Qt-free versioned models, orchestration, transforms, masks, regions, alignment, reconstruction, review requests |
| `handwriting_plotter.adapters.images` | Image probing/decoding and OpenCV-backed preprocessing behind explicit ports |
| `handwriting_plotter.adapters.htr` | Subprocess/provider contracts for Kraken, TrOCR, and CRNN-CTC candidates |
| `handwriting_plotter.capture` | Existing normalization, annotation, draft review, and StylePack publication, extended only through typed adapters |
| `handwriting_plotter.gui` | Photo workspace, overlays, comparisons, progress, cancellation, and review UI |
| user data root | Content-addressed originals/derivatives, canonical manifests, review state, later SQLite metadata where ADR-13 requires it |

## Task ledger

Each row is a complete task record. Complexity uses the 0–12 rubric from the
feature brief. Token bands are planning estimates, not billing or quota claims.

| Task | Description | Dependencies | Acceptance criteria | Expected tests | Status | Tier | Complexity / estimated cost | Completion commit SHA |
|---|---|---|---|---|---|---|---|---|
| TASK 00 | Repository and research audit | Current `main` | Existing architecture and Handwriting Studio verified; adapter locations, licenses, model sizes, test corpus, implementation order, and five control documents recorded | Markdown/link/schema consistency; current full suite | [x] DONE | HIGH | 9/12; 8k–16k tokens; medium quota pressure | `1363b001591910981a89ca4762876584c71a492b` |
| TASK 01 | Canonical photo import model | TASK 00 | PNG/JPEG/WebP import stores immutable original bytes, checksum, metadata, dimensions, transforms, regions, ruling/confidence placeholders; save/reopen is lossless; byte/pixel/decompression and safe-path limits enforced | Model validation, canonical round trip, hash mismatch, corrupt/oversized image, path traversal, atomic persistence | [x] DONE | MEDIUM | 6/12; 6k–12k tokens; medium; about 5–8 files | `1a271b0db6bd69f5173b9439d41d0662cbdae96b` |
| TASK 02 | Photo import UI | TASK 01 | Handwriting Studio can select, preview, zoom, rotate, reset, diagnose, and compare original/corrected images without cluttering the document canvas | Headless Qt workflow, invalid input, state restore, zoom/rotation | [x] DONE | MEDIUM | 6/12; 7k–14k tokens; medium | `1ad775128f822a80623c781fe9159657c12d57df` |
| TASK 03 | Perspective and page correction | TASK 01–02 | Automatic page proposal plus manual four-corner fallback preserves forward/inverse transforms, aspect ratio, crop, orientation, and optional deskew | Synthetic homographies, inverse-map error, manual corners, no-page and curved-page diagnostics | [x] DONE | MEDIUM | 7/12; 8k–16k tokens; medium | `332b1d75f291858d231ddd654f1296d8733d9173` |
| TASK 04 | Notebook paper classification | TASK 03 | Squared, ruled, blank, and unknown/mixed classification with confidence and manual override | Synthetic paper classes, handwriting/table interference, persistence of override | [x] DONE | MEDIUM | 6/12; 6k–12k tokens; medium | `fd22492b33d826558254accfd861d4813b3abed1` |
| TASK 05 | Grid and ruled-line detection | TASK 03–04 | Robust pitch, phase, origins, directions/intersections, local distortion, confidence, overlay, and manual correction are available for squared and ruled paper | Known-pitch/phase fixtures, occlusion, skew, crossing ink, table-border negatives, overlay alignment | [x] DONE | HIGH | 11/12; 15k–30k tokens; high; split algorithm/UI if needed | `6b660c4c4a607be2f2cf0ecd208dafe7f2a56777` |
| TASK 06 | Physical-scale calibration | TASK 05 | Pixel geometry maps to cell/ruling-relative coordinates and optional millimetres; unknown physical pitch remains unknown; 5 mm is an explicit preset | Pixel-to-relative/mm conversions, uncertainty, saved calibration, no silent 5 mm assumption | [x] DONE | MEDIUM | 6/12; 6k–12k tokens; medium | `0347fe7d52e9645b0671d6b29865eb692e5cf11b` |
| TASK 07 | Paper/ink separation | TASK 05–06 | Raw and cleaned masks preserve handwriting across rules while suppressing ruling, texture, shadows, compression, and common blue/black/purple ink backgrounds; manual override exists | Representative synthetic/approved fixtures, overlap preservation, critical dot retention, mask round trip | [x] DONE | HIGH | 11/12; 15k–30k tokens; high; split by color/ruling modes | `cc4585919de5b6983b90509f64d2cc2068571ecc` |
| TASK 08 | Regions and handwriting lines | TASK 03, TASK 07 | Regions, baselines, line polygons/crops, reading order, headers/marginalia, and source transforms persist and display correctly | Provider contract, manual fallback, polygon/source mapping, reading order, cancellation | [x] DONE | HIGH | 10/12; 12k–24k tokens; high | `0cc138194859062bd330b87e2caab50b0d3d8003` |
| TASK 09 | HTR model benchmark | TASK 08 plus verified samples | At least one Ukrainian TrOCR and one lighter CPU candidate are compared on identical corrected/uncorrected line crops for CER, WER, protected letters, latency, RAM, and failures; primary/fallback recommendation is evidence-based | Reproducible benchmark harness, metric unit tests, fixed manifests, model checksum validation | [ ] TODO | HIGH | 10/12; 12k–25k tokens plus downloads/runtime; very high uncertainty | — |
| TASK 10 | HTR integration | TASK 09 | Optional lazy provider processes line batches on CPU with progress, cancellation, limits, explicit unknowns, offline reuse, and editable predictions without breaking default install | Provider/subprocess contract, missing/corrupt model, cancellation, batching, Unicode, default-install isolation | [ ] TODO | MEDIUM/HIGH | 8/12; 10k–20k tokens; high | — |
| TASK 11 | Transcription review UI | TASK 08, TASK 10 | Original prediction and corrected Ukrainian text, confidence, discrepancies, symbols, reading order, save/reopen are available; unknowns are never invented | Headless Qt edit/reopen, NFC, unknown token, reading-order edits, stale revision | [ ] TODO | MEDIUM | 7/12; 8k–16k tokens; medium | — |
| TASK 12 | Grapheme and word alignment | TASK 08, TASK 11 | Corrected spans align to word/grapheme/ligature geometry with alternatives and uncertainty; inseparable cursive clusters remain grouped | Constrained alignment, ligature/diacritic ambiguity, alternative retention, mismatch handling | [ ] TODO | HIGH | 12/12; 18k–35k tokens; very high; split word then grapheme alignment | — |
| TASK 13 | Stroke skeleton extraction | TASK 07, TASK 12 optional | Masks produce reproducible centerline graphs with endpoints, collapsed junction regions, edges, cycles, components, and bounded spur filtering while preserving marks | Lines, T/X crossings, loops, diagonals, dots, connected groups, raster overlay | [ ] TODO | HIGH | 12/12; 18k–35k tokens; very high; split graph extraction/cleanup | — |
| TASK 14 | Stroke direction and pen lifts | TASK 13 | Bounded plausible directed hypotheses use continuity/curvature/constraints, expose ambiguity and manual confirmation, and store `offline_inferred` provenance | Simple known paths, ambiguous crossings/loops, pen lifts, alternative cap, no false ground truth | [ ] TODO | HIGH | 12/12; 18k–40k tokens; very high | — |
| TASK 15 | Letter and ligature sample bank | TASK 12–14 | Candidates group by label/context/shape/scale/source/confidence; deduplication preserves authentic variants; repeated `а м н о` are browsable | Grouping, stable clustering, dedupe, source traceability, Ukrainian contexts | [ ] TODO | HIGH | 9/12; 12k–24k tokens; high | — |
| TASK 16 | Manual correction and active review | TASK 15 | Accept/reject/relabel/split/merge/reverse inferred paths/anchors/lifts/alternatives persist; priority queue surfaces useful uncertain work | Append-only corrections, restart persistence, stale edits, online-path reversal prohibition, GUI tests | [ ] TODO | MEDIUM/HIGH | 8/12; 10k–20k tokens; high | — |
| TASK 17 | Offline handwriting to StylePack | TASK 16 | Reviewed offline samples pass existing normalization, integrity, provenance, review, and immutable publication checks as test-only revisions usable by Document Workspace | Publication round trip, tamper checks, provenance, coverage, existing StylePack regressions | [ ] TODO | HIGH | 9/12; 10k–20k tokens; high | — |
| TASK 18 | Notebook page templates | TASK 00 | Blank/squared/ruled A4 and custom profiles use mm geometry, margins, pitch/offset/color/thickness/orientation/major divisions; backgrounds remain separate from pen-only export | 5 mm A4 geometry, profile round trip, canvas/SVG background, pen-only exclusion | [ ] TODO | MEDIUM | 6/12; 7k–14k tokens; medium | — |
| TASK 19 | Handwriting size adaptation | TASK 06, TASK 17–18 | Learned x-height/ascenders/descenders/baseline/advance/spacing map to squared and ruled pages in preserve/fit-height/manual modes without per-glyph distortion; overflow is explicit | Metric mapping, join continuity, physical dimensions, both ruling modes, overflow | [ ] TODO | HIGH | 10/12; 12k–25k tokens; high | — |
| TASK 20 | Note composition assistant | TASK 17–19 | A focused workflow accepts text/style/template/margins/size/spacing/naturalness/output, previews warnings, and routes missing glyphs to capture/review | Headless Qt workflow, missing coverage, stale preview, valid exports | [ ] TODO | MEDIUM/HIGH | 8/12; 10k–20k tokens; high | — |
| TASK 21 | Multi-page notebook generation | TASK 18–20 | Long notes wrap and paginate with stable ruled baselines, paragraph spacing, navigation, per-page SVG and virtual G-code, and no lost words | Multi-page coverage, page breaks, baseline phase, export manifest, reopen | [ ] TODO | HIGH | 9/12; 10k–22k tokens; high | — |
| TASK 22 | Full practical benchmark | TASK 03–21 | Genuine user samples are tested end-to-end when available; otherwise synthetic results and unverified gates are clearly separated; all named quality/resource metrics are measured | Frozen benchmark command, reproducibility, reopen, export, metric report | [ ] TODO | MEDIUM/HIGH | 8/12; 8k–18k tokens plus human review; high | — |
| TASK 23 | Performance and usability | TASK 22 | Profiled bottlenecks alone receive caching/workers/cancellation/downsampling/lazy loading/batching; before/after CPU/RAM/timing evidence exists on Linux and Windows where CI supports it | Performance budgets, cancellation, cache provenance, large project save, UI responsiveness | [ ] TODO | MEDIUM/HIGH | 8/12; 10k–24k tokens; high | — |
| TASK 24 | Final stabilization | TASK 01–23 | Existing capture and generation plus photo workflow pass unit/integration/GUI/security/reproducibility/Linux/Windows CI; install/model sizes/tutorial are documented | Full matrix, corrupt/massive image, Unicode, missing model, StylePack integrity, save/reopen | [ ] TODO | MEDIUM/HIGH | 8/12; 10k–24k tokens; high | — |

## First usable milestone

The first vertical slice is photo import, manual/automatic rectification, ruling
overlay, line HTR with editable transcription, a centerline graph, human review,
a test-only StylePack, and normal text generation. A five-letter dataset using
`а м и н о` and the words `мама`, `мимо`, `мана`, and `мина` may prove the
integration. The implementation must remain Unicode-generic and must not embed
these labels as special cases.

## Continuation protocol

At the start of every session:

1. Read `PROGRESS.md`, inspect HEAD and the working tree, and reconcile tests.
2. Select the first TODO task whose dependencies are DONE and which is not blocked.
3. Score complexity, state a suitable model tier, and perform only that task.
4. Run the task tests plus justified regressions, make one meaningful task commit,
   record its SHA, push without force, and stop at a clean checkpoint.

TASK 09 is the next permitted task. It is not started by TASK 08.
