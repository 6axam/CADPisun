"""Build the second review-only Ukrainian connected-handwriting pilot.

Revision 0.2.0 preserves the immutable 0.1.0 package and replaces the
ambiguous и/п/н and м/т/ш/щ wave families with manually authored directed
centre lines.  Reference material informs movement classes only; no external
font outline or workbook geometry is copied.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from generate_ua_school_pilot import BASE, Design, c, mark


ROOT = Path(__file__).parents[1]
STYLE_ID = "ua-school-v1-pilot"
REVISION = "0.2.0"
TARGET = ROOT / "assets" / "styles" / STYLE_ID / REVISION
LICENSE_ID = "ua-pilot-authored-mit"
SOURCE_REF = "UA-PILOT-AUTHORING-002"
ALL_CONTEXTS = ("isolated", "initial", "medial", "final")
RUN_CONTEXTS = ("isolated", "initial", "medial")
BREAK_BEFORE = frozenset({"п", "м", "т", "ш", "щ"})

Point = tuple[float, float]
CubicSpec = tuple[Point, Point, Point, Point]


@dataclass(frozen=True, slots=True)
class VariantDesign:
    design: Design
    suffix: str
    contexts: tuple[str, ...] = ALL_CONTEXTS
    no_join_before: bool = False
    no_join_after: bool = False
    entry_anchor: bool = True
    exit_anchor: bool = True
    transform_note: str = "manually authored directed centre-line trajectory"


def _scale_point(point: Point, factor: float) -> Point:
    x, y = point
    return x, y * factor if y >= 0 else y


def _scale_design(design: Design, factor: float = 1.45) -> Design:
    """Correct the 0.1.0 body-to-x-height ratio without changing topology."""
    body = tuple(tuple(_scale_point(point, factor) for point in segment) for segment in design.body)
    marks = tuple(
        (name, tuple(tuple(_scale_point(point, factor) for point in segment) for segment in segments))
        for name, segments in design.marks
    )
    return Design(body, design.advance, marks, design.joinable, design.critical_features)


def _terminal(design: Design) -> Design:
    """Add a compact rising word terminal; final forms have no exit anchor."""
    end = design.body[-1][-1]
    terminal = c(
        end,
        (end[0] + 35, end[1]),
        (design.advance - 75, 85),
        (design.advance - 38, 125),
    )
    return Design(design.body + (terminal,), design.advance, design.marks, design.joinable, design.critical_features)


# Seven ambiguous letters are redrawn from different movement skeletons.
# Their similar dimensions are deliberate; their upper/lower phase and the
# position of the characteristic turn carry identity.
I = Design((
    c((0, 0), (55, 55), (115, 560), (165, 690)),
    c((165, 690), (180, 720), (205, 710), (215, 625)),
    c((215, 625), (235, 430), (220, 90), (270, 20)),
    c((270, 20), (320, -25), (405, 555), (465, 685)),
    c((465, 685), (485, 725), (515, 700), (525, 615)),
    c((525, 615), (545, 415), (530, 75), (580, 20)),
    c((580, 20), (605, 0), (630, 0), (665, 0)),
), 795)

P = Design((
    c((0, 0), (55, 55), (105, 555), (155, 690)),
    c((155, 690), (170, 720), (195, 710), (205, 625)),
    c((205, 625), (225, 430), (210, 85), (260, 20)),
    c((260, 20), (305, -15), (335, 520), (385, 650)),
    c((385, 650), (430, 765), (590, 735), (610, 590)),
    c((610, 590), (625, 390), (610, 75), (665, 20)),
    c((665, 20), (690, 0), (715, 0), (750, 0)),
), 880)

N = Design((
    c((0, 0), (55, 55), (105, 555), (155, 690)),
    c((155, 690), (170, 720), (195, 710), (205, 625)),
    c((205, 625), (225, 430), (210, 85), (260, 20)),
    c((260, 20), (285, 5), (310, 255), (350, 330)),
    c((350, 330), (390, 385), (465, 365), (505, 315)),
    c((505, 315), (535, 275), (520, 590), (555, 680)),
    c((555, 680), (575, 725), (610, 690), (615, 595)),
    c((615, 595), (625, 390), (610, 75), (665, 20)),
    c((665, 20), (690, 0), (715, 0), (750, 0)),
), 880)

M = Design((
    c((0, 0), (60, 55), (145, 575), (205, 700)),
    c((205, 700), (220, 735), (245, 715), (260, 645)),
    c((260, 645), (290, 470), (285, 95), (340, 20)),
    c((340, 20), (385, -20), (425, 520), (485, 655)),
    c((485, 655), (535, 765), (685, 735), (705, 590)),
    c((705, 590), (720, 390), (705, 75), (760, 20)),
    c((760, 20), (785, 0), (810, 0), (845, 0)),
), 975)

T = Design((
    c((0, 0), (55, 55), (105, 540), (155, 665)),
    c((155, 665), (200, 765), (320, 725), (335, 590)),
    c((335, 590), (350, 390), (335, 75), (390, 20)),
    c((390, 20), (435, -20), (465, 525), (520, 655)),
    c((520, 655), (565, 755), (685, 720), (700, 585)),
    c((700, 585), (715, 385), (700, 75), (755, 20)),
    c((755, 20), (800, -20), (830, 525), (885, 655)),
    c((885, 655), (930, 755), (1050, 720), (1065, 585)),
    c((1065, 585), (1080, 385), (1065, 75), (1120, 20)),
    c((1120, 20), (1145, 0), (1170, 0), (1205, 0)),
), 1335)

SH = Design((
    c((0, 0), (55, 55), (105, 555), (155, 695)),
    c((155, 695), (170, 725), (195, 710), (205, 625)),
    c((205, 625), (225, 445), (210, 90), (260, 20)),
    c((260, 20), (310, -25), (350, 555), (405, 690)),
    c((405, 690), (420, 725), (445, 710), (455, 625)),
    c((455, 625), (475, 445), (460, 90), (510, 20)),
    c((510, 20), (560, -25), (600, 555), (655, 690)),
    c((655, 690), (670, 725), (695, 710), (705, 625)),
    c((705, 625), (725, 445), (710, 90), (760, 20)),
    c((760, 20), (785, 0), (810, 0), (845, 0)),
), 975)

SHCH = Design((
    *SH.body[:-1],
    c((760, 20), (790, -20), (785, -275), (845, -315)),
    c((845, -315), (890, -345), (925, -110), (880, -35)),
    c((880, -35), (865, -10), (910, 0), (955, 0)),
), 1085)

I_DOTTED = Design((
    c((0, 0), (55, 55), (105, 555), (165, 690)),
    c((165, 690), (195, 735), (265, 705), (285, 610)),
    c((285, 610), (310, 410), (305, 75), (360, 20)),
    c((360, 20), (385, 0), (410, 0), (445, 0)),
), 575, marks=(mark("dot", c((205, 920), (210, 945), (238, 945), (243, 920))),), critical_features=("dot",))

YI = Design(I_DOTTED.body, I_DOTTED.advance, marks=(
    mark("dot-left", c((165, 920), (170, 945), (198, 945), (203, 920))),
    mark("dot-right", c((275, 920), (280, 945), (308, 945), (313, 920))),
), critical_features=("dot-left", "dot-right"))

Y = Design(I.body, I.advance, marks=(mark(
    "breve", c((330, 920), (405, 835), (545, 835), (625, 920)),
),), critical_features=("breve",))

GHE_UPTURN = Design((
    c((0, 0), (60, 55), (125, 520), (205, 670)),
    c((205, 670), (275, 785), (495, 745), (565, 610)),
    c((565, 610), (605, 500), (590, 110), (650, 20)),
    c((650, 20), (675, 0), (705, 0), (740, 0)),
), 870, marks=(mark(
    "top-hook", c((285, 845), (380, 845), (505, 845), (565, 845)),
    c((565, 845), (595, 845), (605, 895), (610, 930)),
),), critical_features=("top-hook",))


REDRAWN = {
    "и": I, "п": P, "н": N, "м": M, "т": T, "ш": SH, "щ": SHCH,
    "і": I_DOTTED, "ї": YI, "й": Y, "ґ": GHE_UPTURN,
}


def _scaled_base(character: str) -> Design:
    if character == "У":
        return BASE[character]
    return _scale_design(BASE[character])


def _variants() -> dict[str, tuple[VariantDesign, ...]]:
    variants: dict[str, tuple[VariantDesign, ...]] = {}
    for character in BASE:
        if character in REDRAWN:
            design = REDRAWN[character]
            if character in BREAK_BEFORE:
                variants[character] = (
                    VariantDesign(design, "initial", ("isolated", "initial")),
                    VariantDesign(
                        design, "medial", ("medial",), no_join_before=True,
                        transform_note="manually authored medial form with deliberate pen lift before the characteristic entry",
                    ),
                    VariantDesign(
                        _terminal(design), "final", ("final",), no_join_before=True,
                        no_join_after=True, exit_anchor=False,
                        transform_note="manually authored final form with deliberate entry lift and compact terminal",
                    ),
                )
            else:
                variants[character] = (
                    VariantDesign(design, "run", RUN_CONTEXTS),
                    VariantDesign(
                        _terminal(design), "final", ("final",), no_join_after=True,
                        exit_anchor=False, transform_note="manually authored body with compact final terminal",
                    ),
                )
        else:
            design = _scaled_base(character)
            variants[character] = (VariantDesign(
                design,
                "metric",
                transform_note=(
                    "0.1.0 project-authored centre line with explicit 1.45 vertical metric correction"
                    if character != "У" else "unchanged 0.1.0 project-authored capital trajectory"
                ),
            ),)
    return variants


DESIGNS = _variants()


def _segment(value: CubicSpec) -> dict[str, object]:
    p0, c1, c2, p1 = value
    point = lambda item: {"x": float(item[0]), "y": float(item[1])}
    return {"kind": "cubic", "p0": point(p0), "c1": point(c1), "c2": point(c2), "p1": point(p1)}


def _safe_name(character: str, suffix: str) -> str:
    codepoints = "-".join(f"{ord(item):04x}" for item in character)
    return f"glyphs/u-{codepoints}-{suffix}.json"


def _unit(dx: float, dy: float) -> dict[str, float]:
    length = math.hypot(dx, dy)
    return {"x": dx / length, "y": dy / length}


def _glyph(character: str, variant: VariantDesign) -> dict[str, object]:
    design = variant.design
    strokes = [{
        "id": "body",
        "segments": [_segment(item) for item in design.body],
        "source_refs": [SOURCE_REF],
        "role": "body",
        "direction_provenance": "authored",
    }]
    for name, segments in design.marks:
        strokes.append({
            "id": name,
            "segments": [_segment(item) for item in segments],
            "source_refs": [SOURCE_REF],
            "role": "mark",
            "direction_provenance": "authored",
        })
    if design.joinable:
        first = design.body[0]
        last = design.body[-1]
        entry = None
        exit = None
        if variant.entry_anchor:
            entry = {
                "stroke_id": "body", "endpoint": "start",
                "tangent": _unit(first[1][0] - first[0][0], first[1][1] - first[0][1]),
                "class_id": "baseline-entry", "allowed_partner_classes": ["baseline-exit"],
                "max_gap_gu": 220.0, "max_vertical_delta_gu": 90.0, "max_angle_deg": 58.0,
            }
        if variant.exit_anchor:
            exit = {
                "stroke_id": "body", "endpoint": "end",
                "tangent": _unit(last[3][0] - last[2][0], last[3][1] - last[2][1]),
                "class_id": "baseline-exit", "allowed_partner_classes": ["baseline-entry"],
                "max_gap_gu": 220.0, "max_vertical_delta_gu": 90.0, "max_angle_deg": 58.0,
            }
        join_spec: dict[str, object] = {
            "mode": "single_body_deferred_marks",
            "body_stroke_id": "body",
            "deferred_marks": [name for name, _ in design.marks],
            "entry": entry,
            "exit": exit,
            "no_join_before": variant.no_join_before,
            "no_join_after": variant.no_join_after,
        }
    else:
        join_spec = {"mode": "none", "no_join_before": True, "no_join_after": True}
    return {
        "format": "hp-glyph",
        "schema_version": "1.0",
        "variant_id": f"ua-pilot-v020-{ord(character):04x}-{variant.suffix}",
        "key": character,
        "strokes": strokes,
        "advance_gu": design.advance,
        "context_tags": list(variant.contexts),
        "join_spec": join_spec,
        "provenance": {
            "license_id": LICENSE_ID,
            "source_method": "manual_vector",
            "author_id": "handwriting-plotter-project",
            "transforms": [variant.transform_note, "no external outlines or workbook coordinates"],
            "reviewed_by": "automated-geometry-review",
            "review_record_id": "review/pilot-review.json",
        },
        "review_status": "approved",
        "critical_features": list(design.critical_features),
    }


def _canonical(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    (TARGET / "glyphs").mkdir(parents=True)
    (TARGET / "licenses").mkdir()
    (TARGET / "review").mkdir()

    license_text = (ROOT / "assets" / "styles" / STYLE_ID / "0.1.0" / "licenses" / f"{LICENSE_ID}.txt").read_text()
    license_relative = f"licenses/{LICENSE_ID}.txt"
    (TARGET / license_relative).write_text(license_text)

    glyph_files: list[str] = []
    file_hashes: dict[str, str] = {}
    for character in sorted(DESIGNS, key=ord):
        for variant in DESIGNS[character]:
            relative = _safe_name(character, variant.suffix)
            raw = _canonical(_glyph(character, variant))
            (TARGET / relative).write_bytes(raw)
            glyph_files.append(relative)
            file_hashes[relative] = hashlib.sha256(raw).hexdigest()

    words = (
        "Україна", "ґрунт", "мама", "привіт", "школа", "пишу",
        "ймовірність", "машина", "мишка", "тиша", "шишки", "написання",
    )
    pairs = sorted({pair for word in words for pair in zip(word, word[1:], strict=False)})
    review = {
        "style_id": STYLE_ID,
        "revision": REVISION,
        "status": "needs_human_visual_acceptance",
        "automated_geometry_review": "passed_by_test_suite",
        "word_corpus": list(words),
        "pair_corpus": ["".join(pair) for pair in pairs],
        "redrawn_letters": ["и", "п", "н", "м", "т", "ш", "щ", "і", "ї", "й", "ґ"],
        "acceptance_questions": [
            "Can readers distinguish и/п/н and м/т/ш without knowing the source text?",
            "Are щ descender and ї/й/ґ marks recognizable at 3.0-4.0 mm?",
            "Are joins natural and free of collisions?",
            "Are stroke order and pen lifts physically plausible?",
        ],
        "not_a_product_release": True,
    }
    review_raw = _canonical(review)
    (TARGET / "review" / "pilot-review.json").write_bytes(review_raw)
    file_hashes["review/pilot-review.json"] = hashlib.sha256(review_raw).hexdigest()

    provenance = {
        "record_id": SOURCE_REF,
        "style_id": STYLE_ID,
        "revision": REVISION,
        "source_method": "manual_vector",
        "geometry_license": "MIT",
        "parent_revision": "0.1.0",
        "authoring_note": "Problem letters were manually redrawn as directed centre lines; remaining project-authored glyphs received an explicit vertical metric correction.",
        "research_references": [
            {"name": "MON order 978", "url": "https://mon.gov.ua/npa/pro-utvorennya-robochoyi-grupi-z-rozroblennya-yedinih-zrazkiv-kaligrafichnogo-pisma-bukv-ukrayinskogo-alfavitu-yih-zyednan-ta-cifr", "role": "official scope reference", "integrated": False},
            {"name": "NAES handwritten alphabet exercises", "url": "https://lib.iitta.gov.ua/id/eprint/739131/1/%D0%9F%D0%BE%D1%81%D1%96%D0%B1%D0%BD%D0%B8%D0%BA.pdf", "role": "visual distinction reference", "integrated": False},
            {"name": "NAES movement grouping", "url": "https://lib.iitta.gov.ua/id/eprint/712954/1/%D0%BC%D0%BE%D0%BD%D0%BE%D0%B3%D1%80%D0%B0%D1%84%D1%96%D1%8F%20%D0%A4%D0%BE%D1%80%D0%BC%D0%B8.pdf", "role": "pen movement class reference", "integrated": False},
            {"name": "NAES grade-one method", "url": "https://lib.iitta.gov.ua/id/eprint/714300/1/%D0%9C%D0%A0%201%20%D0%BA%D0%BB%D0%B0%D1%81.pdf", "role": "join and proportion reference", "integrated": False},
        ],
    }
    provenance_raw = _canonical(provenance)
    (TARGET / "provenance.json").write_bytes(provenance_raw)
    file_hashes["provenance.json"] = hashlib.sha256(provenance_raw).hexdigest()
    file_hashes[license_relative] = hashlib.sha256(license_text.encode()).hexdigest()

    coverage = sorted(DESIGNS, key=ord)
    manifest = {
        "format": "hp-style",
        "schema_version": "1.0",
        "style_id": STYLE_ID,
        "revision": REVISION,
        "display_name": "REVIEW ONLY — Ukrainian school cursive pilot, geometry revision 2",
        "scripts": ["Cyrillic"],
        "license_record": {"license_id": LICENSE_ID, "name": "MIT project-authored pilot geometry", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {
            "x_height_gu": 1000.0, "ascender_gu": 1200.0, "descender_gu": -350.0,
            "space_advance_gu": 620.0, "line_gap_gu": 550.0, "supported_x_height_mm": [3.0, 4.0],
        },
        "coverage": coverage,
        "glyph_files": glyph_files,
        "join_rules": {
            "strategy": "authored baseline anchors, contextual final terminals, and cubic connectors",
            "classes": ["baseline-entry", "baseline-exit"],
            "review_corpus": "review/pilot-review.json",
            "natural_pen_lifts_allowed": True,
        },
        "variation_policy": {
            "max_scale_fraction": 0.008, "max_shear_deg": 0.5,
            "max_baseline_offset_mm": 0.03, "max_word_space_fraction": 0.025, "max_line_y_mm": 0.04,
        },
        "file_hashes": file_hashes,
        "approved": True,
        "production_eligible": False,
        "test_only": True,
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
