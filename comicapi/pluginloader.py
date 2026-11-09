"""Entry point names shared by installed plugins and local plugin archives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

ARCHIVER_ENTRY_POINT = "comicapi.archiver"
TAG_ENTRY_POINT = "comicapi.tags"
TALKER_ENTRY_POINT = "comictagger.talker"

T = TypeVar("T")


@dataclass(frozen=True)
class LocalPlugin(Generic[T]):
    name: str
    path: Path
    implementation: type[T]
