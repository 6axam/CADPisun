# TASK 12B: grapheme, join and ligature hypotheses

This stage refines existing [TASK 12A word candidates](WORD_ALIGNMENT.md).
It consumes an accepted human review, its persisted word-alignment record and
the same immutable crop/mask/frame. No new recognizer, image segmentation,
skeletonization or stroke reconstruction is run.

## Verified local workflow

The following objects are already selected from Studio's local repositories:
`photo_repository`, current `source: PhotoRecord`, `review:
TranscriptionReviewRecord`, and `word_record: WordAlignmentRecord`.
The review must be `accepted`, not merely edited. Rebuild TASK 12A if its review
is obsolete or a legacy record lacks source-frame metadata.

```python
from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper
from handwriting_plotter.learning import (
    GraphemeAlignmentRepository, align_photo_graphemes,
    render_alignment_overlay_svg,
)

cropper = OpenCvLineMaskCropper()
alignment = align_photo_graphemes(
    photos=photo_repository, source=source, review=review,
    words=word_record, cropper=cropper,
)
repository = GraphemeAlignmentRepository(photo_repository.root)
stored = repository.store(alignment)

# On restart/use, pass the current selected parent word record and source.
restored = repository.load_current(
    stored.sha256, photos=photo_repository, source=source,
    review=review, words=word_record, cropper=cropper,
)
crop_png = photo_repository.derivative_path(review.revision.crop_sha256, "png").read_bytes()
svg = render_alignment_overlay_svg(
    alignment=restored.alignment, words=word_record, crop_png=crop_png,
    hypothesis_id=restored.alignment.hypotheses[0].hypothesis_id,
)
# Save svg only to a chosen private diagnostic-output path.
```

The SVG embeds the original crop. Green dashed boxes identify parent word
geometry; orange identifies shared groups and cyan identifies single-grapheme
candidates. Group titles and a separate ledger expose text offsets, relation,
state and unresolved joins. Red ledger entries have unresolved geometry; no
fictitious box is drawn for them. The output is diagnostic, independent of
PenPlan, production SVG and G-code. A caller can select any stored hypothesis.

`align_graphemes()` is the pure geometry entry point for previously validated
inputs and synthetic tests. It checks input identities/structure but cannot
check on-disk freshness. `load()` checks immutable record/parent integrity for
archival inspection; `load_current()` is required before applying results to a
current photo or downstream alignment workflow. A newer selected word record,
review, mask, crop or segmentation causes explicit invalidation.

## Typed results and geometry

| Type | Meaning |
|---|---|
| `GraphemeToken` | One extended grapheme cluster, exact half-open code-point offsets and references to TASK 12A spans |
| `GraphemeInkGroup` | One or more graphemes mapped to complete components, or explicitly unresolved/non-ink text |
| `UnresolvedJoin` | Adjacent graphemes sharing ink without an observable cut |
| `GraphemeHypothesis` | A monotone grouping tied to one parent word alternative, with heuristic ranking cost and retained residual ink |
| `GraphemeAlignment` | Provenance, frame translation, tokens/components, bounded alternatives and resource counters |

Unicode uses the installed `regex` package's `\X`. The stage never renormalizes
or rewrites text; TASK 11 owns NFC. Ukrainian apostrophes, `і`, `ї`, `є`, `ґ`,
`й`, `ь`, numbers, punctuation, combining marks and emoji clusters retain their
exact TASK 12A offsets. A cluster crossing tokenizer spans references every
overlapping span and stays unresolved if no word candidate safely owns it.

For each parent alternative, shared components and overlapping word envelopes
are merged into a safe unit. Components whose X envelopes overlap form an
indivisible atom: a detached dot above a body stays available with that body.
The graph advances monotonically through complete atoms and graphemes, using
edges that consume one grapheme with multiple atoms or multiple graphemes with
one atom. K-best dynamic programming uses relative width/count and grouping
penalties as layout cues. It performs no character-shape classification.

