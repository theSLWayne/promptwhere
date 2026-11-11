"""The public API."""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backend import Backend
from .errors import LabelNotFound
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
            The saved ``Prompt``, or the latest existing one if ``text`` is
            unchanged (nothing is saved then).

        Raises:
            InvalidPromptName: If ``name`` is not valid.
            LockTimeout: If another process holds the prompt's lock too long.
        """
        validate_name(name)
        content_hash = hash_template(text)
        with self._backend.lock(name):
            existing = name in self._backend.list_prompts()
            latest = self._backend.list_versions(name)[-1] if existing else None
            if latest is not None and latest.content_hash == content_hash:
                return Prompt.from_record(name, latest)
            record = VersionRecord(
                version=latest.version + 1 if latest else 1,
                template=text,
                created_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                message=message,
                metadata=dict(metadata or {}),
            )
            self._backend.save_version(name, record)
        return Prompt.from_record(name, record)

    def get(self, name: str, version: int | None = None, label: str | None = None) -> Prompt:
        """Return a version of a prompt, the latest by default.

        Args:
            name: Prompt name.
            version: A version number. Mutually exclusive with ``label``.
            label: A label such as ``"production"``. Mutually exclusive with ``version``.

        Raises:
            ValueError: If both ``version`` and ``label`` are given.
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
            VersionNotFound: If ``version`` does not exist.
            LabelNotFound: If ``label`` does not exist.
        """
        validate_name(name)
        if version is not None and label is not None:
            raise ValueError(
                "Pass either version or label to get(), not both. "
                "Drop one of them, e.g. get(name, version=2) or get(name, label='production')."
            )
        if label is not None:
            labels = self._backend.get_labels(name)
            if label not in labels:
                raise LabelNotFound(name, label, sorted(labels))
            version = labels[label]
        if version is None:
            record = self._backend.list_versions(name)[-1]
        else:
            record = self._backend.get_version(name, version)
        return Prompt.from_record(name, record)

    def render(
        self,
        name: str,
        /,
        version: int | None = None,
        label: str | None = None,
        **variables: Any,
    ) -> str:
        """Fetch a prompt (the latest by default) and fill in its variables.

        Args:
            name: Prompt name (positional-only, so a ``{name}`` variable still works).
            version: Version to render; the latest if omitted. A template variable
                called ``version`` or ``label`` can't be passed here; use
                ``get(...).render(...)``.
            label: Label to render instead of a version (not both).
            **variables: Values for the ``{variables}`` in the template.

        Raises:
            ValueError: If both ``version`` and ``label`` are given.
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
            VersionNotFound: If ``version`` does not exist.
            LabelNotFound: If ``label`` does not exist.
            MissingVariables: If the template uses a variable that was not provided.
        """
        return self.get(name, version, label).render(**variables)

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

    def set_label(self, name: str, label: str, version: int) -> None:
        """Point ``label`` at ``version``, creating or moving it. No version changes.

        Args:
            name: Prompt name.
            label: Label such as ``"production"``.
            version: The version it should point to.

        Raises:
            ValueError: If ``label`` is empty.
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
            VersionNotFound: If ``version`` does not exist.
            LockTimeout: If another process holds the prompt's lock too long.
        """
        validate_name(name)
        if not isinstance(label, str) or not label.strip():
            raise ValueError("A label must be a non-empty string, e.g. 'production'.")
        self._backend.get_version(name, version)  # raises if the prompt or version is missing
        with self._backend.lock(name):
            self._backend.set_label(name, label, version)

    def labels(self, name: str) -> dict[str, int]:
        """Return the current labels of a prompt as ``{label: version}``.

        Raises:
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
        """
        validate_name(name)
        return self._backend.get_labels(name)

    def diff(self, name: str, a: int, b: int) -> str:
        """Return a unified diff between versions ``a`` and ``b`` of a prompt.

        Args:
            name: Prompt name.
            a: The older version number.
            b: The newer version number.

        Returns:
            The unified diff text, or an empty string if the templates are identical.

        Raises:
            InvalidPromptName: If ``name`` is not valid.
            PromptNotFound: If the prompt does not exist.
            VersionNotFound: If ``a`` or ``b`` does not exist.
        """
        validate_name(name)
        old = self._backend.get_version(name, a).template
        new = self._backend.get_version(name, b).template
        lines = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{name} v{a}",
            tofile=f"{name} v{b}",
        )
        return "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in lines
        )
