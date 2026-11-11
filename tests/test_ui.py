import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from promptwhere import PromptWhere
from promptwhere.cli import main
from promptwhere.ui.server import _UIServer, make_server


@pytest.fixture
def store(tmp_path: Path) -> PromptWhere:
    s = PromptWhere(tmp_path / "prompts")
    s.save("chatbot", "Hello {user}\nline two\n", message="first", metadata={"model": "m1"})
    s.save("chatbot", "Hello {user}\nline 2\n", message="second")
    s.set_label("chatbot", "production", 1)
    return s


@pytest.fixture
def server(store: PromptWhere) -> Iterator[_UIServer]:
    srv = make_server(store)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join()


def request(
    srv: _UIServer,
    path: str,
    method: str = "GET",
    *,
    token: str | None = "default",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    sent = dict(headers or {})
    if token == "default":
        token = srv.token
    if token is not None:
        sent.setdefault("X-Token", token)
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        conn.request(method, path, body=body, headers=sent)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def api(srv: _UIServer, path: str) -> tuple[int, Any]:
    status, _, body = request(srv, "/api" + path)
    return status, json.loads(body)


def post(
    srv: _UIServer,
    path: str,
    payload: Any,
    *,
    token: str | None = "default",
    headers: dict[str, str] | None = None,
    raw: bytes | None = None,
) -> tuple[int, Any]:
    sent = {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{srv.server_address[1]}",
        **(headers or {}),
    }
    body = raw if raw is not None else json.dumps(payload).encode()
    status, _, data = request(srv, "/api" + path, "POST", token=token, headers=sent, body=body)
    return status, json.loads(data)


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


# --- local-only and access control ---------------------------------------------------


def test_binds_to_loopback_only(server: _UIServer) -> None:
    assert server.server_address[0] == "127.0.0.1"
    assert server.url.startswith("http://127.0.0.1:")


def test_page_needs_the_token(server: _UIServer) -> None:
    assert request(server, "/", token=None)[0] == 403
    assert request(server, "/?token=wrong", token=None)[0] == 403
    status, headers, body = request(server, f"/?token={server.token}", token=None)
    assert status == 200 and b"promptwhere" in body
    assert "default-src 'none'" in headers["Content-Security-Policy"]


def test_api_needs_the_token(server: _UIServer) -> None:
    assert request(server, "/api/prompts", token=None)[0] == 401
    assert request(server, "/api/prompts", token="wrong")[0] == 401
    assert request(server, f"/api/prompts?token={server.token}", token=None)[0] == 401


@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", "127.0.0.1:1"])
def test_bad_host_header_is_rejected(server: _UIServer, host: str) -> None:
    assert request(server, "/api/prompts", headers={"Host": host})[0] == 403


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "https://127.0.0.1"])
def test_bad_origin_header_is_rejected(server: _UIServer, origin: str) -> None:
    assert request(server, "/api/prompts", headers={"Origin": origin})[0] == 403


def test_localhost_host_and_own_origin_are_accepted(server: _UIServer) -> None:
    port = server.server_address[1]
    status, _, _ = request(
        server,
        "/api/prompts",
        headers={"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}"},
    )
    assert status == 200


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_only_get_and_post_are_allowed(server: _UIServer, method: str) -> None:
    status, headers, _ = request(server, "/api/prompts/chatbot", method)
    assert status == 405 and headers["Allow"] == "GET, POST"


def test_unknown_paths(server: _UIServer) -> None:
    assert request(server, "/nope")[0] == 404
    assert api(server, "/nope")[0] == 400
    assert api(server, "/prompts/chatbot/nope")[0] == 400


def test_no_request_changes_the_store(
    server: _UIServer, store: PromptWhere, tmp_path: Path
) -> None:
    root = tmp_path / "prompts"
    before = snapshot(root)
    for path in [
        "/prompts",
        "/prompts/chatbot",
        "/prompts/chatbot/get?version=1",
        "/prompts/chatbot/get?label=production",
        "/prompts/chatbot/diff?a=1&b=2",
        "/prompts/chatbot/render?var.user=Ann",
        "/prompts/missing",
    ]:
        api(server, path)
    for method in ["PUT", "DELETE", "PATCH"]:
        request(server, "/api/prompts/chatbot", method)
    assert snapshot(root) == before


# --- writes (phase 7b) -----------------------------------------------------------------


def test_new_prompt_creates_version_1(server: _UIServer, store: PromptWhere) -> None:
    status, data = post(server, "/prompts", {"name": "fresh", "text": "Hi", "message": "first"})
    assert status == 200 and data["version"] == 1 and data["created"] is True
    saved = store.get("fresh")
    assert (saved.template, saved.message) == ("Hi", "first")


