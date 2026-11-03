from pathlib import Path

import pytest

from promptwhere import (
    InvalidPromptName,
    Prompt,
    PromptNotFound,
    PromptWhere,
    VersionNotFound,
)


@pytest.fixture
def store(tmp_path: Path) -> PromptWhere:
    return PromptWhere(tmp_path / "prompts")


def test_store_folder_is_created(tmp_path: Path) -> None:
    PromptWhere(tmp_path / "a" / "b")
    assert (tmp_path / "a" / "b").is_dir()


def test_new_name_creates_version_1_then_2(store: PromptWhere) -> None:
    assert store.save("chatbot", "one").version == 1
    assert store.save("chatbot", "two").version == 2


def test_save_returns_prompt(store: PromptWhere) -> None:
    prompt = store.save("chatbot", "Hello", message="first", metadata={"model": "m"})
    assert isinstance(prompt, Prompt)
    assert (prompt.name, prompt.template, prompt.message) == ("chatbot", "Hello", "first")
    assert prompt.metadata == {"model": "m"}
    assert prompt.created_at.tzinfo is not None
    assert str(prompt) == "Hello"


def test_get_defaults_to_latest(store: PromptWhere) -> None:
    store.save("chatbot", "one")
    store.save("chatbot", "two")
    assert store.get("chatbot").template == "two"


def test_get_specific_version(store: PromptWhere) -> None:
    store.save("chatbot", "one")
    store.save("chatbot", "two")
    assert store.get("chatbot", 1).template == "one"


def test_history_is_ordered_and_complete(store: PromptWhere) -> None:
    for text in ("a", "b", "c"):
        store.save("chatbot", text, message=f"m-{text}")
    history = store.history("chatbot")
    assert [p.version for p in history] == [1, 2, 3]
    assert [p.template for p in history] == ["a", "b", "c"]
    assert [p.message for p in history] == ["m-a", "m-b", "m-c"]


def test_versions_are_numbered_per_prompt(store: PromptWhere) -> None:
    store.save("one", "x")
    store.save("one", "y")
    assert store.save("two", "z").version == 1


def test_list_returns_sorted_names(store: PromptWhere) -> None:
    store.save("summarizer", "x")
    store.save("chatbot", "y")
    assert store.list() == ["chatbot", "summarizer"]


def test_list_empty_store(store: PromptWhere) -> None:
    assert store.list() == []


def test_list_ignores_stray_files_and_folders(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    store = PromptWhere(root)
    store.save("chatbot", "x")
    (root / "notes.txt").write_text("hi")
    (root / "Not Valid").mkdir()
    assert store.list() == ["chatbot"]


def test_multiline_unicode_and_metadata_round_trip(tmp_path: Path) -> None:
    text = "You are a helpful assistant.\n  Indented line.\nCafé ☕ {company}\n"
    meta = {"model": "some-model", "temperature": 0.2, "tags": ["a", "b"]}
    PromptWhere(tmp_path).save("chatbot", text, metadata=meta)

    reopened = PromptWhere(tmp_path).get("chatbot")
    assert reopened.template == text
    assert reopened.metadata == meta


def test_created_at_round_trips(tmp_path: Path) -> None:
    saved = PromptWhere(tmp_path).save("chatbot", "x")
    assert PromptWhere(tmp_path).get("chatbot").created_at == saved.created_at


def test_version_file_layout(tmp_path: Path) -> None:
    PromptWhere(tmp_path).save("chatbot", "Hello\nWorld\n", message="msg")
    content = (tmp_path / "chatbot" / "v1.yaml").read_text(encoding="utf-8")
    assert "version: 1" in content
    assert "message: msg" in content
    assert "content_hash: sha256:" in content
    assert "template: |" in content


def test_saving_does_not_modify_earlier_versions(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path)
    store.save("chatbot", "one")
    v1 = tmp_path / "chatbot" / "v1.yaml"
    before = v1.read_bytes()
    store.save("chatbot", "two")
    assert v1.read_bytes() == before


@pytest.mark.parametrize(
    "name", ["../x", "", "Chatbot", "a/b", "a b", "-lead", "_lead", ".hidden", "a.b", "x\n"]
)
def test_invalid_names_rejected(store: PromptWhere, name: str) -> None:
    with pytest.raises(InvalidPromptName):
        store.save(name, "x")
    with pytest.raises(InvalidPromptName):
        store.get(name)
    with pytest.raises(InvalidPromptName):
        store.history(name)


@pytest.mark.parametrize("name", ["a", "chatbot", "support-bot_2", "9lives", "a-b_c"])
def test_valid_names_accepted(store: PromptWhere, name: str) -> None:
    assert store.save(name, "x").name == name


def test_invalid_name_writes_nothing(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path / "prompts")
    with pytest.raises(InvalidPromptName):
        store.save("../escape", "x")
    assert list((tmp_path).iterdir()) == [tmp_path / "prompts"]
    assert list((tmp_path / "prompts").iterdir()) == []


def test_unknown_prompt_suggests_close_match(store: PromptWhere) -> None:
    store.save("chatbot", "x")
    with pytest.raises(PromptNotFound, match="Did you mean 'chatbot'"):
        store.get("chatbt")
    with pytest.raises(PromptNotFound):
        store.history("chatbt")


def test_unknown_prompt_without_match(store: PromptWhere) -> None:
    with pytest.raises(PromptNotFound, match="save"):
        store.get("nothing")


def test_unknown_version_lists_available(store: PromptWhere) -> None:
    store.save("chatbot", "x")
    with pytest.raises(VersionNotFound, match="Available versions: 1"):
        store.get("chatbot", 5)


def test_get_version_of_unknown_prompt(store: PromptWhere) -> None:
    with pytest.raises(PromptNotFound):
        store.get("nothing", 1)
