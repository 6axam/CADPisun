"""Canonical JSON views for plans and reports."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic


def primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Point2):
        return {"x": value.x, "y": value.y}
    if isinstance(value, Line):
        return {"kind": "line", "p0": primitive(value.p0), "p1": primitive(value.p1)}
    if isinstance(value, Quadratic):
        return {"kind": "quadratic", "p0": primitive(value.p0), "c1": primitive(value.c1), "p1": primitive(value.p1)}
    if isinstance(value, Cubic):
        return {
            "kind": "cubic", "p0": primitive(value.p0), "c1": primitive(value.c1),
            "c2": primitive(value.c2), "p1": primitive(value.p1),
        }
    if is_dataclass(value):
        data = {field.name: primitive(getattr(value, field.name)) for field in fields(value)}
        data.setdefault("type", value.__class__.__name__)
        return data
    if isinstance(value, dict):
        return {str(key): primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(item) for item in value]
    raise TypeError(f"cannot serialize {type(value).__name__}")

