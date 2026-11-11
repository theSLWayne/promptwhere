"""Exceptions raised by promptwhere."""

from __future__ import annotations


class PromptWhereError(Exception):
    """Base class for all promptwhere errors."""


class InvalidPromptName(PromptWhereError):
    """The prompt name does not follow the naming rules."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Invalid prompt name {name!r}. Use lowercase letters, digits, '-' and '_', "
            "and start with a letter or digit (e.g. 'chatbot' or 'support-bot_2')."
        )
        self.name = name


class PromptNotFound(PromptWhereError):
    """No prompt with the given name exists in the store."""

    def __init__(self, name: str, suggestions: list[str] | None = None) -> None:
        message = f"No prompt named {name!r} in this store."
        if suggestions:
            message += " Did you mean " + " or ".join(repr(s) for s in suggestions) + "?"
        else:
            message += " Save one first with save(name, text), or check list() for existing names."
        super().__init__(message)
        self.name = name
        self.suggestions = suggestions or []


class MissingVariables(PromptWhereError):
    """A template variable was not provided at render time."""

    def __init__(self, name: str, missing: list[str]) -> None:
        listed = ", ".join(missing)
        example = ", ".join(f"{m}=..." for m in missing)
        super().__init__(
            f"Prompt {name!r} needs variables that were not provided: {listed}. "
            f"Pass them as keyword arguments, e.g. render({name!r}, {example})."
        )
        self.name = name
        self.missing = missing


class VersionExists(PromptWhereError):
    """A version file already exists; saved versions are never overwritten."""

    def __init__(self, name: str, version: int) -> None:
        super().__init__(
            f"Version {version} of prompt {name!r} already exists and versions are immutable. "
            "Save the text again to create the next version."
        )
        self.name = name
        self.version = version


class LockTimeout(PromptWhereError):
    """The per-prompt lock could not be acquired in time."""

    def __init__(self, name: str, path: str) -> None:
        super().__init__(
            f"Timed out waiting for the lock on prompt {name!r}. Another process may be saving it. "
            f"If no other process is running, a crashed save left {path!r} behind: delete it and retry."
        )
        self.name = name
        self.path = path


class VersionNotFound(PromptWhereError):
    """The prompt exists but has no such version."""

    def __init__(self, name: str, version: int, available: list[int]) -> None:
        shown = ", ".join(str(v) for v in available) or "none"
        super().__init__(f"Prompt {name!r} has no version {version}. Available versions: {shown}.")
        self.name = name
        self.version = version


class LabelNotFound(PromptWhereError):
    """The prompt has no label with that name."""

    def __init__(self, name: str, label: str, available: list[str]) -> None:
        shown = ", ".join(repr(a) for a in available) or "none"
        super().__init__(
            f"Prompt {name!r} has no label {label!r}. Existing labels: {shown}. "
            f"Create it with set_label({name!r}, {label!r}, version)."
        )
        self.name = name
        self.label = label
