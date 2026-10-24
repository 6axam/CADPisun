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
    InkMaskRaster,
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


class OpenCvRulingGeometryEstimator:
    """Recover periodic line geometry from long Hough segments in one pixel frame."""

    MIN_LINES = 4
    MIN_PITCH_PX = 8.0

    def estimate(
        self,
        content: bytes,
        *,
        frame_id: str,
        classification: str,
    ) -> RulingEstimate:
        if classification not in {"squared", "ruled"}:
            raise ValueError("RULING_GEOMETRY_NOT_APPLICABLE")
        cv2, np = _cv_modules()
        image = OpenCvPageCorrector._decode(content)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 30, 100)
        height, width = gray.shape
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 360.0,
            threshold=max(35, min(width, height) // 10),
            minLineLength=max(36, int(min(width, height) * 0.22)),
            maxLineGap=max(8, min(width, height) // 45),
        )
        horizontal: list[tuple[float, float, float]] = []
        vertical: list[tuple[float, float, float]] = []
        if lines is not None:
            for x1, y1, x2, y2 in lines.reshape(-1, 4):
                dx, dy = float(x2 - x1), float(y2 - y1)
                length = math.hypot(dx, dy)
                if length <= 0.0:
                    continue
                angle = math.degrees(math.atan2(dy, dx))
                horizontal_angle = ((angle + 90.0) % 180.0) - 90.0
                midpoint_x, midpoint_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                if abs(horizontal_angle) <= 25.0 and length >= width * 0.25:
                    horizontal.append((horizontal_angle, midpoint_x, midpoint_y))
                vertical_angle = angle % 180.0
                if 65.0 <= vertical_angle <= 115.0 and length >= height * 0.25:
                    vertical.append((vertical_angle, midpoint_x, midpoint_y))
        horizontal_geometry = self._axis_geometry(horizontal, axis="horizontal")
        if horizontal_geometry is None:
            raise ValueError("HORIZONTAL_RULING_NOT_FOUND")
        vertical_geometry = self._axis_geometry(vertical, axis="vertical")
        if classification == "squared" and vertical_geometry is None:
            raise ValueError("VERTICAL_GRID_NOT_FOUND")

        h_angle, h_pitch, h_origin, h_residual, h_count = horizontal_geometry
        if classification == "ruled":
            confidence = self._confidence(h_count, h_residual, h_pitch)
            return RulingEstimate(
                frame_id=frame_id,
                classification="ruled",
                status="proposed",
                method="opencv-ruling-geometry/1",
                confidence=ConfidenceValue(
                    value=confidence,
                    origin="heuristic",
                    meaning=(
                        "periodic horizontal Hough-line fit; "
                        f"lines={h_count}, residual_px={h_residual:.3f}"
                    ),
                ),
                ruling_pitch_px=h_pitch,
                origin_y_px=h_origin,
                horizontal_angle_deg=h_angle,
                horizontal_residual_px=h_residual,
            )
        assert vertical_geometry is not None
        v_angle, v_pitch, v_origin, v_residual, v_count = vertical_geometry
        confidence = self._confidence(min(h_count, v_count), max(h_residual, v_residual), min(h_pitch, v_pitch))
        return RulingEstimate(
            frame_id=frame_id,
            classification="squared",
            status="proposed",
            method="opencv-ruling-geometry/1",
            confidence=ConfidenceValue(
                value=confidence,
                origin="heuristic",
                meaning=(
                    "periodic horizontal and vertical Hough-line fit; "
                    f"horizontal_lines={h_count}, vertical_lines={v_count}, "
                    f"residual_px={max(h_residual, v_residual):.3f}"
                ),
            ),
            cell_pitch_x_px=v_pitch,
            cell_pitch_y_px=h_pitch,
            origin_x_px=v_origin,
            origin_y_px=h_origin,
            horizontal_angle_deg=h_angle,
            vertical_angle_deg=v_angle,
            horizontal_residual_px=h_residual,
            vertical_residual_px=v_residual,
        )

    @classmethod
    def _axis_geometry(
        cls,
        segments: list[tuple[float, float, float]],
        *,
        axis: str,
    ) -> tuple[float, float, float, float, int] | None:
        _, np = _cv_modules()
        if len(segments) < cls.MIN_LINES:
            return None
        angles = np.asarray([item[0] for item in segments], dtype=np.float64)
        angle = float(np.median(angles))
        radians = math.radians(angle)
        normal = (-math.sin(radians), math.cos(radians)) if axis == "horizontal" else (math.sin(radians), -math.cos(radians))
        coordinates = sorted(
            normal[0] * x + normal[1] * y for _, x, y in segments
        )
        merged: list[list[float]] = []
        for coordinate in coordinates:
            if not merged or coordinate - merged[-1][-1] > 3.0:
                merged.append([coordinate])
            else:
                merged[-1].append(coordinate)
        centers = [float(np.median(group)) for group in merged]
        if len(centers) < cls.MIN_LINES:
            return None
        periodic = cls._periodic_fit(centers)
        if periodic is None:
            return None
        pitch, origin, residual, count = periodic
        return angle, pitch, origin, residual, count

    @classmethod
    def _periodic_fit(
        cls, coordinates: list[float]
    ) -> tuple[float, float, float, int] | None:
        _, np = _cv_modules()
        adjacent = [right - left for left, right in zip(coordinates, coordinates[1:])]
        nominal_gap = float(np.median(adjacent))
        candidates: set[float] = set()
        for start, left in enumerate(coordinates):
            for right in coordinates[start + 1 :]:
                distance = right - left
                for divisor in range(1, min(12, int(distance // cls.MIN_PITCH_PX)) + 1):
                    pitch = distance / divisor
                    if pitch >= cls.MIN_PITCH_PX:
                        candidates.add(round(pitch, 3))
        best: tuple[float, float, float, int] | None = None
        for pitch in sorted(candidates):
            # A harmonic of a true periodic gap fits every line too.  The robust
            # median adjacent gap keeps a 10 px harmonic from replacing 40 px
            # notebook rules while allowing modest occlusion/outliers.
            if pitch < nominal_gap * 0.55 or pitch > nominal_gap * 1.6:
                continue
            for coordinate in coordinates:
                origin = coordinate % pitch
                errors = np.asarray(
                    [abs(value - (origin + round((value - origin) / pitch) * pitch)) for value in coordinates],
                    dtype=np.float64,
                )
                inliers = errors <= max(2.5, pitch * 0.12)
                count = int(np.count_nonzero(inliers))
                if count < cls.MIN_LINES:
                    continue
                residual = float(np.sqrt(np.mean(np.square(errors[inliers]))))
                candidate = (pitch, origin, residual, count)
                if best is None or (count, -residual / pitch, pitch) > (
                    best[3],
                    -best[2] / best[0],
                    best[0],
                ):
                    best = candidate
        return best

    @staticmethod
    def _confidence(count: int, residual: float, pitch: float) -> float:
        support = min(1.0, count / 10.0)
        precision = max(0.0, 1.0 - residual / max(1.0, pitch * 0.15))
        return min(0.95, 0.45 + 0.3 * support + 0.2 * precision)


class OpenCvInkSeparator:
    """Create reviewable raw and conservative cleaned handwriting masks.

    The cleaner removes only pixels near already measured ruling families. Dark
    marks are deliberately protected at intersections; the raw mask remains a
    persisted manual fallback for every colour/lighting condition.
    """

    def separate(self, content: bytes, *, frame_id: str, ruling: RulingEstimate) -> InkMaskRaster:
        cv2, np = _cv_modules()
        image = OpenCvPageCorrector._decode(content)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        background = cv2.GaussianBlur(gray, (0, 0), 19.0)
        contrast = cv2.subtract(background, gray)
        # Raw deliberately retains faint coloured rules for review.  The clean
        # variant may remove them only when the measured periodic geometry says
        # they are a ruling family.
        raw = ((contrast > 10) | (gray < 225)).astype(np.uint8) * 255
        ruling_mask = self._ruling_mask(raw.shape, ruling, np)
        if ruling_mask is None:
            cleaned = raw.copy()
            diagnostics = ("NO_RULING_GEOMETRY_RAW_EQUALS_CLEANED",)
        else:
            # Blue/brown printed lines tend to remain brighter than ink.  Dark
            # black/purple writing is retained even when it crosses a rule.
            protected_ink = (gray < 145) | ((hsv[:, :, 1] > 70) & (hsv[:, :, 2] < 150))
            cleaned = ((raw > 0) & ((ruling_mask == 0) | protected_ink)).astype(np.uint8) * 255
            diagnostics = ("RULING_REMOVAL_CONSERVATIVE", "DARK_INTERSECTIONS_PROTECTED")
        for mask in (raw, cleaned):
            if int(np.count_nonzero(mask)) == 0:
                raise ValueError("INK_MASK_EMPTY")
        raw_ok, raw_png = cv2.imencode(".png", raw, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        clean_ok, clean_png = cv2.imencode(".png", cleaned, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        if not raw_ok or not clean_ok:
            raise ValueError("INK_MASK_ENCODE_FAILED")
        return InkMaskRaster(
            frame_id=frame_id,
            raw_png=raw_png.tobytes(),
            cleaned_png=clean_png.tobytes(),
            method=f"opencv-conservative-ink-mask/{cv2.__version__}",
            diagnostics=diagnostics,
        )

    @staticmethod
    def _ruling_mask(shape, ruling: RulingEstimate, np):
        if ruling.frame_id == "" or ruling.classification not in {"ruled", "squared"}:
            return None
        height, width = shape
        yy, xx = np.indices((height, width), dtype=np.float64)
        result = np.zeros((height, width), dtype=np.uint8)

        def add_family(pitch, origin, angle, *, vertical: bool) -> bool:
            if pitch is None or origin is None or angle is None:
                return False
            radians = math.radians(angle)
            normal = (math.sin(radians), -math.cos(radians)) if vertical else (-math.sin(radians), math.cos(radians))
            coordinate = normal[0] * xx + normal[1] * yy
            distance = np.abs(((coordinate - origin + pitch / 2.0) % pitch) - pitch / 2.0)
            result[distance <= max(1.0, min(2.0, pitch * 0.08))] = 255
            return True

        horizontal = add_family(ruling.ruling_pitch_px or ruling.cell_pitch_y_px, ruling.origin_y_px, ruling.horizontal_angle_deg, vertical=False)
        vertical = add_family(ruling.cell_pitch_x_px, ruling.origin_x_px, ruling.vertical_angle_deg, vertical=True)
        return result if horizontal or vertical else None
