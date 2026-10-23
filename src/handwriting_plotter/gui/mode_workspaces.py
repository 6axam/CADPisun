"""Read-only preview and virtual execution workspaces."""

from __future__ import annotations

import json

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .canvas import PageCanvas


class ArtifactModeWorkspace(QWidget):
    """Inspect generated geometry and play its verified virtual toolpath."""

    def __init__(self, mode: str, parent=None) -> None:  # noqa: ANN001
        if mode not in {"preview", "execution"}:
            raise ValueError("UNKNOWN_ARTIFACT_MODE")
        super().__init__(parent)
        self.mode = mode
        self.setObjectName(f"{mode}-workspace")
        self._positions: list[tuple[QPointF, bool, str]] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.state_label = QLabel()
        self.state_label.setObjectName(f"{mode}-state")
        self.state_label.setStyleSheet(
            "QLabel { background: #20252d; border-bottom: 1px solid #353b46; "
            "padding: 7px 10px; font-weight: 600; }"
        )
        layout.addWidget(self.state_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = PageCanvas()
        self.canvas.setObjectName(f"{mode}-canvas")
        self.canvas.set_interaction_enabled(False)
        splitter.addWidget(self.canvas)

        side = QWidget()
        side.setMinimumWidth(270)
        side_layout = QVBoxLayout(side)
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 15px; font-weight: 650;")
        side_layout.addWidget(self.heading)
        self.gcode = QPlainTextEdit()
        self.gcode.setObjectName(f"{mode}-gcode")
        self.gcode.setReadOnly(True)
        self.gcode.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        side_layout.addWidget(self.gcode, 1)

        controls = QHBoxLayout()
        self.play_button = QPushButton()
        self.play_button.setObjectName(f"{mode}-play")
        self.play_button.clicked.connect(self.toggle_playback)
        self.speed_combo = QComboBox()
        self.speed_combo.setObjectName(f"{mode}-speed")
        self.speed_combo.addItem("0.5×", 0.5)
        self.speed_combo.addItem("1×", 1.0)
        self.speed_combo.addItem("2×", 2.0)
        self.speed_combo.addItem("4×", 4.0)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.currentIndexChanged.connect(self._update_timer_interval)
        controls.addWidget(self.play_button)
        controls.addWidget(self.speed_combo)
        side_layout.addLayout(controls)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setObjectName(f"{mode}-timeline")
        self.timeline.valueChanged.connect(self._show_step)
        side_layout.addWidget(self.timeline)
        self.step_label = QLabel()
        self.step_label.setObjectName(f"{mode}-step")
        self.step_label.setWordWrap(True)
        side_layout.addWidget(self.step_label)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((900, 320))
        layout.addWidget(splitter, 1)
        self.set_language("en")
        self.clear()

    @property
    def has_artifact(self) -> bool:
        return self.canvas.has_artifact

    def set_language(self, language: str) -> None:
        ukrainian = language == "uk"
        self.heading.setText("Віртуальний G-code" if ukrainian else "Virtual G-code")
        if ukrainian:
            self.play_button.setText("Пауза" if self._timer.isActive() else "Відтворити")
        else:
            self.play_button.setText("Pause" if self._timer.isActive() else "Play")
        self._language = language
        if self.has_artifact:
            self.set_stale(self.canvas.preview_is_stale)
        else:
            self.state_label.setText(
                "Спочатку згенеруйте сторінку" if ukrainian else "Generate the page to populate this mode"
            )

    def clear(self) -> None:
        self._timer.stop()
        self._positions.clear()
        self.canvas.clear_artifacts()
        self.gcode.clear()
        self.timeline.setRange(0, 0)
        self.step_label.setText("—")
        self.set_language(getattr(self, "_language", "en"))

    def set_artifacts(
        self,
        production_svg: bytes,
        preview_svg: bytes,
        plan_json: bytes,
        gcode: bytes,
    ) -> None:
        self.canvas.set_artifacts(production_svg, preview_svg, plan_json)
        self.canvas.set_show_travel(self.mode == "preview")
        self.canvas.set_show_markers(self.mode == "preview")
        self.canvas.zoom_to_fit()
        self.gcode.setPlainText(gcode.decode("utf-8", errors="strict"))
        self._positions = self._positions_from_plan(json.loads(plan_json))
        self.timeline.setRange(0, max(0, len(self._positions) - 1))
        self.timeline.setValue(0)
        self._show_step(0)
        self.set_stale(False)

    def set_stale(self, stale: bool) -> None:
        if not self.has_artifact:
            return
        self.canvas.set_preview_stale(stale)
        if stale:
            text = "ПОПЕРЕДНІЙ ПЕРЕГЛЯД · ЗГЕНЕРУЙТЕ СТОРІНКУ" if self._language == "uk" else \
                "STALE PREVIEW · GENERATE THE PAGE"
        elif self.mode == "execution":
            text = "СИМУЛЯЦІЯ · ОБЛАДНАННЯ НЕ ПІДКЛЮЧЕНО" if self._language == "uk" else \
                "SIMULATION ONLY · NO HARDWARE CONNECTED"
        else:
            text = "Діагностичний маршрут і перевірений G-code" if self._language == "uk" else \
                "Diagnostic travel path and validated G-code"
        self.state_label.setText(text)

    @staticmethod
    def _positions_from_plan(plan: dict) -> list[tuple[QPointF, bool, str]]:
        positions: list[tuple[QPointF, bool, str]] = []
        pen_down = False
        for operation in plan.get("operations", []):
            kind = operation.get("op", "")
            if kind == "pen_down":
                pen_down = True
            elif kind in {"pen_up", "ensure_pen_up"}:
                pen_down = False
            elif kind == "travel_to":
                target = operation.get("target", {})
                positions.append((QPointF(float(target["x"]), float(target["y"])), False, kind))
            elif kind == "draw":
                for segment in operation.get("segments", []):
                    target = segment.get("p3") or segment.get("p1")
                    if target:
                        positions.append((QPointF(float(target["x"]), float(target["y"])), pen_down, kind))
        return positions

    def toggle_playback(self) -> None:
        if not self._positions:
            return
        if self._timer.isActive():
            self._timer.stop()
        else:
            if self.timeline.value() >= self.timeline.maximum():
                self.timeline.setValue(0)
            self._update_timer_interval()
            self._timer.start()
        self.set_language(self._language)

    def _update_timer_interval(self) -> None:
        speed = float(self.speed_combo.currentData() or 1.0)
        self._timer.setInterval(max(16, round(80 / speed)))

    def _advance(self) -> None:
        if self.timeline.value() >= self.timeline.maximum():
            self._timer.stop()
            self.set_language(self._language)
            return
        self.timeline.setValue(self.timeline.value() + 1)

    def _show_step(self, index: int) -> None:
        if not self._positions:
            self.canvas.set_head_position(None)
            self.step_label.setText("—")
            return
        point, pen_down, kind = self._positions[index]
        self.canvas.set_head_position(point, pen_down=pen_down)
        pen = "DOWN" if pen_down else "UP"
        self.step_label.setText(
            f"{index + 1}/{len(self._positions)} · {kind} · X {point.x():.2f} · Y {point.y():.2f} · PEN {pen}"
        )
