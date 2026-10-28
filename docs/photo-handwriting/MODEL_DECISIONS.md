# Photo-to-Handwriting model and architecture decisions

Created: 2026-10-23. These decisions refine the existing project ADRs; they do
not supersede `DECISIONS.md`, immutable StylePack contracts, or hardware gates.

## PH-ADR-001 — Reuse the existing personal-style pipeline

**Status:** Accepted.

Photo processing ends at reviewed glyph/ligature candidates compatible with the
existing normalization, annotation, draft, and `PersonalStylePackBuilder`
interfaces. Generation continues through existing shaping, layout, PenPlan,
SVG, and virtual G-code. No second font format or renderer is introduced.

## PH-ADR-002 — Add a Qt-free learning domain

**Status:** Accepted.

Versioned source assets, transforms, ruling estimates, regions, transcriptions,
masks, graph candidates, alignments, and review requests belong under
`handwriting_plotter.learning`. Image codecs, OpenCV, and HTR engines implement
narrow ports in adapters. PySide6 presents these services but does not define
their persisted models.

## PH-ADR-003 — Preserve immutable bytes and coordinate transforms

**Status:** Accepted.

The exact original image bytes are content-addressed by SHA-256 and never
rewritten. Every derived image records input/output hashes, algorithm revision,
parameters, pixel frame, dimensions, and forward/inverse transforms. Corrected
and original views remain available together.

For TASK 01 the provisional default safety envelope is 32 MiB compressed input,
60 million decoded pixels, and 20,000 pixels on either dimension. These are
explicit configuration constants and must be validated against real fixtures on
Linux and Windows before being treated as final product limits.

## PH-ADR-004 — Keep semantic and geometric streams independent

**Status:** Accepted.

HTR text does not determine exact letter contours. Ink components do not
determine Unicode labels. Regions reference both streams, and alignment stores
alternatives, source spans, confidence origin, and unresolved boundaries.
Connected cursive may remain a word/ligature sample instead of being cut into
fictitious characters.

## PH-ADR-005 — Treat offline direction as a hypothesis

**Status:** Accepted.

Photo-derived paths use `offline_inferred`; authentic pointer recordings keep
`online_capture`. The graph is stored before traversal, hypotheses are bounded,
and ambiguity remains visible. Reversal is allowed only for inferred candidates
or by explicit human reconstruction, never silently for online captures.

## PH-ADR-006 — Classical CV before neural page preprocessing

**Status:** Accepted.

OpenCV-based corners, homography, deskew, color/morphology, periodic ruling
analysis, and manual fallbacks are the initial page pipeline. They are local,
inspectable, testable with exact synthetic geometry, and adequate for planar
pages. Curved-page dewarping remains a separate future capability.

TASK 03 resolves the first adapter pin as optional
`opencv-python-headless==4.13.0.92` with locked NumPy 2.2.6. It implements only
page proposal, orientation composition, homography, and fine deskew. This pin
does not select the later segmentation/skeleton stack or HTR environment.

TASK 04 adds only a bounded local classifier on that adapter: repeated long
horizontal/vertical evidence maps to proposed blank/squared/ruled/mixed/unknown
with explicitly heuristic confidence. A user may store a human override. Pitch,
phase, physical size, overlays, and any learned classifier remain deferred, so
the first implementation cannot present a page-type guess as measured geometry.

## PH-ADR-007 — Store periodic pixel geometry before physical calibration

**Status:** Accepted.

TASK 05 uses local Canny/Hough evidence and robust periodic fitting to store only
pixel pitch, phase/origin, direction and fit residual in the immutable ruling
estimate. The overlay is reconstructed from this compact model. Four repeated
long lines are required; sparse table borders fail rather than being promoted to
paper geometry. A user can replace values explicitly. Physical millimetres,
paper-removal masks, learned deformation and general real-photo accuracy remain
outside the TASK 05 detector and require the subsequent explicit calibration
decision.

## PH-ADR-013 — Physical scale is opt-in and axis-specific

**Status:** Accepted for TASK 06.

Measured pixel pitch maps to relative cell/rule units without a physical claim.
Millimetres enter a manifest only after a user-entered reference or an explicit
5 mm notebook preset. The preset is provenance, not a detector result. Scale is
frame-bound and follows ruling normals, so a skewed photograph is not silently
treated as image-aligned millimetres. Ruled paper calibrates its measured Y
axis only. Geometry revisions erase calibration because a changed pitch makes
the old conversion invalid. Fit residuals are not promoted to physical
uncertainty without a validated reference-error model.

