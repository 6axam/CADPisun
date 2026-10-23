# Photo-to-Handwriting benchmark protocol

Created: 2026-10-23. This file defines measurements before implementation so
later results cannot be selected after seeing outcomes. No photo/HTR/reconstruction
benchmark has run yet.

## Result state

| Benchmark | State | Measured result |
|---|---|---|
| Photo import throughput and memory | DEFERRED — TASK 23; TASK 01 covers correctness/resource rejection | — |
| Rectification accuracy | NOT RUN — TASK 03 | — |
| Paper classification | NOT RUN — TASK 04 | — |
| Grid/ruling geometry | NOT RUN — TASK 05 | — |
| Ink separation | NOT RUN — TASK 07 | — |
| Line segmentation | NOT RUN — TASK 08 | — |
| Ukrainian HTR comparison | NOT RUN — TASK 09 | — |
| Skeleton geometry | NOT RUN — TASK 13 | — |
| Direction/order inference | NOT RUN — TASK 14 | — |
| End-to-end personal StylePack | NOT RUN — TASK 22 | — |

## Reproducibility record

Every executed benchmark report must include:

- UTC timestamp, Git commit, dirty state, operating system, CPU, RAM, Python,
  dependency lock hash, provider environment hash, thread counts, and seed;
- input manifest hash, per-file source hash, rights class, synthetic/real flag,
  train/validation/test membership, preprocessing revision, and model hash;
- warm-up count, measured repetitions, wall-clock method, peak RSS method,
  cancellation/timeout policy, output artifact hashes, and failures;
- raw per-sample rows plus summary statistics. Averages without raw samples are
  insufficient for model selection.

The provisional resource target is a CPU-only laptop with about 16 GB RAM.
Meeting it must be measured; it is not a claim about current providers.

## Dataset partitions

Generated fixtures are deterministic from committed parameters and may be in
Git. Real handwriting remains private by default. Repeated crops from one source
page or session may not cross train/validation/test boundaries.

| Set | Purpose | Leakage rule |
|---|---|---|
| `synthetic-security-v1` | Decoder/storage rejection and limits | Generated cases are never used as HTR quality evidence |
| `synthetic-geometry-v1` | Known corners, transforms, pitch, phase, masks | Exact generator parameters are ground truth |
| `synthetic-topology-v1` | Skeleton graph and ambiguity | Does not validate natural writing order |
| `photo-pilot-private-v1` | Real notebook geometry/HTR/ink | Split by whole page/session; rights manifest required |
| `paired-order-private-v1` | Photo/raster plus true online trace | Split by session; only set allowed for order accuracy |

## Metrics and gates

### Import and persistence

- SHA-256 equality of stored original bytes.
- Canonical manifest byte equality after save/reopen.
- Decode dimensions and media type equality.
- Wall time and peak RSS by compressed bytes and decoded pixels.
- Rejection of path traversal, oversized bytes/pixels, malformed/truncated data,
  unsupported formats, and checksum mismatch before publication.

### Rectification

- Corner error in source pixels.
- Forward/inverse reprojection RMSE and maximum error.
- Known grid-intersection error after homography.
- Aspect-ratio error.
- Failure classification for no page, partial page, and curved page.

### Ruling classification and geometry

- Classification confusion matrix for blank/squared/ruled/unknown.
- Pitch absolute and relative error, phase error, line/intersection precision and
  recall, angle error, local residual, and overlay reprojection error.
- Report separately for clean, shadowed, compressed, occluded, table-border, and
  handwriting-heavy fixtures.

### Ink separation

- Raw and cleaned mask precision/recall/F1/IoU against approved masks.
- Recall for handwritten pixels overlapping printed rules.
- Critical-mark recall for dots/diacritics.
- False removal rate by ink color and ruling color.

### Regions and lines

- Line polygon precision/recall/F1 at IoU ≥ 0.5.
- Baseline distance and reading-order correctness.
- Critical missed-line count, including marginal notes and headers.
- Per-page latency and peak RSS.

### HTR

- Unicode NFC CER and WER using one documented tokenizer/whitespace policy.
- Insertions, deletions, substitutions, exact-line accuracy, unknown count.
- Per-character errors for `ґ є і ї й ь ю я`, digits, and punctuation.
- Corrected and uncorrected photo crops reported separately.
- Median/p95 time per line, model load time, peak RSS, threads, batch size.
- Confidence risk/coverage or calibration bins when scores are available.

The initial assistive target is CER ≤ 10% on the private held-out line subset.
Failure does not permit invented correction; the prediction stays editable and
requires human review.

### Skeleton and trajectory

- Graph topology: component, endpoint, collapsed junction, edge, and cycle counts.
- Symmetric centerline distance, Chamfer distance, and rendered mask IoU at fixed
  resolution and pen width.
- Missing/extra critical-component count.
- Hypothesis count, unresolved junction count, and manual correction time.
- Stroke direction, order, pen-lift placement, and DTW only on paired online
  ground truth; these values are null for ordinary photos.

### End-to-end usefulness

- Accepted/rejected candidate rate and reason taxonomy.
- Median review time per word/candidate.
- Glyph/ligature/context coverage and authentic unique variant count.
- StylePack validation status and immutable source traceability.
- Generation time, peak RSS, page count, source-text coverage, SVG/G-code
  validation, save/reopen reproducibility, and physical metric display.
- Visual/linguistic review remains a human gate and is reported separately.

## Candidate comparison rules

1. Verify license, model card, weight hash, codec, and install before inference.
2. Run every candidate on the identical source manifest and crop variants.
3. Keep preprocessing/decoding settings in the result; crop differences are a
   benchmark dimension rather than an undocumented optimization.
4. Select on validation data under a declared CPU/RAM budget. Use the held-out
   test set once for the final report.
5. Do not rank models using CER values copied from unrelated model cards.
6. Prefer the smaller provider when quality and correction time are materially
   equivalent. Keep one fallback only when it adds measured value.

## Planned benchmark commands

Commands will be added by the task that implements each harness. Until then,
there is intentionally no command that downloads weights or claims a result.
All commands must accept a manifest, output canonical JSON/CSV, and support an
offline mode using already verified artifacts.
