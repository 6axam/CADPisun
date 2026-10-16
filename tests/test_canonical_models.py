from __future__ import annotations

import json
import os
import subprocess
import sys


def test_frozenset_json_is_stable_across_python_hash_seeds() -> None:
    script = r'''
from handwriting_plotter.capture.annotation import GlyphAnnotation, StrokeRoleAssignment
from handwriting_plotter.domain.models import canonical_json_bytes

value = GlyphAnnotation(
    source_normalized_sha256="0" * 64,
    source_processed_sha256="1" * 64,
    variant_id="stable",
    label="м",
    context_tags=frozenset({"isolated", "initial", "medial", "final"}),
    stroke_order=("body",),
    stroke_roles=(StrokeRoleAssignment(stroke_id="body", role="body"),),
    join_mode="none",
)
print(canonical_json_bytes(value.model_dump(mode="json")).decode("utf-8"))
'''
    outputs = []
    for seed in ("1", "8675309"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(result.stdout.strip())

    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["context_tags"] == ["final", "initial", "isolated", "medial"]
