from pathlib import Path

import pytest

from promptwhere import PromptWhere, VersionNotFound
from promptwhere.cli import main


@pytest.fixture
def store(tmp_path: Path) -> PromptWhere:
    s = PromptWhere(tmp_path / "prompts")
    s.save("chatbot", "line one\nline two\n", message="first")
    s.save("chatbot", "line one\nline 2\n", message="second")
    return s


def run(tmp_path: Path, *argv: str) -> int:
    return main(["--path", str(tmp_path / "prompts"), *argv])


def fake_editor(monkeypatch: pytest.MonkeyPatch, new_text: str | None) -> None:
    """Replace the editor with one that returns ``new_text`` (None: leave the text alone)."""

    def edit(initial: str) -> str:
        return initial if new_text is None else new_text

    monkeypatch.setattr("promptwhere.cli._edit_in_editor", edit)


# --- diff on the public API -----------------------------------------------------


def test_api_diff_between_versions(store: PromptWhere) -> None:
    diff = store.diff("chatbot", 1, 2)
    assert "--- chatbot v1" in diff and "+++ chatbot v2" in diff
    assert "-line two" in diff and "+line 2" in diff
    assert store.diff("chatbot", 2, 2) == ""


def test_api_diff_missing_version(store: PromptWhere) -> None:
    with pytest.raises(VersionNotFound):
        store.diff("chatbot", 1, 9)


# --- commands -------------------------------------------------------------------


def test_list(store: PromptWhere, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store.save("another", "x")
    assert run(tmp_path, "list") == 0
    assert capsys.readouterr().out.split() == ["another", "chatbot"]


def test_show_latest_version_and_label(
    store: PromptWhere, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store.set_label("chatbot", "production", 1)
    run(tmp_path, "show", "chatbot")
    assert capsys.readouterr().out == "line one\nline 2\n"
    run(tmp_path, "show", "chatbot", "--version", "1")
    assert capsys.readouterr().out == "line one\nline two\n"
    run(tmp_path, "show", "chatbot", "--label", "production")
    assert capsys.readouterr().out == "line one\nline two\n"


def test_show_version_and_label_together_is_rejected(store: PromptWhere, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run(tmp_path, "show", "chatbot", "--version", "1", "--label", "x")


def test_history(store: PromptWhere, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, "history", "chatbot") == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("v1") and lines[0].endswith("first")
    assert lines[1].startswith("v2") and lines[1].endswith("second")


def test_diff(store: PromptWhere, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, "diff", "chatbot", "1", "2") == 0
    out = capsys.readouterr().out
    assert "--- chatbot v1" in out and "+++ chatbot v2" in out
    assert "-line two" in out and "+line 2" in out


def test_label(store: PromptWhere, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, "label", "chatbot", "production", "2") == 0
    assert store.labels("chatbot") == {"production": 2}
    assert "production -> v2" in capsys.readouterr().out


def test_edit_saves_next_version(
    store: PromptWhere, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_editor(monkeypatch, "brand new\n")
    assert run(tmp_path, "edit", "chatbot", "-m", "rewrite") == 0
    latest = store.get("chatbot")
    assert (latest.version, latest.template, latest.message) == (3, "brand new\n", "rewrite")


def test_edit_unchanged_does_nothing(
    store: PromptWhere, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_editor(monkeypatch, None)
    assert run(tmp_path, "edit", "chatbot") == 0
    assert len(store.history("chatbot")) == 2


@pytest.mark.parametrize("text", ["", "  \n\n"])
def test_edit_empty_does_nothing(
    store: PromptWhere, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    fake_editor(monkeypatch, text)
    assert run(tmp_path, "edit", "chatbot") == 0
    assert len(store.history("chatbot")) == 2


def test_errors_are_printed_with_exit_code_1(
    store: PromptWhere, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "show", "chatbt") == 1
    assert "Did you mean 'chatbot'" in capsys.readouterr().err
