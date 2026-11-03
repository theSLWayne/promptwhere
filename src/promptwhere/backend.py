"""The storage interface. The public API talks to storage only through this."""

from __future__ import annotations

from typing import Protocol

from .models import VersionRecord


class Backend(Protocol):
    def save_version(self, name: str, record: VersionRecord) -> None:
        """Store a new version. Creates the prompt if it does not exist."""

    def get_version(self, name: str, version: int) -> VersionRecord:
        """Return one version. Raises ``PromptNotFound`` or ``VersionNotFound``."""

    def list_versions(self, name: str) -> list[VersionRecord]:
        """Return all versions, oldest first. Raises ``PromptNotFound``."""

    def list_prompts(self) -> list[str]:
        """Return all prompt names, sorted."""
