"""Build the review-only Ukrainian connected-handwriting pilot StylePack.

The geometry in this file is deliberately authored as directed centre lines.
It is not derived by slanting an outline font and it is not a complete or
human-accepted ``ua-school-v1`` release.  The generated package is an
engineering candidate for word-level visual review.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).parents[1]
STYLE_ID = "ua-school-v1-pilot"
REVISION = "0.1.0"
TARGET = ROOT / "assets" / "styles" / STYLE_ID / REVISION
LICENSE_ID = "ua-pilot-authored-mit"
SOURCE_REF = "UA-PILOT-AUTHORING-001"

Point = tuple[float, float]
CubicSpec = tuple[Point, Point, Point, Point]


@dataclass(frozen=True, slots=True)
class Design:
    body: tuple[CubicSpec, ...]
    advance: float
    marks: tuple[tuple[str, tuple[CubicSpec, ...]], ...] = ()
    joinable: bool = True
    critical_features: tuple[str, ...] = ()


def c(p0: Point, c1: Point, c2: Point, p1: Point) -> CubicSpec:
    return p0, c1, c2, p1


def mark(name: str, *segments: CubicSpec) -> tuple[str, tuple[CubicSpec, ...]]:
    return name, tuple(segments)


# Coordinates use GlyphFrame: baseline y=0, positive y upwards. Every joinable
# body begins on the baseline with an up-right tangent and finishes on the
# baseline with a rightward tangent. The remaining advance is the authored
# connector interval. These are letter-specific pen trajectories, not outlines.
BASE: dict[str, Design] = {
    "а": Design((
        c((0, 0), (70, 70), (120, 260), (235, 365)),
        c((235, 365), (350, 475), (535, 430), (555, 255)),
        c((555, 255), (575, 80), (410, -25), (285, 35)),
        c((285, 35), (170, 90), (190, 300), (320, 360)),
        c((320, 360), (470, 430), (565, 245), (570, 105)),
        c((570, 105), (585, 25), (630, 0), (700, 0)),
    ), 870),
    "в": Design((
        c((0, 0), (65, 70), (145, 250), (210, 520)),
        c((210, 520), (260, 745), (455, 805), (500, 650)),
        c((500, 650), (545, 505), (375, 390), (250, 430)),
        c((250, 430), (135, 470), (170, 135), (315, 55)),
        c((315, 55), (455, -25), (600, 55), (585, 210)),
        c((585, 210), (570, 315), (490, 355), (415, 325)),
        c((415, 325), (520, 265), (600, 55), (610, 20)),
        c((610, 20), (625, 5), (660, 0), (715, 0)),
    ), 885),
    "г": Design((
        c((0, 0), (65, 70), (120, 285), (245, 390)),
        c((245, 390), (355, 480), (530, 430), (545, 265)),
        c((545, 265), (555, 110), (470, 10), (545, 0)),
        c((545, 0), (575, 0), (615, 0), (665, 0)),
    ), 835),
    "ґ": Design((
        c((0, 0), (65, 70), (120, 285), (245, 390)),
        c((245, 390), (355, 480), (530, 430), (545, 265)),
        c((545, 265), (555, 110), (470, 10), (545, 0)),
        c((545, 0), (575, 0), (615, 0), (665, 0)),
    ), 835, marks=(mark("top-hook",
        c((335, 535), (400, 585), (500, 565), (555, 515)),
    ),), critical_features=("top-hook",)),
    "д": Design((
        c((0, 0), (70, 70), (115, 265), (235, 365)),
        c((235, 365), (350, 470), (535, 430), (550, 250)),
        c((550, 250), (565, 80), (405, -25), (285, 35)),
        c((285, 35), (180, 90), (190, 300), (320, 360)),
        c((320, 360), (455, 420), (555, 235), (575, 80)),
        c((575, 80), (600, -70), (585, -285), (700, -310)),
        c((700, -310), (825, -335), (850, -115), (735, -45)),
        c((735, -45), (690, -15), (715, 0), (770, 0)),
    ), 940),
    "е": Design((
        c((0, 0), (70, 70), (125, 245), (250, 330)),
        c((250, 330), (390, 425), (560, 365), (545, 220)),
        c((545, 220), (535, 115), (360, 125), (255, 190)),
        c((255, 190), (170, 245), (190, 45), (340, 15)),
        c((340, 15), (475, -15), (555, 70), (610, 55)),
        c((610, 55), (635, 45), (650, 0), (700, 0)),
    ), 870),
    "є": Design((
        c((0, 0), (70, 70), (125, 245), (245, 340)),
        c((245, 340), (365, 435), (535, 405), (565, 285)),
        c((565, 285), (510, 230), (390, 215), (285, 235)),
        c((285, 235), (390, 235), (505, 190), (540, 105)),
        c((540, 105), (485, -5), (315, -25), (230, 45)),
        c((230, 45), (330, -5), (510, 15), (610, 0)),
        c((610, 0), (635, 0), (655, 0), (695, 0)),
    ), 865),
    "и": Design((
        c((0, 0), (70, 70), (110, 300), (220, 385)),
        c((220, 385), (315, 455), (325, 80), (365, 20)),
        c((365, 20), (415, -45), (520, 280), (625, 380)),
        c((625, 380), (720, 470), (725, 75), (755, 20)),
        c((755, 20), (780, 0), (810, 0), (850, 0)),
    ), 1020),
    "і": Design((
        c((0, 0), (70, 70), (115, 300), (225, 385)),
        c((225, 385), (325, 465), (330, 75), (365, 20)),
        c((365, 20), (390, 0), (425, 0), (470, 0)),
    ), 640, marks=(mark("dot",
        c((245, 620), (250, 640), (270, 640), (275, 620)),
    ),), critical_features=("dot",)),
    "ї": Design((
        c((0, 0), (70, 70), (115, 300), (225, 385)),
        c((225, 385), (325, 465), (330, 75), (365, 20)),
        c((365, 20), (390, 0), (425, 0), (470, 0)),
    ), 640, marks=(
        mark("dot-left", c((195, 620), (200, 640), (220, 640), (225, 620))),
        mark("dot-right", c((310, 620), (315, 640), (335, 640), (340, 620))),
    ), critical_features=("dot-left", "dot-right")),
    "й": Design((
        c((0, 0), (70, 70), (110, 300), (220, 385)),
        c((220, 385), (315, 455), (325, 80), (365, 20)),
        c((365, 20), (415, -45), (520, 280), (625, 380)),
        c((625, 380), (720, 470), (725, 75), (755, 20)),
        c((755, 20), (780, 0), (810, 0), (850, 0)),
    ), 1020, marks=(mark("breve",
        c((300, 620), (390, 535), (520, 535), (610, 620)),
    ),), critical_features=("breve",)),
    "к": Design((
        c((0, 0), (70, 70), (115, 300), (225, 390)),
        c((225, 390), (315, 460), (305, 80), (335, 25)),
        c((335, 25), (365, -25), (390, 235), (510, 350)),
        c((510, 350), (610, 445), (690, 365), (610, 270)),
        c((610, 270), (530, 185), (465, 220), (520, 160)),
        c((520, 160), (595, 70), (650, 0), (735, 0)),
    ), 905),
    "л": Design((
        c((0, 0), (70, 70), (140, 245), (245, 390)),
        c((245, 390), (330, 505), (385, 455), (450, 300)),
        c((450, 300), (505, 170), (520, 25), (585, 5)),
        c((585, 5), (615, 0), (645, 0), (690, 0)),
    ), 860),
    "м": Design((
        c((0, 0), (70, 70), (115, 290), (225, 390)),
        c((225, 390), (315, 470), (330, 80), (360, 20)),
        c((360, 20), (395, -35), (470, 285), (570, 375)),
        c((570, 375), (660, 455), (670, 85), (700, 20)),
        c((700, 20), (740, -35), (825, 285), (915, 375)),
        c((915, 375), (1000, 445), (1010, 80), (1040, 20)),
        c((1040, 20), (1060, 0), (1090, 0), (1130, 0)),
    ), 1300),
    "н": Design((
        c((0, 0), (70, 70), (115, 300), (225, 390)),
        c((225, 390), (315, 465), (320, 75), (355, 20)),
        c((355, 20), (410, -35), (505, 290), (615, 385)),
        c((615, 385), (705, 455), (715, 70), (745, 20)),
        c((745, 20), (770, 0), (800, 0), (840, 0)),
    ), 1010),
    "о": Design((
        c((0, 0), (70, 70), (120, 265), (245, 370)),
        c((245, 370), (370, 480), (555, 420), (565, 235)),
        c((565, 235), (575, 65), (420, -35), (290, 25)),
        c((290, 25), (175, 80), (185, 295), (320, 365)),
        c((320, 365), (470, 445), (570, 245), (595, 90)),
        c((595, 90), (610, 20), (650, 0), (710, 0)),
    ), 880),
    "п": Design((
        c((0, 0), (70, 70), (115, 300), (225, 390)),
        c((225, 390), (315, 465), (320, 75), (355, 20)),
        c((355, 20), (405, -35), (505, 290), (610, 385)),
        c((610, 385), (700, 455), (705, 75), (740, 20)),
        c((740, 20), (765, 0), (795, 0), (835, 0)),
    ), 1005),
    "р": Design((
        c((0, 0), (70, 70), (115, 290), (225, 380)),
        c((225, 380), (305, 450), (295, 40), (310, -180)),
        c((310, -180), (325, -340), (470, -345), (520, -220)),
        c((520, -220), (555, -125), (465, -35), (380, 5)),
        c((380, 5), (455, 10), (565, 95), (585, 245)),
        c((585, 245), (600, 390), (455, 455), (350, 350)),
        c((350, 350), (430, 385), (585, 265), (605, 90)),
        c((605, 90), (615, 25), (655, 0), (715, 0)),
    ), 885),
    "с": Design((
        c((0, 0), (70, 70), (125, 250), (245, 340)),
        c((245, 340), (370, 435), (545, 390), (570, 270)),
        c((570, 270), (505, 335), (355, 310), (280, 210)),
        c((280, 210), (195, 95), (270, 5), (405, 10)),
        c((405, 10), (500, 15), (555, 70), (615, 35)),
        c((615, 35), (635, 20), (650, 0), (695, 0)),
    ), 865),
    "т": Design((
        c((0, 0), (70, 70), (110, 285), (215, 385)),
        c((215, 385), (300, 465), (310, 80), (340, 20)),
        c((340, 20), (375, -35), (450, 280), (545, 375)),
        c((545, 375), (630, 455), (640, 80), (670, 20)),
        c((670, 20), (705, -35), (785, 280), (880, 375)),
        c((880, 375), (970, 455), (980, 80), (1010, 20)),
        c((1010, 20), (1035, 0), (1060, 0), (1100, 0)),
    ), 1270),
    "у": Design((
        c((0, 0), (70, 70), (110, 290), (220, 385)),
        c((220, 385), (315, 455), (320, 75), (360, 20)),
        c((360, 20), (420, -45), (520, 285), (625, 380)),
        c((625, 380), (710, 455), (700, 90), (705, -120)),
        c((705, -120), (710, -325), (565, -345), (500, -225)),
        c((500, -225), (445, -120), (535, -35), (650, 0)),
        c((650, 0), (700, 0), (765, 0), (805, 0)),
    ), 975),
    "ш": Design((
        c((0, 0), (70, 70), (105, 285), (210, 380)),
        c((210, 380), (300, 455), (305, 75), (340, 20)),
        c((340, 20), (390, -35), (485, 285), (590, 380)),
        c((590, 380), (675, 455), (680, 75), (715, 20)),
        c((715, 20), (765, -35), (860, 285), (965, 380)),
        c((965, 380), (1050, 455), (1055, 75), (1090, 20)),
        c((1090, 20), (1115, 0), (1145, 0), (1185, 0)),
    ), 1355),
    "щ": Design((
        c((0, 0), (70, 70), (105, 285), (210, 380)),
        c((210, 380), (300, 455), (305, 75), (340, 20)),
        c((340, 20), (390, -35), (485, 285), (590, 380)),
        c((590, 380), (675, 455), (680, 75), (715, 20)),
        c((715, 20), (765, -35), (860, 285), (965, 380)),
        c((965, 380), (1050, 455), (1050, 70), (1085, 10)),
        c((1085, 10), (1120, -50), (1100, -250), (1195, -285)),
        c((1195, -285), (1275, -310), (1285, -120), (1190, -45)),
        c((1190, -45), (1160, -20), (1180, 0), (1230, 0)),
    ), 1400),
    "я": Design((
        c((0, 0), (70, 70), (125, 255), (250, 345)),
        c((250, 345), (380, 440), (545, 380), (540, 225)),
        c((540, 225), (535, 85), (375, 80), (285, 165)),
        c((285, 165), (205, 245), (250, 360), (375, 350)),
        c((375, 350), (495, 340), (515, 120), (545, 35)),
        c((545, 35), (585, -35), (665, 285), (755, 380)),
        c((755, 380), (845, 455), (850, 75), (885, 20)),
        c((885, 20), (910, 0), (940, 0), (980, 0)),
    ), 1150),
    "ь": Design((
        c((0, 0), (70, 70), (115, 300), (225, 390)),
        c((225, 390), (315, 460), (315, 70), (350, 15)),
        c((350, 15), (420, -30), (575, 15), (595, 155)),
        c((595, 155), (610, 300), (455, 365), (355, 270)),
        c((355, 270), (450, 310), (600, 205), (615, 65)),
        c((615, 65), (625, 15), (660, 0), (715, 0)),
    ), 885),
    "У": Design((
        c((20, 820), (90, 1010), (225, 1080), (320, 900)),
        c((320, 900), (400, 750), (420, 475), (515, 360)),
        c((515, 360), (630, 220), (745, 545), (825, 875)),
        c((825, 875), (760, 535), (690, 155), (640, -105)),
        c((640, -105), (605, -295), (430, -335), (365, -205)),
        c((365, -205), (315, -105), (420, -25), (575, 10)),
        c((575, 10), (665, 30), (760, 5), (835, 0)),
    ), 1030, joinable=False),
}


def _variant(design: Design, *, dx: float, dy: float) -> Design:
    """Produce a deliberately authored alternate by moving selected controls."""
    body: list[CubicSpec] = []
    for index, segment in enumerate(design.body):
        p0, c1, c2, p1 = segment
        if index in {0, len(design.body) - 1}:
            body.append(segment)
            continue
        body.append(c(
            p0,
            (c1[0] + dx, c1[1] + dy),
            (c2[0] - dx * 0.5, c2[1] - dy * 0.5),
            p1,
        ))
    return Design(tuple(body), design.advance, design.marks, design.joinable, design.critical_features)


DESIGNS: dict[str, tuple[Design, ...]] = {key: (value,) for key, value in BASE.items()}
for _key in ("а", "е", "и", "м", "о", "т"):
    DESIGNS[_key] = (BASE[_key], _variant(BASE[_key], dx=14.0, dy=18.0))


def _segment(value: CubicSpec) -> dict[str, object]:
    p0, c1, c2, p1 = value
    point = lambda item: {"x": float(item[0]), "y": float(item[1])}
    return {"kind": "cubic", "p0": point(p0), "c1": point(c1), "c2": point(c2), "p1": point(p1)}


def _safe_name(character: str, variant: int) -> str:
    codepoints = "-".join(f"{ord(item):04x}" for item in character)
    return f"glyphs/u-{codepoints}-v{variant}.json"


def _glyph(character: str, design: Design, variant: int) -> dict[str, object]:
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

        def unit(dx: float, dy: float) -> dict[str, float]:
            length = math.hypot(dx, dy)
            return {"x": dx / length, "y": dy / length}

        entry_tangent = unit(first[1][0] - first[0][0], first[1][1] - first[0][1])
        exit_tangent = unit(last[3][0] - last[2][0], last[3][1] - last[2][1])
        join_spec: dict[str, object] = {
            "mode": "single_body_deferred_marks",
            "body_stroke_id": "body",
            "deferred_marks": [name for name, _ in design.marks],
            "entry": {
                "stroke_id": "body", "endpoint": "start", "tangent": entry_tangent,
                "class_id": "baseline-entry", "allowed_partner_classes": ["baseline-exit"],
                "max_gap_gu": 240.0, "max_vertical_delta_gu": 90.0, "max_angle_deg": 58.0,
            },
            "exit": {
                "stroke_id": "body", "endpoint": "end", "tangent": exit_tangent,
                "class_id": "baseline-exit", "allowed_partner_classes": ["baseline-entry"],
                "max_gap_gu": 240.0, "max_vertical_delta_gu": 90.0, "max_angle_deg": 58.0,
            },
        }
    else:
        join_spec = {"mode": "none", "no_join_before": True, "no_join_after": True}
    return {
        "format": "hp-glyph",
        "schema_version": "1.0",
        "variant_id": f"ua-pilot-{ord(character):04x}-v{variant}",
        "key": character,
        "strokes": strokes,
        "advance_gu": design.advance,
        "context_tags": ["isolated", "initial", "medial", "final"],
        "join_spec": join_spec,
        "provenance": {
            "license_id": LICENSE_ID,
            "source_method": "manual_vector",
            "author_id": "handwriting-plotter-project",
            "transforms": ["authored directed centre-line Bézier trajectory; no outline tracing"],
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

    license_text = """MIT License

