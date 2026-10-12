"""Exact literal Unicode coverage checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoverageReport:
    declared: tuple[str, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    undeclared: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing and not self.undeclared


def compare_coverage(declared: tuple[str, ...], present: set[str]) -> CoverageReport:
    expected = set(declared)
    return CoverageReport(
        tuple(sorted(expected)),
        tuple(sorted(present)),
        tuple(sorted(expected - present)),
        tuple(sorted(present - expected)),
    )