## PH-ADR-008 — Isolate HTR providers

**Status:** Accepted.

Kraken and Transformers/PyTorch recognizers do not enter the default CADPisun
environment. A versioned subprocess/provider protocol carries checksummed image
artifacts and canonical results. Providers initialize lazily, can run on CPU,
report progress/resource limits, support cooperative cancellation, and work
offline after explicit model installation.

## PH-ADR-009 — Do not select an HTR winner during architecture work

**Status:** Accepted.

The first benchmark compares a lightweight Ukrainian CRNN-CTC checkpoint with
at least one Ukrainian TrOCR checkpoint on the same CADPisun lines. Kraken is a
strong segmentation candidate and may also supply recognition when a verified
Ukrainian model is available. Selection depends on measured CER/WER, protected
characters, correction time, latency, RAM, license, codec, and install cost.

Current planning order:

1. `achimrabus/crnn-ctc-ukrainian` as the inexpensive CPU baseline.
2. `cyrillic-trocr/trocr-ukrainian-handwritten` as a smaller TrOCR comparison.
3. A Hukyl 558M real-only/mixed model only if earlier candidates leave a useful
   quality gap worth the 2.23 GB weight and runtime cost.

This order is a download/benchmark strategy, not a quality ranking.

## PH-ADR-010 — Preserve rights and privacy as data invariants

**Status:** Accepted.

Every source/model/dataset record includes license/rights/consent reference,
hash, origin, and redistribution status. Private handwriting stays under the
user data root and is excluded from Git by default. Technical logs omit notebook
content. A missing rights record blocks publication/training but not local
inspection of the user's own explicitly imported data.

## PH-ADR-011 — Notebook backgrounds are page geometry

**Status:** Accepted for TASK 18.

Squared and ruled templates use physical millimetres and remain separate from
handwriting PenPlan strokes. Preview/background export can include them; pen-only
SVG and virtual G-code exclude ruling unless the user explicitly requests a
future verified ruling-plot operation. A 5 mm cell is a preset, not an inference.

## PH-ADR-012 — Fit style metrics, never deform each glyph independently

**Status:** Accepted for TASK 19.

Notebook adaptation derives one coherent mapping for x-height, ascenders,
descenders, baseline offset, advances, spacing, and line pitch. It may preserve
learned proportions or fit a chosen writing height/ruling. It must keep joins
continuous, display physical dimensions, and report overflow instead of silently
shrinking or applying nonuniform per-glyph stretches.

## PH-ADR-013 — Bounded trail hypotheses without invented junction geometry

**Status:** Accepted for TASK 14.

Use bounded partial port matchings and a bounded order/orientation beam over
the existing immutable skeleton graph. Keep multiple candidates, exact edge
references, node regions and explicit unknowns. Do not duplicate edges to force
an Euler path or interpolate straight bridges across compact junctions.
Ranking constants are versioned provisional geometric heuristics; calibration
on paired online/photo traces remains deferred. A search fallback preserves
coverage with unresolved directions/order, no selected pen-lift sequence and
null cost. Explicit human selection is append-only and remains
`offline_inferred`; it never becomes `online_capture` or automatic publication.

See [TRAJECTORY_HYPOTHESES.md](TRAJECTORY_HYPOTHESES.md).

## Deferred decisions

| Decision | Earliest task | Required evidence |
|---|---|---|
| Full vision worker dependency pins | TASK 07 | Ruling/mask fixtures, worker isolation, Linux/Windows install |
| Ink color/separation profiles | TASK 07 | Approved masks for representative pen/paper conditions |
| Primary and fallback HTR provider | TASK 09 | Identical-corpus quality, latency, RAM, rights, and install report |
| Alignment algorithm | TASK 12 | Ambiguous cursive/diacritic fixtures and alternative preservation |
| Calibrated stroke-order scoring weights | After TASK 14 heuristic foundation | Paired online/photo subset plus manual correction time; not provided by synthetic route tests |
| Clustering/deduplication thresholds | TASK 15 | Repeated authentic variants with reviewer decisions |

No deferred choice blocks TASK 06.
