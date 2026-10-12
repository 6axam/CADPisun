"""Job controls that do not leak event-loop or platform objects into core."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event


@dataclass(slots=True)
class CancellationToken:
    _event: Event = field(default_factory=Event, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled


class JobCancelled(Exception):
    """Raised only at explicit application cancellation points."""

