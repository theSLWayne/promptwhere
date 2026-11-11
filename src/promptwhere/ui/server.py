"""The UI server (phase 7b: read and write).

Uses only the standard library and the public ``PromptWhere`` API. It never
touches files itself. GET reads; POST on three endpoints saves a new prompt,
saves a new version, or moves a label. Nothing updates or deletes a version.
"""

from __future__ import annotations

import hmac
import json
import secrets
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from ..core import PromptWhere
from ..errors import LabelNotFound, PromptNotFound, PromptWhereError, VersionNotFound
from ..models import Prompt

_HOST = "127.0.0.1"
_TOKEN_HEADER = "X-Token"
_VAR_PREFIX = "var."
_NOT_FOUND = (PromptNotFound, VersionNotFound, LabelNotFound)
_MAX_BODY = 1_000_000

Query = dict[str, list[str]]
Body = dict[str, Any]


class _Conflict(Exception):
    """A write that was refused because of the current state (HTTP 409)."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


def _text_field(body: Body, key: str, *, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Field {key!r} must be a string in the request body.")  # noqa: TRY004
    return value


def _int_field(body: Body, key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Field {key!r} must be a whole number in the request body.")  # noqa: TRY004
    return value


def _prompt_json(prompt: Prompt) -> dict[str, Any]:
    return {
        "name": prompt.name,
        "version": prompt.version,
        "template": prompt.template,
        "created_at": prompt.created_at.isoformat(),
        "message": prompt.message,
        "metadata": prompt.metadata,
        "variables": prompt.variables,
    }


def _optional_int(query: Query, key: str) -> int | None:
    if key not in query:
        return None
    value = query[key][0]
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"Query parameter {key!r} must be a whole number, got {value!r}."
        ) from None


def _required_int(query: Query, key: str) -> int:
    number = _optional_int(query, key)
    if number is None:
        raise ValueError(f"Missing query parameter {key!r}, e.g. ?{key}=1.")
    return number


def _message(body: Body) -> str | None:
    return _text_field(body, "message", required=False) or None


class _Handler(BaseHTTPRequestHandler):
    server_version = "promptwhere-ui"

    @property
    def _ui(self) -> _UIServer:
        return cast("_UIServer", self.server)

    def log_message(self, format: str, *args: Any) -> None:
        """Stay quiet: request lines would print the access token."""

    # --- helpers ---------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _host_and_origin_ok(self) -> bool:
        if self.headers.get("Host") not in self._ui.allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in self._ui.allowed_hosts}

    def _token_ok(self, supplied: str | None) -> bool:
        return supplied is not None and hmac.compare_digest(supplied, self._ui.token)

    # --- methods -----------------------------------------------------------------

    def _method_not_allowed(self) -> None:
        self._send(
            HTTPStatus.METHOD_NOT_ALLOWED,
            json.dumps(
                {"error": "Only GET and POST are allowed. Versions can't be changed or deleted."}
            ).encode(),
            "application/json; charset=utf-8",
            Allow="GET, POST",
        )

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _method_not_allowed

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        if not self._host_and_origin_ok() or origin is None:
            self._error(HTTPStatus.FORBIDDEN, "Writes need a matching Origin header.")
            return
        if not self.path.startswith("/api/"):
            self._error(HTTPStatus.NOT_FOUND, "Not found.")
            return
        if not self._token_ok(self.headers.get(_TOKEN_HEADER)):
            self._error(HTTPStatus.UNAUTHORIZED, f"Missing or wrong {_TOKEN_HEADER} header.")
            return
        if self.headers.get_content_type() != "application/json":
            self._error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "Send the body as Content-Type: application/json.",
            )
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(HTTPStatus.LENGTH_REQUIRED, "A Content-Length header is required.")
            return
        if length < 0 or length > _MAX_BODY:
            self._error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"The request body must be at most {_MAX_BODY} bytes.",
            )
            return
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "The request body must be valid JSON.")
            return
        if not isinstance(body, dict):
            self._error(HTTPStatus.BAD_REQUEST, "The request body must be a JSON object.")
            return
        segments = [unquote(s) for s in urlsplit(self.path).path.split("/")[2:]]
        self._run(lambda: self._write(segments, body))

    def do_GET(self) -> None:
        if not self._host_and_origin_ok():
            self._error(HTTPStatus.FORBIDDEN, "Unexpected Host or Origin header.")
            return
        parts = urlsplit(self.path)
        query = parse_qs(parts.query, keep_blank_values=True)
        if parts.path == "/":
            self._page(query)
        elif parts.path.startswith("/api/"):
            self._api(parts.path, query)
        else:
            self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def _page(self, query: Query) -> None:
        if not self._token_ok(query.get("token", [None])[0]):
            self._error(
                HTTPStatus.FORBIDDEN,
                "Missing or wrong token. Open the full URL printed by `prompts ui`.",
            )
            return
        html = resources.files("promptwhere.ui").joinpath("static/index.html").read_text("utf-8")
        self._send(
            HTTPStatus.OK,
            html.encode("utf-8"),
            "text/html; charset=utf-8",
            Content_Security_Policy=(
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'"
            ),
        )

    def _api(self, path: str, query: Query) -> None:
        if not self._token_ok(self.headers.get(_TOKEN_HEADER)):
            self._error(HTTPStatus.UNAUTHORIZED, f"Missing or wrong {_TOKEN_HEADER} header.")
            return
        segments = [unquote(s) for s in path.split("/")[2:]]
        self._run(lambda: self._route(segments, query))

    def _run(self, action: Callable[[], dict[str, Any]]) -> None:
        try:
            self._json(action())
        except _NOT_FOUND as error:
            self._error(HTTPStatus.NOT_FOUND, str(error))
        except _Conflict as error:
            self._json({"error": str(error), **error.extra}, HTTPStatus.CONFLICT)
        except (PromptWhereError, ValueError) as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
        except (OSError, yaml.YAMLError) as error:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not use the store: {error}")

    def _write(self, segments: list[str], body: Body) -> dict[str, Any]:
        store = self._ui.store
        if segments == ["prompts"]:
            name = cast("str", _text_field(body, "name"))
            if name in store.list():
                raise _Conflict(
                    f"Prompt {name!r} already exists. Open it and save a new version instead."
                )
            saved = store.save(name, cast("str", _text_field(body, "text")), _message(body))
            return {**_prompt_json(saved), "created": True}
        if len(segments) == 3 and segments[0] == "prompts":
            name = segments[1]
            if segments[2] == "versions":
                text = cast("str", _text_field(body, "text"))
                base = _int_field(body, "base_version")
                latest = store.history(name)[-1]
                if base != latest.version and body.get("force") is not True:
                    raise _Conflict(
                        f"{name!r} changed: version {latest.version} was saved since you "
                        f"started editing version {base}. Review it, then save anyway or reload.",
                        latest=_prompt_json(latest),
                    )
                saved = store.save(name, text, _message(body), dict(latest.metadata))
                return {**_prompt_json(saved), "created": saved.version != latest.version}
            if segments[2] == "labels":
                label = cast("str", _text_field(body, "label"))
                store.set_label(name, label, _int_field(body, "version"))
                return {"labels": store.labels(name)}
        raise ValueError("Unknown API path. See docs/DESIGN.md, section UI.")

    def _route(self, segments: list[str], query: Query) -> dict[str, Any]:
        store = self._ui.store
        if segments == ["prompts"]:
            return {"prompts": store.list()}
        if len(segments) >= 2 and segments[0] == "prompts":
            name = segments[1]
            action = segments[2] if len(segments) == 3 else None
            if len(segments) == 2:
                return {
                    "name": name,
                    "versions": [_prompt_json(p) for p in store.history(name)],
                    "labels": store.labels(name),
                }
            version, label = _optional_int(query, "version"), query.get("label", [None])[0]
            if action == "get":
                return _prompt_json(store.get(name, version, label))
            if action == "diff":
                return {
                    "diff": store.diff(name, _required_int(query, "a"), _required_int(query, "b"))
                }
            if action == "render":
                values = {
                    key[len(_VAR_PREFIX) :]: found[0]
                    for key, found in query.items()
                    if key.startswith(_VAR_PREFIX)
                }
                return {"text": store.get(name, version, label).render(**values)}
        raise ValueError("Unknown API path. See docs/DESIGN.md, section UI.")


class _UIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, store: PromptWhere, port: int) -> None:
        super().__init__((_HOST, port), _Handler)
        self.store = store
        self.token = secrets.token_urlsafe(16)
        actual = self.server_address[1]
        self.allowed_hosts = {f"{_HOST}:{actual}", f"localhost:{actual}"}

    @property
    def url(self) -> str:
        return f"http://{_HOST}:{self.server_address[1]}/?token={self.token}"


def make_server(store: PromptWhere, port: int = 0) -> _UIServer:
    """Create (but do not start) a loopback-only UI server. ``port=0`` picks a free port."""
    return _UIServer(store, port)


def serve(store: PromptWhere, port: int = 0, open_browser: bool = True) -> None:
    """Run the UI until interrupted with Ctrl+C."""
    server = make_server(store, port)
    print(f"promptwhere UI:{server.url}\nPress Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
