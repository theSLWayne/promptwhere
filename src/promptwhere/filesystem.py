"""Filesystem backend: one folder per prompt, one YAML file per version."""

from __future__ import annotations

import difflib
import os
import re
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .errors import InvalidPromptName, LockTimeout, PromptNotFound, VersionExists, VersionNotFound
from .models import VersionRecord, validate_name

_VERSION_FILE_RE = re.compile(r"v(\d+)\.yaml")
_LOCK_FILE = "_lock"
_LOCK_POLL = 0.02
LOCK_TIMEOUT = 10.0  # seconds to wait for another process before giving up


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
        if not directory.is_dir() or not self._version_numbers(directory):
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

    @contextmanager
    def lock(self, name: str) -> Iterator[None]:
        directory = self._prompt_dir(name)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / _LOCK_FILE
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(name, str(lock_path)) from None
                time.sleep(_LOCK_POLL)
        os.close(fd)
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def save_version(self, name: str, record: VersionRecord) -> None:
        directory = self._prompt_dir(name)
        directory.mkdir(parents=True, exist_ok=True)
        target = self._version_path(name, record.version)
        if target.exists():
            raise VersionExists(name, record.version)
        data = {
            "version": record.version,
            "created_at": _format_time(record.created_at),
            "message": record.message,
            "content_hash": record.content_hash,
            "metadata": record.metadata,
            "template": record.template,
        }
        text = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True)
        self._write_new(name, target, text)

    @staticmethod
    def _write_new(name: str, target: Path, text: str) -> None:
        """Write ``text`` to a temp file next to ``target``, then publish it atomically."""
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # A hard link fails if the target exists, so it can never overwrite.
                os.link(tmp, target)
            except FileExistsError:
                raise VersionExists(name, int(target.stem[1:])) from None
            except OSError:
                # Filesystem without hard links: rename, safe because the caller holds the lock.
                if target.exists():
                    raise VersionExists(name, int(target.stem[1:])) from None
                os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

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
            if not path.is_dir() or not self._version_numbers(path):
                continue  # not a folder, or a folder with no saved versions
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
