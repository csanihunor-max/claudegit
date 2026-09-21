from __future__ import annotations

from typing import Protocol

from ..models import Deal


class Notifier(Protocol):
    def notify(self, deal: Deal) -> None: ...
