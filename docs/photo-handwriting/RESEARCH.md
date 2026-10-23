# Photo-to-Handwriting research audit

Audit date: 2026-10-23. Links and revisions below are pinned research evidence,
not dependencies selected for installation. Published quality numbers are
self-reported by their authors unless CADPisun later measures them in
`BENCHMARKS.md`.

## Existing CADPisun architecture

The repository already has the correct downstream shape:

- `capture/models.py` defines immutable online pointer samples with explicit
  coordinate frame, timing and pressure semantics.
- `capture/repository.py` stores canonical content-addressed records.
- `capture/processing.py` and `capture/metrics.py` produce bounded processed and
  normalized geometry without Qt.
- `capture/annotation.py` separates stroke roles, authored order, entry/exit
  anchors, ligature boundaries, and review state.
- `capture/style_builder.py` validates reviewed candidates and publishes an
  immutable test-only StylePack with hashes, provenance, review, and license.
- `gui/studio.py` is a large integrated workspace for capture and review. Photo
  import should be a dedicated page/workspace within Handwriting Studio and
  should call Qt-free services.

The missing seam is before normalized glyph review. A photo-derived candidate
needs an adapter that produces the same normalized/annotation inputs while
preserving raster provenance and `offline_inferred` direction semantics.

## Source and license ledger

