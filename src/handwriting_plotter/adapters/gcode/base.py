"""Command artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandArtifact:
    dialect_id: str
    profile_id: str
    media_type: str
    content: bytes
    page_id: str
    sha256: str
    op_to_line_map: tuple[tuple[str, int], ...]
    simulation_only: bool

