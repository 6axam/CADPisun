from __future__ import annotations

import cv2
import numpy as np
import pytest

from handwriting_plotter.adapters.images.opencv import OpenCvLineSegmenter
from handwriting_plotter.learning import manual_line_region


def _mask() -> bytes:
    value = np.zeros((160, 300), dtype=np.uint8)
    cv2.line(value, (30, 35), (220, 35), 255, 4)
    cv2.line(value, (50, 100), (260, 100), 255, 5)
    ok, encoded = cv2.imencode(".png", value)
    assert ok
    return encoded.tobytes()


def test_segmenter_orders_two_lines_and_provides_baselines() -> None:
    regions = OpenCvLineSegmenter().segment(_mask(), frame_id="source-pixels")
    assert [region.region_id for region in regions] == ["line-0001", "line-0002"]
    assert all(region.baseline is not None for region in regions)
    assert regions[0].baseline[0].y < regions[1].baseline[0].y


def test_manual_line_fallback_validates_bounds() -> None:
    region = manual_line_region(
        frame_id="source-pixels", region_id="line-manual", left=2, top=3, right=40, bottom=20
    )
    assert region.confidence is not None and region.confidence.origin == "human"
    with pytest.raises(ValueError, match="INVALID_MANUAL_LINE_BOUNDS"):
        manual_line_region(frame_id="source-pixels", region_id="bad", left=2, top=3, right=2, bottom=20)
