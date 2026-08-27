from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator

from src.models.core import RawEntity


class SourceConnector(ABC):
    supports_incremental: bool = False

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def fetch_all(self) -> Iterator[RawEntity]: ...

    def fetch_since(self, since: datetime) -> Iterator[RawEntity]:
        raise NotImplementedError("This connector does not support incremental fetch")