def test_new_prompt_with_existing_name_is_a_409(
    server: _UIServer, store: PromptWhere, tmp_path: Path
) -> None:
    before = snapshot(tmp_path / "prompts")
    status, data = post(server, "/prompts", {"name": "chatbot", "text": "other"})
    assert status == 409 and "already exists" in data["error"]
    assert snapshot(tmp_path / "prompts") == before


def test_new_prompt_with_invalid_name_shows_library_message(server: _UIServer) -> None:
    status, data = post(server, "/prompts", {"name": "../x", "text": "Hi"})
    assert status == 400 and "name" in data["error"].lower()


def test_new_version_never_touches_existing_files(
    server: _UIServer, store: PromptWhere, tmp_path: Path
) -> None:
    before = snapshot(tmp_path / "prompts")
    body = {"text": "Brand new {user}", "message": "third", "base_version": 2}
    status, data = post(server, "/prompts/chatbot/versions", body)
    assert status == 200 and data["version"] == 3 and data["created"] is True
    after = snapshot(tmp_path / "prompts")
    assert {k: v for k, v in after.items() if k in before} == before
    assert sorted(set(after) - set(before)) == [str(Path("chatbot") / "v3.yaml")]
    assert store.get("chatbot").message == "third"


def test_new_version_carries_over_metadata(server: _UIServer, store: PromptWhere) -> None:
    store.save("meta", "one", metadata={"model": "m1"})
    post(server, "/prompts/meta/versions", {"text": "two", "base_version": 1})
    assert store.get("meta").metadata == {"model": "m1"}


def test_unchanged_text_creates_nothing(server: _UIServer, store: PromptWhere) -> None:
    same = store.get("chatbot").template
    status, data = post(server, "/prompts/chatbot/versions", {"text": same, "base_version": 2})
    assert status == 200 and data["created"] is False and data["version"] == 2
    assert len(store.history("chatbot")) == 2


def test_stale_edit_is_blocked_then_forced(
    server: _UIServer, store: PromptWhere, tmp_path: Path
) -> None:
    store.save("chatbot", "someone else was here")  # v3 while the editor started at v2
    before = snapshot(tmp_path / "prompts")
    body = {"text": "my edit", "base_version": 2}
    status, data = post(server, "/prompts/chatbot/versions", body)
    assert status == 409 and data["latest"]["version"] == 3
    assert data["latest"]["template"] == "someone else was here"
    assert snapshot(tmp_path / "prompts") == before
    status, data = post(server, "/prompts/chatbot/versions", {**body, "force": True})
    assert status == 200 and data["version"] == 4
    assert store.get("chatbot", 3).template == "someone else was here"


def test_new_version_of_missing_prompt_is_404(server: _UIServer) -> None:
    status, data = post(server, "/prompts/chatbt/versions", {"text": "x", "base_version": 1})
    assert status == 404 and "Did you mean 'chatbot'" in data["error"]


def test_move_label_changes_no_version(
    server: _UIServer, store: PromptWhere, tmp_path: Path
) -> None:
    root = tmp_path / "prompts"
    before = snapshot(root)
    status, data = post(server, "/prompts/chatbot/labels", {"label": "production", "version": 2})
    assert status == 200 and data["labels"] == {"production": 2}
    after = snapshot(root)
    changed = {k for k in after if after[k] != before.get(k)}
    assert changed == {str(Path("chatbot") / "_labels.yaml")}


def test_move_label_to_missing_version_is_404(server: _UIServer) -> None:
    body = {"label": "production", "version": 9}
    assert post(server, "/prompts/chatbot/labels", body)[0] == 404


@pytest.mark.parametrize(
    "path, payload",
    [
        ("/prompts", {"name": "x"}),
        ("/prompts", {"name": "x", "text": 5}),
        ("/prompts/chatbot/versions", {"text": "x"}),
        ("/prompts/chatbot/versions", {"text": "x", "base_version": "2"}),
        ("/prompts/chatbot/labels", {"label": "a", "version": True}),
        ("/prompts/chatbot/nope", {}),
        ("/prompts/chatbot", {}),
    ],
)
def test_bad_write_bodies_are_400(server: _UIServer, path: str, payload: dict[str, Any]) -> None:
    assert post(server, path, payload)[0] == 400


