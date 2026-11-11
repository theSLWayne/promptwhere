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
) -> tuple[int, dict[str, str], bytes]:
    sent = dict(headers or {})
    if token == "default":
        token = srv.token
    if token is not None:
        sent.setdefault("X-Token", token)
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        conn.request(method, path, headers=sent)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def api(srv: _UIServer, path: str) -> tuple[int, Any]:
    status, _, body = request(srv, "/api" + path)
    return status, json.loads(body)


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


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_only_get_is_allowed(server: _UIServer, method: str) -> None:
    status, headers, _ = request(server, "/api/prompts/chatbot", method)
    assert status == 405 and headers["Allow"] == "GET"


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
    for method in ["POST", "PUT", "DELETE", "PATCH"]:
        request(server, "/api/prompts/chatbot", method)
    assert snapshot(root) == before


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
