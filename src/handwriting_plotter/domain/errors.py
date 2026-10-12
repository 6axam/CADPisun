"""Structured errors shared by application boundaries."""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class ExitCode(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    VALIDATION_FAILED = 3
    RESOURCE_LIMIT = 4
    IO_ERROR = 5
    INTERNAL_ERROR = 70


class Diagnostic(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"]
    stage: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_spans: tuple[tuple[int, int], ...] = ()
    object_ids: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


T = TypeVar("T")


class Outcome(BaseModel, Generic[T]):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    value: T | None = None
    errors: tuple[Diagnostic, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.errors

