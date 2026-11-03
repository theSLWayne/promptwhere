"""Data model and name validation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import InvalidPromptName

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def validate_name(name: str) -> str:
    """Return ``name`` if it is a valid prompt name, otherwise raise ``InvalidPromptName``.

    Names map directly to folder names, so this also keeps paths safe.
    """
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise InvalidPromptName(str(name))
    return name


def hash_template(template: str) -> str:
    """SHA-256 of the template text, in the ``sha256:<hex>`` form used on disk."""
    return "sha256:" + hashlib.sha256(template.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VersionRecord:
    """One immutable saved version, as handled by a storage backend."""

    version: int
    template: str
    created_at: datetime
    content_hash: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Prompt:
    """A prompt version returned to the user."""

    name: str
    version: int
    template: str
    created_at: datetime
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.template

    @classmethod
    def from_record(cls, name: str, record: VersionRecord) -> Prompt:
        return cls(
            name=name,
            version=record.version,
            template=record.template,
            created_at=record.created_at,
            message=record.message,
            metadata=dict(record.metadata),
        )
