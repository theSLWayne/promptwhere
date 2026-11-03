"""The public API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backend import Backend
from .filesystem import FileSystemBackend
from .models import Prompt, VersionRecord, hash_template, validate_name


class PromptWhere:
    """A prompt store: many named prompts, each with numbered versions."""

    def __init__(self, path: str | Path = "./prompts") -> None:
        """Open a store, creating the folder if needed.

        Args:
            path: Folder that holds the prompts.
        """
        self._backend: Backend = FileSystemBackend(path)

    def save(
        self,
        name: str,
        text: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Prompt:
        """Save ``text`` as the next version of prompt ``name`` (version 1 if new).

        Args:
            name: Prompt name: lowercase letters, digits, '-' and '_'.
            text: The prompt text.
            message: Optional note about this version.
            metadata: Optional free-form details (model, temperature, ...).

        Returns:
            The saved ``Prompt``.

        Raises:
            InvalidPromptName: If ``name`` is not valid.
        """
        validate_name(name)
        existing = name in self._backend.list_prompts()
        latest = self._backend.list_versions(name)[-1].version if existing else 0
        record = VersionRecord(
            version=latest + 1,
            template=text,
            created_at=datetime.now(timezone.utc),
            content_hash=hash_template(text),
            message=message,
            metadata=dict(metadata or {}),
        )
        self._backend.save_version(name, record)
        return Prompt.from_record(name, record)

    def get(self, name: str, version: int | None = None) -> Prompt:
        """Return a version of a prompt, the latest by default.

        Raises:
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
            VersionNotFound: If ``version`` does not exist.
        """
        validate_name(name)
        if version is None:
            record = self._backend.list_versions(name)[-1]
        else:
            record = self._backend.get_version(name, version)
        return Prompt.from_record(name, record)

    def history(self, name: str) -> list[Prompt]:
        """Return all versions of a prompt, oldest first.

        Raises:
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
        """
        validate_name(name)
        return [Prompt.from_record(name, r) for r in self._backend.list_versions(name)]

    def list(self) -> list[str]:
        """Return the names of all prompts in the store."""
        return self._backend.list_prompts()