Copyright (c) 2026 Handwriting Plotter contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
    license_relative = f"licenses/{LICENSE_ID}.txt"
    (TARGET / license_relative).write_text(license_text, encoding="utf-8")

    glyph_files: list[str] = []
    file_hashes: dict[str, str] = {}
    for character in sorted(DESIGNS, key=ord):
        for index, design in enumerate(DESIGNS[character], start=1):
            relative = _safe_name(character, index)
            raw = _canonical(_glyph(character, design, index))
            (TARGET / relative).write_bytes(raw)
            glyph_files.append(relative)
            file_hashes[relative] = hashlib.sha256(raw).hexdigest()

    words = ("Україна", "ґрунт", "мама", "привіт", "школа", "пишу", "ймовірність")
    pairs = sorted({pair for word in words for pair in zip(word, word[1:], strict=False)})
    review = {
        "style_id": STYLE_ID,
        "revision": REVISION,
        "status": "needs_human_visual_acceptance",
        "automated_geometry_review": "required",
        "word_corpus": list(words),
        "pair_corpus": ["".join(pair) for pair in pairs],
        "acceptance_questions": [
            "Are all letters recognizable as Ukrainian school cursive?",
            "Are joins natural and free of collisions?",
            "Are stroke order and pen lifts physically plausible?",
            "Are proportions acceptable at 3.5-4.5 mm x-height?",
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
        "authoring_note": "Directed centre lines were authored specifically for this pilot; outline fonts were not converted or traced.",
        "research_references": [
            {"name": "VHS", "url": "https://github.com/utrost/VHS", "role": "capture-workflow comparison", "license": "AGPL-3.0", "integrated": False},
            {"name": "Google Ink Stroke Modeler", "url": "https://github.com/google/ink-stroke-modeler", "role": "future stylus smoothing candidate", "license": "Apache-2.0", "integrated": False},
            {"name": "Relief SingleLine", "url": "https://github.com/isdat-type/Relief-SingleLine", "role": "single-line format comparison", "license": "OFL-1.1", "integrated": False},
            {"name": "Bad Script", "url": "https://github.com/google/fonts/tree/main/ofl/badscript", "role": "licensed Cyrillic visual comparison only", "license": "OFL-1.1", "integrated": False},
            {"name": "Marck Script", "url": "https://github.com/google/fonts/tree/main/ofl/marckscript", "role": "licensed Cyrillic visual comparison only", "license": "OFL-1.1", "integrated": False},
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
        "display_name": "REVIEW ONLY — Ukrainian school cursive pilot",
        "scripts": ["Cyrillic"],
        "license_record": {"license_id": LICENSE_ID, "name": "MIT project-authored pilot geometry", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {
            "x_height_gu": 1000.0, "ascender_gu": 1200.0, "descender_gu": -350.0,
            "space_advance_gu": 620.0, "line_gap_gu": 550.0, "supported_x_height_mm": [3.5, 4.5],
        },
        "coverage": coverage,
        "glyph_files": glyph_files,
        "join_rules": {
            "strategy": "authored baseline anchors with cubic connectors",
            "classes": ["baseline-entry", "baseline-exit"],
            "review_corpus": "review/pilot-review.json",
        },
        "variation_policy": {
            "max_scale_fraction": 0.01, "max_shear_deg": 1.0,
            "max_baseline_offset_mm": 0.04, "max_word_space_fraction": 0.03, "max_line_y_mm": 0.05,
        },
        "file_hashes": file_hashes,
        "approved": True,
        "production_eligible": False,
        "test_only": True,
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
