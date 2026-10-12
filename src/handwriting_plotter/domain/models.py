"""Public validation models and canonical serialization helpers."""

from __future__ import annotations

import json
import math
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class Envelope(StrictModel):
    format: str = Field(min_length=1)
    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    id: str = Field(min_length=1)
    payload: dict[str, Any]
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extensions")
    @classmethod
    def namespaced_extensions(cls, value: dict[str, Any]) -> dict[str, Any]:
        if any("." not in key for key in value):
            raise ValueError("extension keys must be namespaced")
        return value


class Check(StrictModel):
    check_id: str
    passed: bool
    message: str = ""


class ValidationReport(StrictModel):
    input_hashes: tuple[str, ...]
    validator_version: str
    checks: tuple[Check, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    passed: bool


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(data: bytes | str) -> Any:
    """Load UTF-8 JSON while rejecting BOM, duplicate keys and NaN/Infinity."""
    if isinstance(data, bytes):
        if data.startswith(b"\xef\xbb\xbf"):
            raise ValueError("JSON BOM is not allowed")
        data = data.decode("utf-8", errors="strict")
    return json.loads(
        data,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_constant,
    )


def canonical_json_bytes(value: Any) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.encode("utf-8")


def canonical_hash(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def finite_number(value: float, field: str = "number") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result