| Source | Audited revision | Declared license | Size / relevant artifact | Decision |
|---|---|---|---|---|
| [HandwritingDatasetGen](https://github.com/Carson-Stark/HandwritingDatasetGen) | `d8bdbe4c528cdc5ceda1825c7fcadca0035c9792` | None detected; no `LICENSE` file | Repository API reports about 4.4 MB, including a sample scan | Algorithm/workflow reference only; copy no code or sample data |
| [Kraken](https://github.com/mittagessen/kraken) | release 7.1.1 source `a314f84f42da49a34079a4166305a7f378bb9c71`; main observed at `bb487219e7d8289274443d1ad0989efb4924dc2a` | Apache-2.0 | 7.1.1 wheel 5.1 MB; transitive torch/scientific stack is much larger | Candidate line/region segmentation and HTR provider in an isolated environment |
| [Hukyl/trocr-large-uk-handwritten-real](https://huggingface.co/Hukyl/trocr-large-uk-handwritten-real) | `7ae1697fdbce210f8c6ba313d746279357b9f56b` | Apache-2.0 model card; training-data obligations remain separate | 558,299,136 params; `model.safetensors` 2,233,276,152 bytes | Benchmark candidate; line-level only; no automatic download |
| [Hukyl/trocr-large-uk-handwritten](https://huggingface.co/Hukyl/trocr-large-uk-handwritten) | `3ea3af0c3a2bd68c927577f40c997b5b24098c04` | Apache-2.0 model card; mixed training data includes CC BY-SA attribution | 558,299,136 params; weights 2,233,276,152 bytes | Benchmark candidate only after rights/attribution review |
| [cyrillic-trocr/trocr-ukrainian-handwritten](https://huggingface.co/cyrillic-trocr/trocr-ukrainian-handwritten) | `2f717bb4e44af7e5cabf553df2a9aae06322255e` | MIT model card | 333,921,792 params; weights 1,335,747,032 bytes | Smaller TrOCR benchmark candidate; historical-domain caveat |
| [achimrabus/crnn-ctc-ukrainian](https://huggingface.co/achimrabus/crnn-ctc-ukrainian) | `f889a20feee96e6b85e807e70e8a9a0b8d3d8b42` | Apache-2.0 model card | `best_model.pt` 43,123,569 bytes | Primary lightweight CPU candidate for TASK 09, subject to identical-crop benchmark |
| [Polyscriptor](https://github.com/achimrabus/polyscriptor) | `7994ccadc537c59b0b90eb25b66dfa5d54976d6d` | README says MIT; GitHub API found no license file at this revision | Multi-engine reference; broad dependency set | Study interfaces/preprocessing; do not vendor code until license file/terms are resolved |
| [doc-scan](https://github.com/AVI20953/doc-scan) | `41e2fce8d0d12e36f73fed4cf9db9ea94259888d` | None detected; no `LICENSE` file | Small OpenCV example | Algorithm reference only; use OpenCV APIs and independent implementation |
| [VHS](https://github.com/utrost/VHS) | `1dabbad575b08e9e6417ef34dcd731f7c2a6cd29` | AGPL-3.0 | Workflow/UI reference | No code incorporation into the MIT project |

Model licenses do not automatically license every training image or permit
redistribution of user notebooks. Every selected weight and dataset snapshot
must keep its own rights record, source revision, checksum, and attribution.

## Offline-to-online reconstruction

HandwritingDatasetGen describes this useful sequence:

1. Segment pages into lines and words using vertical strips, row-density
   painting, dilation, background thinning, separator linking, and overlap
   correction.
2. Thin ink to a one-pixel skeleton and repair connectivity.
3. Build a graph of endpoints, junctions, edges, and loops.
4. Pair odd-degree nodes and choose paths with local curvature/smoothness
   heuristics, introducing pen-up bridges where needed.
5. Traverse components, handle loops/backtracking, then resample `(x, y,
   pen-state)` points.

The repository implementation is a single large exploratory script with
heuristics and no explicit license. CADPisun will independently implement small,
typed steps from documented graph principles, with synthetic fixtures for every
topology. The raw graph is retained before route selection. Additional traversals
must not be invented simply to force an Euler path because that changes ink
density and plotter behavior.

Photo evidence does not identify start point, direction, retracing, or true pen
lifts. A simple open chain already has two valid directions; crossings and loops
have more. The data model therefore needs bounded alternative hypotheses,
unresolved junctions, separate geometry/order confidence, and human review.

## Kraken and page geometry

Kraken 7.1.1 is the stable target to reproduce in a separate Python 3.12
environment. Its published features cover baseline/region segmentation, reading
order, line recognition, character cuts, ALTO/PageXML, batching, and task model
APIs. The 7.x API changed materially, so the adapter must target the tagged
release rather than current `main` examples.

Kraken's output is a proposal, not CADPisun ground truth. We retain polygons,
baselines, reading order, model revision, codec, scores, and the complete
source-to-line transform. Manual polygons must remain available when no suitable
model exists. Character cuts can help alignment but do not prove cursive glyph
boundaries.

The package itself is small, but its torch, torchvision, Lightning, scikit-image,
SciPy, Core ML, and Arrow dependencies would make the normal GUI environment
large and fragile. `TECH_STACK.md` already records an incompatible scikit-image
pin with CADPisun's provisional vision environment. Use a subprocess protocol
and an isolated lock rather than adding Kraken to `pyproject.toml` base extras.

## Ukrainian HTR candidates

All inspected models accept one cropped line, not an arbitrary notebook page.
Page rectification and line segmentation remain mandatory.

| Candidate | Published validation | Input sensitivity | CADPisun consequence |
|---|---|---|---|
| Hukyl TrOCR Large real-only | CER 0.0249, WER 0.0931 on its in-domain held-out set | RGB line at 384 px encoder input; extended Cyrillic tokenizer | Large CPU/RAM and latency risk; compare only after lightweight baseline |
| Hukyl TrOCR Large mixed | CER 0.0173, WER 0.0768 on a split matching a roughly 3:1 synthetic/real training mix; card reports much worse zero-shot document transfer | Same 558M architecture | Published number is not evidence for modern student notebooks |
| Cyrillic TrOCR Ukrainian v2 | CER 4.99% on 970 held-out historical-document lines, beam 4 | Corrected EXIF; aspect-preserving line resize; historical 19th–20th century domain | Useful medium-size comparison, still far larger than CRNN |
| CRNN-CTC Ukrainian | CER 4.76% reported; separate experiment reports 5.10% polygon-masked vs 10.29% bounding-box crops | Grayscale, 128 px height, aspect preserved, polygon-masked background | Strong lightweight candidate; line polygon fidelity is part of the benchmark |

These numbers are not directly comparable: datasets, splits, Unicode
normalization, decoding, crop masks, and domains differ. TASK 09 must evaluate
the exact same checksummed crops and transcriptions, including `ґ є і ї й ь ю я`,
digits, punctuation, formulas/abbreviations where present, and both corrected and
uncorrected photographs.

## Document correction and ruling

OpenCV supplies the required deterministic primitives: EXIF-aware decode at the
adapter boundary, grayscale/color-space transforms, blur, Canny/contours,
polygon approximation, homography, `warpPerspective`, adaptive thresholding,
morphology, Hough/projection analysis, and connected components.

`doc-scan` demonstrates the familiar boundary proposal sequence
blur → Canny → morphology → contour/quad filtering → homography → adaptive
thresholding. Because its pinned repository has no declared license, CADPisun
will independently implement and test this pipeline. Automatic corners are only
a proposal; manual four-corner input is the reliable fallback. A planar
homography cannot honestly correct a curved notebook page.

Ruling detection should use periodic evidence across many rows/columns rather
than treating every long stroke as paper ruling. Robust median/RANSAC-like
statistics, color evidence, frequency/autocorrelation, and phase estimation are
candidates. Handwriting masks and table borders are adversarial cases. Physical
pitch remains unknown until entered, measured from page dimensions, or derived
from a verified reference; 5 mm is only a preset.

## Initial test dataset design

No personal photographs are committed by TASK 00. The planned corpus has four
explicit tiers:

1. **Generated security fixtures**: valid PNG/JPEG/WebP, malformed headers,
   truncation, unsupported data, oversized compressed bytes, excessive declared
   dimensions, decompression-bomb behavior, hash mismatch, duplicate imports,
   Unicode filenames, and path traversal attempts.
2. **Generated geometry fixtures**: blank, 5 mm-equivalent square, and ruled
   pages with known dimensions, pitch, phase, color, homography, rotation,
   shadows, JPEG artifacts, table borders, and occluding synthetic ink. Exact
   source transforms and masks are generated from parameters.
3. **Generated topology fixtures**: line, arc, T/X junctions, loop, dotted form,
   two components, touching glyph group, spur noise, and ambiguous traversal.
   These test software behavior only, not handwriting authenticity.
4. **Private real corpus**: user-authorized squared and ruled notebook photos,
   stored outside Git by default with a checksummed manifest, consent/rights
   record, verified line transcripts, page/session splits, selected ink masks,
   and paired online recordings where stroke-order measurement is required.

The first vertical slice may use real or synthetic samples for `а м и н о` and
`мама`, `мимо`, `мана`, `мина`, but all schemas and algorithms remain arbitrary
Unicode. Synthetic data can prove serialization and integration only.

## Audit conclusions

- The architecture does not need a second application or rendering engine.
- TASK 01 should introduce only canonical photo/import records, a decoder port,
  safe content-addressed persistence, and tests. It should not implement CV.
- OpenCV is the preferred classical-CV base for later tasks after an optional
  dependency/lock is pinned. Kraken and recognizers remain separate providers.
- The first meaningful quality blocker is genuine, consented user material and
  human review. Software work can progress with synthetic fixtures without
  claiming authentic handwriting quality.