Every parent alternative retains a coarse hypothesis even when cheaper detailed
ones exist. `ambiguous` never asserts the true letter or ligature. The relation
`join_or_ligature` means that the group could be a cursive connection or a
ligature; no distinction between those is claimed from geometry alone.
`shared_words` preserves joined word candidates. Every internal boundary in a
shared group has an explicit `unresolved` join. Ranking cost is not probability
or confidence.

The same component cannot appear twice within a hypothesis. Every grapheme is
covered once, and every component is either assigned once or listed in
`unassigned_component_ids`. Punctuation that TASK 12A left without geometry
remains unresolved here; its components are preserved. Bounding boxes enclose
whole components and never imply a cut through connected ink.

All boxes use TASK 12A's half-open `line-crop-px-top-left` coordinates. Add
`crop_left_px`/`crop_top_px` to reach the persisted `frame_id`; the existing
TASK 03 transforms map that frame back to source pixels.

## Fully synthetic examples

These are generated rectangles/dots/crossings labelled for contract testing.
They are not handwriting samples or recognition accuracy measurements.

| Text and synthetic geometry | Result |
|---|---|
| `мама` on one connected horizontal stroke | `g-0..g-3` share the complete box; three unresolved joins; no four-letter cuts |
| `ї` with two detached dots over a connected body | One grapheme with three retained components, including both dots |
| `іі` with a dot horizontally between two bodies | Competing ownership of the dot plus a coarse shared group |
| `ммм` over three separated components | Alternatives include three monotone groups and a whole shared region |
| `мій дім` on crossing/connected ink | Shared word group with unresolved joins; text whitespace is retained separately |
| `...` without parent word geometry | Three unresolved graphemes and explicitly retained residual ink |
| An empty mask | All non-whitespace graphemes unresolved; no manufactured boxes |

## Bounds, persistence and limitations

Default limits are 512 graphemes, 256 inherited ink components, 4,096 graph
nodes, 20,000 DP transitions across the whole run, 2,048 candidate edges,
16 output hypotheses, three paths per node and eight consumed items per local
edge. `GraphemeSearchLimits` allows lower budgets and bounded increases up to
50,000 transitions, 8,192 candidates, four paths per node and sixteen items per
edge. Each hypothesis has at most 512 groups. If a graph budget is exhausted,
the record sets `budget_exhausted` and preserves all parent alternatives as
coarse safe hypotheses; earlier complete refinements may remain. The coarse
fallback can encompass a larger unit than one local DP edge. If the output cap
cannot represent every parent alternative, or text exceeds 512 graphemes, the
request fails explicitly without dropping text or ink.

Canonical `hp-grapheme-alignment/1.0` records use algorithm
`grapheme-component-graph/1`. They are stored in local `grapheme-alignments/`
through the existing atomic/fsync/no-overwrite writer, with an 8 MiB record
limit. They bind the word-record hash, source manifest, line, crop, encoded mask,
binary-mask digest (including dimensions), accepted review and exact text hash.
Reference and coverage invariants run on read/write; active reopen validates the
current assets and selected parent again. UUID/time identify events; geometry,
ranking and counters are deterministic for identical inputs/parameters.

Qt, OpenCV and ML packages are absent from core imports. Only the existing
explicit OpenCV adapter is used for photo decoding. Personal images/texts and
all their derived records and SVGs stay in local private user data. Tests and
the inspected SVGs use synthetic data exclusively.

The stage exposes uncertainty rather than guaranteed character boundaries.
Horizontal projection constraints can conservatively merge overlapping/slanted
strokes; punctuation ownership and inseparable letter/ligature distinctions
can remain unresolved. No real-notebook accuracy or direction/order of strokes
has been established. A new Studio alignment-review panel is not part of this
callable API. TASK 13 remains a separate, unstarted skeleton-extraction stage.
