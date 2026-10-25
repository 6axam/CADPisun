# TASK 12A: word and text-span alignment

This Qt-free API produces hypotheses for human inspection. It uses the existing
TASK 07 mask, TASK 08 line region, TASK 10 immutable PNG crop and TASK 11 review
store. It does not run a recognizer. TASK 12B consumes these records through
[GRAPHEME_ALIGNMENT.md](GRAPHEME_ALIGNMENT.md) and provides a diagnostic SVG
overlay. The callable APIs do not add a new Studio editing workflow.

## Verified photo entry point

`source` is the current `PhotoRecord` and `review` the selected persisted
`TranscriptionReviewRecord`, from the same local user-data root. The crop must
already be stored under its TASK 10 derivative hash. `edited` and `accepted`
reviews are eligible; `unreviewed` and `unresolved` reviews refuse alignment.

```python
from handwriting_plotter.adapters.images.opencv import OpenCvLineMaskCropper
from handwriting_plotter.learning import WordAlignmentRepository, align_photo_line

alignment = align_photo_line(
    photos=photo_repository,
    source=source,
    review=review,
    cropper=OpenCvLineMaskCropper(),
    max_alternatives=8,
)
repository = WordAlignmentRepository(photo_repository.root)
record = repository.store(alignment)
```

The entry point validates the source manifest and latest review revision, crop
and selected-mask SHA-256, decoded dimensions and line frame. Both crop and mask
must match the line bounding box. An outdated review/manifest, changed crop or
corrupt asset causes an error. Missing files remain explicit errors. Source
pixels, HTR predictions and reviews are never rewritten. The optional OpenCV
adapter decodes/crops only: there is no erosion, filtering or small-mark removal.

`align_reviewed_line()` is the lower-level pure geometry function for already
validated binary crops and synthetic unit tests. It cannot check an on-disk
asset or latest revision by itself; use `align_photo_line()` for photo-backed
work. Its record leaves the optional source-frame translation unknown.

On reuse, check the record against the caller's current verified crop identity
and selected mask:

```python
record = repository.load(record.sha256)
repository.ensure_current(
    record,
    reviews=review_repository,
    source_manifest_sha256=current_source.sha256,
    line_id=current_review.revision.line_id,
    crop_sha256=current_review.revision.crop_sha256,
    mask_sha256=current_selected_mask_sha256,
)
```

## Text and geometry

Text spans use half-open Python Unicode code-point offsets `[start, end)` into
the exact reviewed string. The tokenizer preserves all input characters,
including repeated spaces, CR/LF, punctuation and combining marks. It performs
no second NFC conversion: TASK 11 already normalizes saved review text. The
three Ukrainian apostrophes `'`, `’`, `ʼ` remain internal word characters when
between word parts; standalone quotes, hyphens and punctuation remain separate
spans. Line-ending hyphens/newlines are preserved, never silently dehyphenated.
No dictionary or character-shape recognizer decides what the text means.

Every foreground pixel participates in an 8-connected component, including
one-pixel dots and punctuation. Horizontal projection gaps between component
envelopes generate up to four competing groupings. The K-best monotone DP
uses relative widths, text lengths and gaps as soft layout cues. A shared large
area remains available for connected words. Results are deterministic for the
same reviewed text, binary crop and parameters; record UUID/time are event
metadata and change on a new invocation.

All automatic word assignments remain `ambiguous`, even if one grouping has
exactly as many areas as text words. Whitespace has semantic state `non_ink`;
this does not assert that a photographed word boundary exists there.
Punctuation geometry stays `unresolved` while its pixels are retained among
the components. `optimization_cost` ranks hypotheses; it is not confidence.
No result contains letter boundaries, stroke order or reconstructed paths.

## Storage, coordinates and bounds

`hp-word-alignment/1.0` records live in the local `word-alignments/` store,
indexed by the SHA-256 of canonical JSON. Writes use the existing durable
no-overwrite photo repository writer; all reads check hashes and model
invariants. The current algorithm is `word-spans-components/2`; `/1` records
remain readable. Existing project and StylePack formats are unchanged.

Provenance includes source manifest, `line_id`, original PNG `crop_sha256`,
selected mask hash, review revision hash, exact reviewed-text hash and algorithm
version. Boxes use half-open pixel bounds in `line-crop-px-top-left`, with
positive X to the right and Y down. Photo-backed records additionally store
`frame_id` and `crop_left_px`/`crop_top_px`: add those offsets to map any box
into the existing frame, whose TASK 03 transforms then map back to source pixels.

Work limits are 4 million crop pixels, 256 components, 128 words, 4,096 spans,
four grouping variants, 50,000 DP transitions per grouping, and sixteen output
alternatives. Too much input is refused explicitly. A DP budget refusal retains
the coarse grouping and adds `SEARCH_BUDGET_EXHAUSTED`. No limit is implemented
by deleting dots or small components.

Tests use generated data only. Actual photos, masks, crops, review strings and
alignment results stay under the private user-data root, outside Git. The
current evidence covers contract/geometry regressions, not measured alignment
accuracy on a real handwriting corpus. TASK 12B now supplies grapheme/join/ligature
hypotheses and diagnostic overlays; inseparable clusters retain shared geometry.
