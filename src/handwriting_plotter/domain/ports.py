"""Small dependency-inversion ports used by pure core modules."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar


T_co = TypeVar("T_co", covariant=True)


class Repository(Protocol[T_co]):
    def load(self, object_id: str, revision: str) -> T_co: ...


class AtomicPublisher(Protocol):
    def publish_bytes(self, path: Path, content: bytes, *, overwrite: bool = False) -> None: ...

