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


class VersionNotFound(PromptWhereError):
    """The prompt exists but has no such version."""

    def __init__(self, name: str, version: int, available: list[int]) -> None:
        shown = ", ".join(str(v) for v in available) or "none"
        super().__init__(f"Prompt {name!r} has no version {version}. Available versions: {shown}.")
        self.name = name
        self.version = version
