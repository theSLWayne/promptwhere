from pathlib import Path

import pytest

from promptwhere import LabelNotFound, PromptNotFound, PromptWhere, VersionNotFound


@pytest.fixture
def store(tmp_path: Path) -> PromptWhere:
    s = PromptWhere(tmp_path / "prompts")
    s.save("chatbot", "one {x}")
    s.save("chatbot", "two {x}")
    s.save("chatbot", "three {x}")
    return s


def test_labels_empty_by_default(store: PromptWhere) -> None:
    assert store.labels("chatbot") == {}


def test_set_and_get_by_label(store: PromptWhere) -> None:
    store.set_label("chatbot", "production", 2)
    store.set_label("chatbot", "staging", 3)
    assert store.labels("chatbot") == {"production": 2, "staging": 3}
    assert store.get("chatbot", label="production").template == "two {x}"
    assert store.get("chatbot").version == 3  # latest is unaffected


def test_moving_label_does_not_change_versions(store: PromptWhere, tmp_path: Path) -> None:
    store.set_label("chatbot", "production", 2)
    folder = tmp_path / "prompts" / "chatbot"
    before = {p.name: p.read_bytes() for p in folder.glob("v*.yaml")}
    history_before = store.history("chatbot")
    store.set_label("chatbot", "production", 1)  # roll back
    store.set_label("chatbot", "production", 3)  # promote
    assert {p.name: p.read_bytes() for p in folder.glob("v*.yaml")} == before
    assert store.history("chatbot") == history_before
    assert store.labels("chatbot") == {"production": 3}


def test_labels_persist_on_disk(store: PromptWhere, tmp_path: Path) -> None:
    store.set_label("chatbot", "production", 2)
    folder = tmp_path / "prompts" / "chatbot"
    assert (folder / "_labels.yaml").is_file()
    assert PromptWhere(tmp_path / "prompts").labels("chatbot") == {"production": 2}
    assert not list(folder.glob("*.tmp"))
    assert not (folder / "_lock").exists()


def test_labels_are_per_prompt(store: PromptWhere) -> None:
    store.save("other", "x")
    store.set_label("chatbot", "production", 2)
    assert store.labels("other") == {}


def test_unknown_label_raises_with_available(store: PromptWhere) -> None:
    store.set_label("chatbot", "production", 2)
    with pytest.raises(LabelNotFound, match="production"):
        store.get("chatbot", label="staging")


def test_version_and_label_are_mutually_exclusive(store: PromptWhere) -> None:
    store.set_label("chatbot", "production", 2)
    with pytest.raises(ValueError, match="either version or label"):
        store.get("chatbot", version=1, label="production")


def test_set_label_to_missing_version(store: PromptWhere) -> None:
    with pytest.raises(VersionNotFound):
        store.set_label("chatbot", "production", 9)
    assert store.labels("chatbot") == {}


def test_set_label_on_missing_prompt_creates_nothing(store: PromptWhere, tmp_path: Path) -> None:
    with pytest.raises(PromptNotFound):
        store.set_label("chatbt", "production", 1)
    assert not (tmp_path / "prompts" / "chatbt").exists()
    with pytest.raises(PromptNotFound):
        store.labels("chatbt")


def test_empty_label_rejected(store: PromptWhere) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        store.set_label("chatbot", " ", 1)


def test_render_by_label(store: PromptWhere) -> None:
    store.set_label("chatbot", "production", 1)
    assert store.render("chatbot", label="production", x="hi") == "one hi"


def test_labels_file_is_not_a_version(store: PromptWhere) -> None:
    store.set_label("chatbot", "production", 2)
    assert [p.version for p in store.history("chatbot")] == [1, 2, 3]
