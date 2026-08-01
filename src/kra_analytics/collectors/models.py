from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiValidation:
    status: str
    result_code: str | None
    total_count: int | None
    item_count: int
    error_message: str | None = None

    @property
    def successful(self) -> bool:
        return self.status == "SUCCESS"


@dataclass(frozen=True)
class RawArtifact:
    relative_path: str
    absolute_path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RequestOutcome:
    request_id: str
    api_status: str
    total_count: int | None
    item_count: int
    raw_artifact: RawArtifact | None


@dataclass(frozen=True)
class BatchOutcome:
    batch_id: str
    request_count: int
    success_count: int
    no_data_count: int
    failure_count: int
