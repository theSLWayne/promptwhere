"""Filesystem backend: one folder per prompt, one YAML file per version."""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .errors import InvalidPromptName, PromptNotFound, VersionNotFound
from .models import VersionRecord, validate_name

_VERSION_FILE_RE = re.compile(r"v(\d+)\.yaml")


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    # Multi-line prompts stay readable as YAML block scalars.
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):  # hand-written, unquoted timestamps
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class FileSystemBackend:
    """Stores prompts as ``<root>/<name>/v<N>.yaml``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _prompt_dir(self, name: str) -> Path:
        return self.root / validate_name(name)

    def _version_path(self, name: str, version: int) -> Path:
        return self._prompt_dir(name) / f"v{version}.yaml"

    def _require_prompt(self, name: str) -> Path:
        directory = self._prompt_dir(name)
        if not directory.is_dir():
            matches = difflib.get_close_matches(name, self.list_prompts(), n=3)
            raise PromptNotFound(name, matches)
        return directory

    def _version_numbers(self, directory: Path) -> list[int]:
        numbers = []
        for path in directory.iterdir():
            match = _VERSION_FILE_RE.fullmatch(path.name)
            if match:
                numbers.append(int(match.group(1)))
        return sorted(numbers)

    def save_version(self, name: str, record: VersionRecord) -> None:
        directory = self._prompt_dir(name)
        directory.mkdir(parents=True, exist_ok=True)
        data = {
            "version": record.version,
            "created_at": _format_time(record.created_at),
            "message": record.message,
            "content_hash": record.content_hash,
            "metadata": record.metadata,
            "template": record.template,
        }
        text = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True)
        self._version_path(name, record.version).write_text(text, encoding="utf-8")

    def get_version(self, name: str, version: int) -> VersionRecord:
        directory = self._require_prompt(name)
        path = self._version_path(name, version)
        if not path.is_file():
            raise VersionNotFound(name, version, self._version_numbers(directory))
        return self._read(path)

    def list_versions(self, name: str) -> list[VersionRecord]:
        directory = self._require_prompt(name)
        return [self._read(self._version_path(name, n)) for n in self._version_numbers(directory)]

    def list_prompts(self) -> list[str]:
        names = []
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                names.append(validate_name(path.name))
            except InvalidPromptName:
                continue  # not a prompt folder
        return sorted(names)

    @staticmethod
    def _read(path: Path) -> VersionRecord:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return VersionRecord(
            version=int(data["version"]),
            template=data["template"],
            created_at=_parse_time(data["created_at"]),
            content_hash=data["content_hash"],
            message=data.get("message"),
            metadata=data.get("metadata") or {},
        )