def test_writes_are_guarded(server: _UIServer, tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    before = snapshot(root)
    good = {"name": "evil", "text": "x"}
    port = server.server_address[1]
    assert post(server, "/prompts", good, token=None)[0] == 401
    assert post(server, "/prompts", good, token="wrong")[0] == 401
    assert post(server, "/prompts", good, headers={"Origin": "http://evil.example"})[0] == 403
    assert (
        post(server, "/prompts", good, headers={"Origin": f"http://127.0.0.1:{port + 1}"})[0] == 403
    )
    assert post(server, "/prompts", good, headers={"Content-Type": "text/plain"})[0] == 415
    assert post(server, "/prompts", None, raw=b"{not json")[0] == 400
    assert post(server, "/prompts", None, raw=b"[1, 2]")[0] == 400
    assert post(server, "/prompts", None, raw=b"x", headers={"Content-Length": "1000001"})[0] == 413
    assert snapshot(root) == before


def test_write_without_origin_is_rejected(server: _UIServer, tmp_path: Path) -> None:
    before = snapshot(tmp_path / "prompts")
    status, _, _ = request(
        server,
        "/api/prompts",
        "POST",
        headers={"Content-Type": "application/json"},
        body=b'{"name": "evil", "text": "x"}',
    )
    assert status == 403
    assert snapshot(tmp_path / "prompts") == before


# --- data matches the public API -------------------------------------------------------


def test_list(server: _UIServer, store: PromptWhere) -> None:
    store.save("another", "x")
    assert api(server, "/prompts") == (200, {"prompts": ["another", "chatbot"]})


def test_history_and_labels(server: _UIServer, store: PromptWhere) -> None:
    status, data = api(server, "/prompts/chatbot")
    assert status == 200
    assert data["name"] == "chatbot"
    assert data["labels"] == {"production": 1}
    assert [v["version"] for v in data["versions"]] == [1, 2]
    first = store.history("chatbot")[0]
    assert data["versions"][0] == {
        "name": "chatbot",
        "version": 1,
        "template": first.template,
        "created_at": first.created_at.isoformat(),
        "message": "first",
        "metadata": {"model": "m1"},
        "variables": ["user"],
    }


def test_get_latest_version_and_label(server: _UIServer) -> None:
    assert api(server, "/prompts/chatbot/get")[1]["version"] == 2
    assert (
        api(server, "/prompts/chatbot/get?version=1")[1]["template"] == "Hello {user}\nline two\n"
    )
    assert api(server, "/prompts/chatbot/get?label=production")[1]["version"] == 1


def test_get_version_and_label_together_is_a_400(server: _UIServer) -> None:
    status, data = api(server, "/prompts/chatbot/get?version=1&label=production")
    assert status == 400 and "not both" in data["error"]


def test_diff(server: _UIServer, store: PromptWhere) -> None:
    status, data = api(server, "/prompts/chatbot/diff?a=1&b=2")
    assert status == 200 and data["diff"] == store.diff("chatbot", 1, 2)
    assert api(server, "/prompts/chatbot/diff?a=1")[0] == 400
    assert api(server, "/prompts/chatbot/diff?a=x&b=2")[0] == 400
    assert api(server, "/prompts/chatbot/diff?a=1&b=9")[0] == 404


def test_render(server: _UIServer) -> None:
    status, data = api(server, "/prompts/chatbot/render?version=1&var.user=Ann")
    assert status == 200 and data["text"] == "Hello Ann\nline two\n"


def test_render_missing_variables_shows_library_message(server: _UIServer) -> None:
    status, data = api(server, "/prompts/chatbot/render")
    assert status == 400 and "user" in data["error"]


def test_not_found_errors_keep_the_library_message(server: _UIServer) -> None:
    status, data = api(server, "/prompts/chatbt")
    assert status == 404 and "Did you mean 'chatbot'" in data["error"]
    assert api(server, "/prompts/chatbot/get?version=9")[0] == 404
    assert api(server, "/prompts/chatbot/get?label=nope")[0] == 404


@pytest.mark.parametrize("name", ["..%2Fx", "Chatbot", ".."])
def test_invalid_names_are_rejected(server: _UIServer, name: str) -> None:
    assert api(server, f"/prompts/{name}")[0] == 400


# --- CLI ------------------------------------------------------------------------------


def test_cli_ui_command_launches_the_server(
    store: PromptWhere, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[PromptWhere, int, bool]] = []

    def fake_serve(s: PromptWhere, port: int = 0, open_browser: bool = True) -> None:
        calls.append((s, port, open_browser))

    monkeypatch.setattr("promptwhere.ui.server.serve", fake_serve)
    path = str(tmp_path / "prompts")
    assert main(["--path", path, "ui", "--port", "8123", "--no-browser"]) == 0
    assert main(["--path", path, "ui"]) == 0
    assert [(port, browser) for _, port, browser in calls] == [(8123, False), (0, True)]
