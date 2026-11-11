import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from promptwhere import LockTimeout, PromptWhere, VersionExists, filesystem
from promptwhere.filesystem import FileSystemBackend
from promptwhere.models import VersionRecord, hash_template


def make_record(version: int, text: str) -> VersionRecord:
    return VersionRecord(
        version=version,
        template=text,
        created_at=datetime.now(timezone.utc),
        content_hash=hash_template(text),
    )


# --- content-hash dedupe ---------------------------------------------------


def test_identical_text_creates_no_new_version(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path)
    first = store.save("chatbot", "same")
    again = store.save("chatbot", "same", message="ignored")
    assert again == first
    assert [p.version for p in store.history("chatbot")] == [1]
    assert not (tmp_path / "chatbot" / "v2.yaml").exists()


def test_dedupe_compares_with_latest_only(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path)
    store.save("chatbot", "a")
    store.save("chatbot", "b")
    assert store.save("chatbot", "a").version == 3  # same as v1, but not as the latest


def test_changed_text_still_creates_new_version(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path)
    store.save("chatbot", "a")
    assert store.save("chatbot", "a ").version == 2


# --- no overwrite ------------------------------------------------------------


def test_backend_refuses_to_overwrite_existing_version(tmp_path: Path) -> None:
    backend = FileSystemBackend(tmp_path)
    backend.save_version("chatbot", make_record(1, "original"))
    path = tmp_path / "chatbot" / "v1.yaml"
    before = path.read_bytes()

    with pytest.raises(VersionExists, match="immutable"):
        backend.save_version("chatbot", make_record(1, "replacement"))
    assert path.read_bytes() == before


def test_publish_never_overwrites_even_if_file_appears_late(tmp_path: Path) -> None:
    backend = FileSystemBackend(tmp_path)
    target = tmp_path / "v1.yaml"
    target.write_text("existing")
    with pytest.raises(VersionExists):
        backend._write_new("chatbot", target, "new")
    assert target.read_text() == "existing"
    assert [p.name for p in tmp_path.iterdir()] == ["v1.yaml"]


# --- atomic writes -----------------------------------------------------------


def test_no_temp_files_left_after_save(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path)
    store.save("chatbot", "a")
    store.save("chatbot", "b")
    assert sorted(p.name for p in (tmp_path / "chatbot").iterdir()) == ["v1.yaml", "v2.yaml"]


def test_failed_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = FileSystemBackend(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(os, "link", boom)
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(RuntimeError):
        backend.save_version("chatbot", make_record(1, "x"))
    assert list((tmp_path / "chatbot").iterdir()) == []
    assert backend.list_prompts() == []


def test_falls_back_to_rename_without_hard_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(*args: object, **kwargs: object) -> None:
        raise OSError("hard links not supported")

    monkeypatch.setattr(os, "link", no_links)
    store = PromptWhere(tmp_path)
    store.save("chatbot", "a")
    assert store.get("chatbot").template == "a"
    assert sorted(p.name for p in (tmp_path / "chatbot").iterdir()) == ["v1.yaml"]


# --- locking -------------------------------------------------------------------


def test_lock_file_is_removed_after_save(tmp_path: Path) -> None:
    PromptWhere(tmp_path).save("chatbot", "a")
    assert not (tmp_path / "chatbot" / "_lock").exists()


def test_lock_released_when_save_fails(tmp_path: Path) -> None:
    backend = FileSystemBackend(tmp_path)
    with pytest.raises(RuntimeError), backend.lock("chatbot"):
        raise RuntimeError("fail inside lock")
    assert not (tmp_path / "chatbot" / "_lock").exists()


def test_held_lock_times_out_with_helpful_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filesystem, "LOCK_TIMEOUT", 0.1)
    store = PromptWhere(tmp_path)
    store.save("chatbot", "a")
    (tmp_path / "chatbot" / "_lock").touch()  # e.g. left behind by a crash

    with pytest.raises(LockTimeout, match="delete it"):
        store.save("chatbot", "b")
    assert [p.version for p in store.history("chatbot")] == [1]


def test_lock_is_per_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(filesystem, "LOCK_TIMEOUT", 0.1)
    store = PromptWhere(tmp_path)
    store.save("one", "a")
    (tmp_path / "one" / "_lock").touch()
    assert store.save("two", "a").version == 1


def test_concurrent_saves_get_distinct_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filesystem, "LOCK_TIMEOUT", 120.0)  # saves queue up on slow disks
    count = 6
    barrier = threading.Barrier(count)
    versions: list[int] = []
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            store = PromptWhere(tmp_path)  # separate handle per thread, like separate processes
            barrier.wait()
            versions.append(store.save("chatbot", f"text {i}").version)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sorted(versions) == list(range(1, count + 1))
    history = PromptWhere(tmp_path).history("chatbot")
    assert [p.version for p in history] == list(range(1, count + 1))
    assert sorted(p.template for p in history) == sorted(f"text {i}" for i in range(count))


def test_concurrent_identical_saves_create_one_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filesystem, "LOCK_TIMEOUT", 120.0)
    count = 4
    barrier = threading.Barrier(count)

    def worker() -> None:
        barrier.wait()
        PromptWhere(tmp_path).save("chatbot", "same")

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [p.version for p in PromptWhere(tmp_path).history("chatbot")] == [1]


# --- folders without versions ----------------------------------------------------


def test_folder_without_versions_is_not_a_prompt(tmp_path: Path) -> None:
    store = PromptWhere(tmp_path)
    (tmp_path / "empty").mkdir()
    assert store.list() == []
    assert store.save("empty", "x").version == 1
    assert store.list() == ["empty"]
