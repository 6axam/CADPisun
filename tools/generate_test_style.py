"""Build the explicitly non-product technical single-line fixture style.

The generated glyphs are small-cap engineering strokes for pipeline testing.
They are not Ukrainian school cursive and must never be renamed or published as
``ua-school-v1``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).parents[1]
TARGET = ROOT / "assets" / "styles" / "test-technical-v1" / "1.0.0"

Point = tuple[float, float]
Glyph = tuple[list[Point], ...]


def p(*strokes: list[Point]) -> Glyph:
    return tuple(strokes)


CAPS: dict[str, Glyph] = {
    "A": p([(0, 0), (300, 1000), (600, 0)], [(130, 430), (470, 430)]),
    "B": p([(0, 0), (0, 1000), (380, 1000), (560, 850), (560, 650), (380, 520), (0, 520)], [(380, 520), (590, 380), (590, 150), (400, 0), (0, 0)]),
    "C": p([(580, 850), (430, 1000), (160, 1000), (0, 800), (0, 200), (160, 0), (430, 0), (580, 150)]),
    "D": p([(0, 0), (0, 1000), (350, 1000), (580, 780), (580, 220), (350, 0), (0, 0)]),
    "E": p([(580, 1000), (0, 1000), (0, 0), (580, 0)], [(0, 500), (440, 500)]),
    "F": p([(0, 0), (0, 1000), (580, 1000)], [(0, 500), (440, 500)]),
    "G": p([(580, 820), (430, 1000), (160, 1000), (0, 800), (0, 200), (160, 0), (450, 0), (590, 180), (590, 480), (350, 480)]),
    "H": p([(0, 0), (0, 1000)], [(600, 0), (600, 1000)], [(0, 500), (600, 500)]),
    "I": p([(300, 0), (300, 1000)], [(80, 1000), (520, 1000)], [(80, 0), (520, 0)]),
    "J": p([(80, 200), (180, 0), (420, 0), (520, 150), (520, 1000)], [(300, 1000), (600, 1000)]),
    "K": p([(0, 0), (0, 1000)], [(600, 1000), (0, 420), (600, 0)]),
    "L": p([(0, 1000), (0, 0), (600, 0)]),
    "M": p([(0, 0), (0, 1000), (300, 450), (600, 1000), (600, 0)]),
    "N": p([(0, 0), (0, 1000), (600, 0), (600, 1000)]),
    "O": p([(150, 0), (0, 180), (0, 820), (150, 1000), (450, 1000), (600, 820), (600, 180), (450, 0), (150, 0)]),
    "P": p([(0, 0), (0, 1000), (400, 1000), (580, 830), (580, 650), (400, 500), (0, 500)]),
    "Q": p([(150, 0), (0, 180), (0, 820), (150, 1000), (450, 1000), (600, 820), (600, 180), (450, 0), (150, 0)], [(360, 250), (650, -100)]),
    "R": p([(0, 0), (0, 1000), (400, 1000), (580, 830), (580, 650), (400, 500), (0, 500)], [(330, 500), (620, 0)]),
    "S": p([(580, 850), (430, 1000), (150, 1000), (0, 820), (0, 620), (160, 500), (430, 500), (590, 360), (590, 170), (430, 0), (140, 0), (0, 150)]),
    "T": p([(0, 1000), (600, 1000)], [(300, 1000), (300, 0)]),
    "U": p([(0, 1000), (0, 180), (150, 0), (450, 0), (600, 180), (600, 1000)]),
    "V": p([(0, 1000), (300, 0), (600, 1000)]),
    "W": p([(0, 1000), (130, 0), (300, 550), (470, 0), (600, 1000)]),
    "X": p([(0, 1000), (600, 0)], [(600, 1000), (0, 0)]),
    "Y": p([(0, 1000), (300, 500), (600, 1000)], [(300, 500), (300, 0)]),
    "Z": p([(0, 1000), (600, 1000), (0, 0), (600, 0)]),
}


CYR: dict[str, Glyph] = {
    "А": CAPS["A"], "В": CAPS["B"], "Е": CAPS["E"], "К": CAPS["K"], "М": CAPS["M"],
    "Н": CAPS["H"], "О": CAPS["O"], "Р": CAPS["P"], "С": CAPS["C"], "Т": CAPS["T"],
    "У": CAPS["Y"], "Х": CAPS["X"],
    "Б": p([(0, 0), (0, 1000), (570, 1000)], [(0, 520), (400, 520), (580, 350), (580, 170), (400, 0), (0, 0)]),
    "Г": p([(0, 0), (0, 1000), (600, 1000)]),
    "Ґ": p([(0, 0), (0, 1000), (600, 1000), (600, 1150), (500, 1150)]),
    "Д": p([(-50, 0), (80, 0), (190, 1000), (480, 1000), (580, 0), (680, 0)], [(-50, 0), (-50, -180)], [(680, 0), (680, -180)]),
    "Є": p([(580, 850), (430, 1000), (160, 1000), (0, 800), (0, 200), (160, 0), (430, 0), (580, 150)], [(0, 500), (400, 500)]),
    "Ж": p([(0, 1000), (300, 500), (0, 0)], [(300, 0), (300, 1000)], [(600, 1000), (300, 500), (600, 0)]),
    "З": p([(0, 850), (150, 1000), (420, 1000), (580, 830), (580, 650), (420, 500), (230, 500)], [(420, 500), (600, 350), (600, 170), (430, 0), (150, 0), (0, 150)]),
    "И": p([(0, 1000), (0, 0), (600, 1000), (600, 0)]),
    "І": p([(300, 0), (300, 1000)]),
    "Ї": p([(300, 0), (300, 1000)], [(180, 1160), (190, 1170)], [(410, 1160), (420, 1170)]),
    "Й": p([(0, 1000), (0, 0), (600, 1000), (600, 0)], [(180, 1180), (300, 1100), (420, 1180)]),
    "Л": p([(0, 0), (180, 1000), (450, 1000), (600, 0)]),
    "П": p([(0, 0), (0, 1000), (600, 1000), (600, 0)]),
    "Ф": p([(300, -100), (300, 1100)], [(300, 850), (140, 1000), (0, 800), (0, 350), (140, 180), (300, 300), (460, 180), (600, 350), (600, 800), (460, 1000), (300, 850)]),
    "Ц": p([(0, 1000), (0, 0), (520, 0), (520, 1000)], [(520, 0), (650, -180)]),
    "Ч": p([(0, 1000), (0, 600), (180, 450), (600, 600)], [(600, 1000), (600, 0)]),
    "Ш": p([(0, 1000), (0, 0), (300, 0), (300, 1000)], [(300, 0), (600, 0), (600, 1000)]),
    "Щ": p([(0, 1000), (0, 0), (300, 0), (300, 1000)], [(300, 0), (560, 0), (560, 1000)], [(560, 0), (680, -180)]),
    "Ь": p([(0, 1000), (0, 0), (400, 0), (580, 170), (580, 360), (400, 520), (0, 520)]),
    "Ю": p([(0, 0), (0, 1000)], [(0, 500), (150, 500)], [(300, 0), (150, 180), (150, 820), (300, 1000), (500, 1000), (650, 820), (650, 180), (500, 0), (300, 0)]),
    "Я": p([(600, 0), (600, 1000), (200, 1000), (20, 830), (20, 650), (200, 500), (600, 500)], [(250, 500), (0, 0)]),
    "Ё": p(*CAPS["E"], [(170, 1160), (180, 1170)], [(410, 1160), (420, 1170)]),
    "Ъ": p([(0, 1000), (250, 1000), (250, 0), (500, 0), (650, 170), (650, 350), (500, 520), (250, 520)]),
    "Ы": p([(0, 1000), (0, 0), (300, 0), (450, 170), (450, 350), (300, 520), (0, 520)], [(600, 0), (600, 1000)]),
    "Э": p([(0, 850), (150, 1000), (440, 1000), (600, 800), (600, 200), (440, 0), (150, 0), (0, 150)], [(220, 500), (600, 500)]),
}


DIGITS: dict[str, Glyph] = {
    "0": CAPS["O"], "1": p([(180, 800), (300, 1000), (300, 0)], [(120, 0), (480, 0)]),
    "2": p([(0, 800), (150, 1000), (450, 1000), (600, 800), (600, 650), (0, 0), (600, 0)]),
    "3": p([(0, 850), (150, 1000), (450, 1000), (600, 820), (600, 620), (420, 500), (250, 500)], [(420, 500), (600, 350), (600, 170), (450, 0), (150, 0), (0, 150)]),
    "4": p([(500, 0), (500, 1000), (0, 300), (650, 300)]), "5": CAPS["S"],
    "6": p([(560, 850), (420, 1000), (160, 1000), (0, 700), (0, 180), (150, 0), (430, 0), (580, 180), (580, 400), (430, 550), (0, 550)]),
    "7": p([(0, 1000), (600, 1000), (180, 0)]), "8": p([(150, 500), (0, 650), (0, 850), (150, 1000), (450, 1000), (600, 850), (600, 650), (450, 500), (150, 500), (0, 350), (0, 150), (150, 0), (450, 0), (600, 150), (600, 350), (450, 500)]),
    "9": p([(600, 450), (170, 450), (20, 600), (20, 820), (170, 1000), (450, 1000), (600, 820), (600, 300), (440, 0), (160, 0), (20, 150)]),
}


PUNCT: dict[str, Glyph] = {
    ".": p([(280, 0), (300, 20)]), ",": p([(320, 30), (250, -160)]), ":": p([(290, 700), (310, 720)], [(290, 50), (310, 70)]),
    ";": p([(290, 700), (310, 720)], [(320, 50), (250, -160)]), "!": p([(300, 1000), (300, 250)], [(290, 0), (310, 20)]),
    "?": p([(50, 800), (170, 1000), (430, 1000), (550, 820), (550, 650), (300, 450), (300, 250)], [(290, 0), (310, 20)]),
    "-": p([(80, 450), (520, 450)]), "_": p([(0, -100), (600, -100)]), "+": p([(70, 450), (530, 450)], [(300, 180), (300, 720)]),
    "=": p([(80, 600), (520, 600)], [(80, 300), (520, 300)]), "/": p([(0, 0), (600, 1000)]), "\\": p([(0, 1000), (600, 0)]),
    "<": p([(500, 800), (100, 500), (500, 200)]), ">": p([(100, 800), (500, 500), (100, 200)]),
    "(": p([(420, 1100), (220, 850), (140, 500), (220, 150), (420, -100)]), ")": p([(180, 1100), (380, 850), (460, 500), (380, 150), (180, -100)]),
    "[": p([(450, 1100), (180, 1100), (180, -100), (450, -100)]), "]": p([(150, 1100), (420, 1100), (420, -100), (150, -100)]),
    "{": p([(450, 1100), (280, 1000), (280, 650), (150, 500), (280, 350), (280, 0), (450, -100)]),
    "}": p([(150, 1100), (320, 1000), (320, 650), (450, 500), (320, 350), (320, 0), (150, -100)]),
    "'": p([(320, 1050), (250, 820)]), '"': p([(210, 1050), (170, 820)], [(430, 1050), (390, 820)]),
    "`": p([(240, 1050), (360, 900)]), "~": p([(50, 450), (180, 560), (320, 340), (470, 450), (560, 520)]),
    "|": p([(300, -100), (300, 1100)]), "#": p([(180, 0), (260, 1000)], [(380, 0), (460, 1000)], [(40, 650), (560, 650)], [(20, 350), (540, 350)]),
    "$": p(*CAPS["S"], [(300, -120), (300, 1120)]), "%": p([(0, 0), (600, 1000)], [(80, 850), (160, 930)], [(440, 70), (520, 150)]),
    "&": p([(550, 0), (150, 650), (100, 850), (230, 1000), (390, 900), (390, 700), (80, 300), (100, 100), (300, 0), (570, 400)]),
    "*": p([(300, 250), (300, 850)], [(60, 400), (540, 700)], [(60, 700), (540, 400)]),
    "@": p([(520, 180), (440, 0), (150, 0), (0, 180), (0, 780), (150, 1000), (470, 1000), (600, 800), (600, 380), (430, 300), (300, 450), (300, 700), (430, 820), (540, 700)]),
    "^": p([(80, 650), (300, 1000), (520, 650)]),
}


SPECIAL_ALIASES = {"–": "-", "—": "-", "−": "-", "“": '"', "”": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "ʼ": "'", "…": ".", "±": "+", "×": "*", "÷": "/", "≤": "<", "≥": ">", "→": ">", "°": "o", "№": "N", "₴": "S", "€": "E"}


def small_caps(glyph: Glyph) -> Glyph:
    return tuple([(x, y * 0.78) for x, y in stroke] for stroke in glyph)


def glyphs() -> dict[str, Glyph]:
    result: dict[str, Glyph] = {}
    result.update(CAPS)
    result.update({key.lower(): small_caps(value) for key, value in CAPS.items()})
    result.update(CYR)
    result.update({key.lower(): small_caps(value) for key, value in CYR.items()})
    result.update(DIGITS)
    result.update(PUNCT)
    for codepoint in list(range(33, 48)) + list(range(58, 65)) + list(range(91, 97)) + list(range(123, 127)):
        character = chr(codepoint)
        result.setdefault(character, p([(150, 0), (450, 1000)]))
    for character, alias in SPECIAL_ALIASES.items():
        base = result.get(alias) or result.get(alias.upper())
        assert base is not None
        result[character] = base
    return result


def safe_name(character: str) -> str:
    return "u-" + "-".join(f"{ord(item):04x}" for item in character) + ".json"


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    (TARGET / "glyphs").mkdir(parents=True)
    (TARGET / "licenses").mkdir()
    (TARGET / "review").mkdir()
    license_text = (
        "MIT License\n\nCopyright (c) 2026 Handwriting Plotter contributors\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy "
        "of this software and associated documentation files (the \"Software\"), to deal "
        "in the Software without restriction, including without limitation the rights "
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies.\n\n"
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND.\n"
    )
    (TARGET / "licenses" / "fixture-mit.txt").write_text(license_text, encoding="utf-8")
    all_glyphs = glyphs()
    file_hashes: dict[str, str] = {}
    glyph_files: list[str] = []
    for character in sorted(all_glyphs, key=ord):
        strokes = []
        for stroke_index, points in enumerate(all_glyphs[character]):
            segments = [
                {"kind": "line", "p0": {"x": float(a[0]), "y": float(a[1])}, "p1": {"x": float(b[0]), "y": float(b[1])}}
                for a, b in zip(points, points[1:], strict=False)
                if a != b
            ]
            if segments:
                strokes.append({
                    "id": f"stroke-{stroke_index:02d}", "segments": segments, "source_refs": [],
                    "role": "punctuation" if not character.isalnum() else "body", "direction_provenance": "authored",
                })
        data = {
            "format": "hp-glyph", "schema_version": "1.0", "variant_id": f"fixture-{ord(character):04x}-1",
            "key": character, "strokes": strokes, "advance_gu": 700.0,
            "context_tags": ["isolated", "initial", "medial", "final"],
            "join_spec": {"mode": "none"},
            "provenance": {"license_id": "fixture-mit", "source_method": "manual_vector", "author_id": "project-engineering-fixture"},
            "review_status": "approved", "critical_features": [],
        }
        relative = "glyphs/" + safe_name(character)
        raw = (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (TARGET / relative).write_bytes(raw)
        glyph_files.append(relative)
        file_hashes[relative] = hashlib.sha256(raw).hexdigest()
    coverage = sorted(all_glyphs, key=ord)
    coverage_report = {
        "style_id": "test-technical-v1", "revision": "1.0.0", "test_only": True,
        "count": len(coverage), "keys": coverage,
        "warning": "Engineering fixture only; not ua-school-v1 and not cursive-quality reviewed.",
    }
    coverage_raw = (json.dumps(coverage_report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (TARGET / "review" / "coverage.json").write_bytes(coverage_raw)
    file_hashes["review/coverage.json"] = hashlib.sha256(coverage_raw).hexdigest()
    file_hashes["licenses/fixture-mit.txt"] = hashlib.sha256(license_text.encode()).hexdigest()
    manifest = {
        "format": "hp-style", "schema_version": "1.0", "style_id": "test-technical-v1", "revision": "1.0.0",
        "display_name": "TEST ONLY — Technical single-line small caps", "scripts": ["Cyrillic", "Latin", "Common"],
        "license_record": {"license_id": "fixture-mit", "name": "MIT engineering fixture", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1200.0, "descender_gu": -200.0, "space_advance_gu": 500.0, "line_gap_gu": 500.0, "supported_x_height_mm": [2.5, 5.0]},
        "coverage": coverage, "glyph_files": glyph_files, "join_rules": {}, "variation_policy": {}, "file_hashes": file_hashes,
        "approved": True, "production_eligible": False, "test_only": True,
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

