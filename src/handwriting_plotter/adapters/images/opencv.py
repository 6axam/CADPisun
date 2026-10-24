"""Optional OpenCV adapter for bounded planar page proposal and rectification."""

from __future__ import annotations

import math

from handwriting_plotter.learning import (
    ConfidenceValue,
    CorrectedRaster,
    PageCorrectionProposal,
    PageCorners,
    PixelPoint,
    RulingEstimate,
    map_point,
    order_page_corners,
    validate_corners_in_frame,
)
from handwriting_plotter.learning.repository import MAX_PHOTO_DIMENSION, MAX_PHOTO_PIXELS


def _cv_modules():
    try:
        import cv2
        import numpy
    except ImportError as exc:
        raise RuntimeError("PHOTO_CV_EXTRA_REQUIRED") from exc
    return cv2, numpy


def opencv_available() -> bool:
    try:
        _cv_modules()
    except RuntimeError:
        return False
    return True


class OpenCvPageCorrector:
    """Detect a planar page quadrilateral and produce an immutable PNG warp."""

    MIN_PAGE_AREA_RATIO = 0.18

    def propose(
        self, content: bytes, *, orientation: str, source_frame_id: str
    ) -> PageCorrectionProposal:
        cv2, np = _cv_modules()
        source = self._decode(content)
        oriented, _ = self._apply_orientation(source, orientation)
        height, width = oriented.shape[:2]
        longest = max(width, height)
        scale = min(1.0, 1600.0 / longest)
        working = (
            oriented
            if scale == 1.0
            else cv2.resize(oriented, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        )
        gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        median = float(np.median(blur))
        lower = int(max(0.0, 0.66 * median))
        upper = int(min(255.0, max(lower + 1, 1.33 * median)))
        edges = cv2.Canny(blur, lower, upper)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        image_area = float(working.shape[0] * working.shape[1])
        candidates: list[tuple[float, object]] = []
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            area_ratio = abs(cv2.contourArea(polygon)) / image_area
            if area_ratio < self.MIN_PAGE_AREA_RATIO:
                continue
            rectangularity = abs(cv2.contourArea(polygon)) / max(
                1.0, float(cv2.minAreaRect(polygon)[1][0] * cv2.minAreaRect(polygon)[1][1])
            )
            score = area_ratio * min(1.0, rectangularity)
            candidates.append((score, polygon))
        if not candidates:
            return PageCorrectionProposal(
                status="not_found",
                method="opencv-contour-quad/1",
                diagnostics=("NO_PAGE_QUADRILATERAL", "PLANAR_MODEL_ONLY"),
            )
        score, polygon = max(candidates, key=lambda item: item[0])
        raw_points = tuple(
            PixelPoint(x=float(point[0][0] / scale), y=float(point[0][1] / scale))
            for point in polygon
        )
        corners = order_page_corners(raw_points, frame_id=source_frame_id)
        validate_corners_in_frame(corners, width, height)
        confidence_value = max(0.0, min(0.99, 0.35 + score * 0.65))
        return PageCorrectionProposal(
            status="proposed",
            method="opencv-contour-quad/1",
            corners=corners,
            confidence=ConfidenceValue(
                value=confidence_value,
                origin="heuristic",
                meaning="page quadrilateral area and rectangularity score",
            ),
            diagnostics=("AUTOMATIC_PROPOSAL_REQUIRES_REVIEW", "PLANAR_MODEL_ONLY"),
        )

    def correct(
        self,
        content: bytes,
        corners: PageCorners,
        *,
        orientation: str,
        deskew_degrees: float = 0.0,
    ) -> CorrectedRaster:
        cv2, np = _cv_modules()
        if not math.isfinite(deskew_degrees) or abs(deskew_degrees) > 15.0:
            raise ValueError("DESKEW_ANGLE_OUT_OF_RANGE")
        source = self._decode(content)
        oriented, orientation_matrix = self._apply_orientation(source, orientation)
        height, width = oriented.shape[:2]
        validate_corners_in_frame(corners, width, height)
        points = corners.points
        output_width = max(
            2,
            int(round(max(self._distance(points[0], points[1]), self._distance(points[3], points[2])))) + 1,
        )
        output_height = max(
            2,
            int(round(max(self._distance(points[0], points[3]), self._distance(points[1], points[2])))) + 1,
        )
        self._validate_output_size(output_width, output_height)
        source_points = np.float32([(point.x, point.y) for point in points])
        target_points = np.float32(
            [(0, 0), (output_width - 1, 0), (output_width - 1, output_height - 1), (0, output_height - 1)]
        )
        homography = cv2.getPerspectiveTransform(source_points, target_points).astype(np.float64)
        deskew = np.eye(3, dtype=np.float64)
        if abs(deskew_degrees) > 1e-12:
            rotation = cv2.getRotationMatrix2D(
                ((output_width - 1) / 2.0, (output_height - 1) / 2.0),
                deskew_degrees,
                1.0,
            )
            deskew[:2, :] = rotation
        total = deskew @ homography @ orientation_matrix
        corrected = cv2.warpPerspective(
            source,
            total,
            (output_width, output_height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        ok, encoded = cv2.imencode(".png", corrected, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        if not ok:
            raise ValueError("CORRECTED_PHOTO_ENCODE_FAILED")
        inverse = np.linalg.inv(total)
        orientation_inverse = np.linalg.inv(orientation_matrix)
        source_corners = order_page_corners(
            tuple(map_point(self._matrix_tuple(orientation_inverse), point) for point in points),
            frame_id="source-pixels",
        )
        return CorrectedRaster(
            content=encoded.tobytes(),
            width_px=output_width,
            height_px=output_height,
            forward_matrix=self._matrix_tuple(total),
            inverse_matrix=self._matrix_tuple(inverse),
            source_corners=source_corners,
            algorithm_id=f"opencv-planar-page/{cv2.__version__}",
            parameters={
                "orientation": orientation,
                "deskew_degrees": deskew_degrees,
                "oriented_corners": [point.model_dump(mode="json") for point in points],
                "output_width_px": output_width,
                "output_height_px": output_height,
                "interpolation": "cubic",
                "border_mode": "replicate",
            },
        )

    @staticmethod
    def _decode(content: bytes):
        cv2, np = _cv_modules()
        if not content:
            raise ValueError("EMPTY_PHOTO_FILE")
        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError("INVALID_PHOTO_IMAGE")
        return image

    @staticmethod
    def _apply_orientation(image, orientation: str):
        cv2, np = _cv_modules()
        height, width = image.shape[:2]
        matrices = {
            "none": np.array(((1, 0, 0), (0, 1, 0), (0, 0, 1)), dtype=np.float64),
            "mirror_horizontal": np.array(((-1, 0, width - 1), (0, 1, 0), (0, 0, 1)), dtype=np.float64),
            "flip_vertical": np.array(((1, 0, 0), (0, -1, height - 1), (0, 0, 1)), dtype=np.float64),
            "rotate_180": np.array(((-1, 0, width - 1), (0, -1, height - 1), (0, 0, 1)), dtype=np.float64),
            "rotate_90": np.array(((0, -1, height - 1), (1, 0, 0), (0, 0, 1)), dtype=np.float64),
            "mirror_horizontal_rotate_90": np.array(((0, 1, 0), (1, 0, 0), (0, 0, 1)), dtype=np.float64),
            "flip_vertical_rotate_90": np.array(((0, -1, height - 1), (-1, 0, width - 1), (0, 0, 1)), dtype=np.float64),
            "rotate_270": np.array(((0, 1, 0), (-1, 0, width - 1), (0, 0, 1)), dtype=np.float64),
        }
        matrix = matrices.get(orientation)
        if matrix is None:
            raise ValueError("UNSUPPORTED_PHOTO_ORIENTATION")
        operations = {
            "none": lambda value: value,
            "mirror_horizontal": lambda value: cv2.flip(value, 1),
            "flip_vertical": lambda value: cv2.flip(value, 0),
            "rotate_180": lambda value: cv2.rotate(value, cv2.ROTATE_180),
            "rotate_90": lambda value: cv2.rotate(value, cv2.ROTATE_90_CLOCKWISE),
            "mirror_horizontal_rotate_90": cv2.transpose,
            "flip_vertical_rotate_90": lambda value: cv2.flip(cv2.transpose(value), -1),
            "rotate_270": lambda value: cv2.rotate(value, cv2.ROTATE_90_COUNTERCLOCKWISE),
        }
        return operations[orientation](image), matrix

    @staticmethod
    def _distance(left: PixelPoint, right: PixelPoint) -> float:
        return math.hypot(right.x - left.x, right.y - left.y)

    @staticmethod
    def _matrix_tuple(matrix) -> tuple[float, float, float, float, float, float, float, float, float]:
        flat = [float(value) for value in matrix.reshape(9)]
        scale = flat[8]
        if abs(scale) < 1e-12:
            raise ValueError("TRANSFORM_MATRIX_NOT_INVERTIBLE")
        return tuple(value / scale for value in flat)  # type: ignore[return-value]

    @staticmethod
    def _validate_output_size(width: int, height: int) -> None:
        if width > MAX_PHOTO_DIMENSION or height > MAX_PHOTO_DIMENSION:
            raise ValueError("PHOTO_DIMENSION_LIMIT_EXCEEDED")
        if width * height > MAX_PHOTO_PIXELS:
            raise ValueError("PHOTO_PIXEL_LIMIT_EXCEEDED")


class OpenCvRulingClassifier:
    """Classify paper from repeated long horizontal and vertical line evidence."""

    MIN_REPEATED_LINES = 3
    LINE_SPAN_RATIO = 0.18

    def classify(self, content: bytes, *, frame_id: str) -> RulingEstimate:
        cv2, np = _cv_modules()
        image = OpenCvPageCorrector._decode(content)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, ink = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        dark_ratio = float(np.count_nonzero(ink)) / ink.size
        height, width = ink.shape
        horizontal = cv2.morphologyEx(
            ink,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 10), 1)),
        )
        vertical = cv2.morphologyEx(
            ink,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(24, height // 10))),
        )
        horizontal_count, horizontal_strength = self._line_evidence(
            horizontal, axis=1, span=width
        )
        vertical_count, vertical_strength = self._line_evidence(
            vertical, axis=0, span=height
        )
        horizontal_repeated = horizontal_count >= self.MIN_REPEATED_LINES
        vertical_repeated = vertical_count >= self.MIN_REPEATED_LINES

        if horizontal_repeated and vertical_repeated:
            classification = "squared"
            signal = min(horizontal_strength, vertical_strength)
            confidence = min(0.95, 0.55 + signal * 0.45)
        elif horizontal_repeated and not vertical_repeated:
            classification = "ruled"
            confidence = min(0.95, 0.55 + horizontal_strength * 0.45)
        elif dark_ratio < 0.004:
            classification = "blank"
            confidence = min(0.95, 0.75 + (0.004 - dark_ratio) * 50.0)
        elif dark_ratio >= 0.04 or horizontal_count > 0 or vertical_count > 0:
            classification = "mixed"
            confidence = min(0.75, 0.35 + min(0.4, dark_ratio) + 0.05 * (horizontal_count + vertical_count))
        else:
            classification = "unknown"
            confidence = 0.2
        return RulingEstimate(
            frame_id=frame_id,
            classification=classification,
            status="proposed",
            method="opencv-ruling-classifier/1",
            confidence=ConfidenceValue(
                value=confidence,
                origin="heuristic",
                meaning=(
                    "repeated long horizontal and vertical line evidence; "
                    f"horizontal_runs={horizontal_count}, vertical_runs={vertical_count}, "
                    f"dark_ratio={dark_ratio:.6f}"
                ),
            ),
        )

    @classmethod
    def _line_evidence(cls, mask, *, axis: int, span: int) -> tuple[int, float]:
        _, np = _cv_modules()
        ratios = np.count_nonzero(mask, axis=axis) / max(1, span)
        active = ratios >= cls.LINE_SPAN_RATIO
        count = 0
        strengths: list[float] = []
        index = 0
        while index < len(active):
            if not active[index]:
                index += 1
                continue
            end = index + 1
            while end < len(active) and active[end]:
                end += 1
            strengths.append(float(np.max(ratios[index:end])))
            count += 1
            index = end
        return count, (sum(strengths) / len(strengths) if strengths else 0.0)
