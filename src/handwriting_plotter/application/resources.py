"""Locate source-tree or wheel-bundled immutable assets."""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def style_root() -> Path:
    packaged = files("handwriting_plotter").joinpath("assets/styles")
    if packaged.is_dir():
        with as_file(packaged) as path:
            return path
    return Path(__file__).parents[3] / "assets" / "styles"


def virtual_profile_path() -> Path:
    packaged = files("handwriting_plotter").joinpath("assets/profiles/virtual-cartesian-z-v1.json")
    if packaged.is_file():
        with as_file(packaged) as path:
            return path
    return Path(__file__).parents[3] / "profiles" / "virtual-cartesian-z-v1.json"

