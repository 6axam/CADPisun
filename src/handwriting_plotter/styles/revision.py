"""Revision identity helpers."""

from __future__ import annotations

import re


_REVISION = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:-[a-z0-9.-]+)?$")


def validate_revision(value: str) -> str:
    if not _REVISION.fullmatch(value):
        raise ValueError("invalid immutable style revision")
    return value

