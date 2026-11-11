# promptwhere — Design

A basic, easy-to-use, hassle-free prompt management library for Python.
Users name their prompts (e.g. `"chatbot"`), save new versions as they edit them,
and can always see and fetch every past version.


## Goals

1. **Easy usage.** A user should learn the whole library from the README in about 60 seconds.
2. **Named prompts with versions.** Each prompt has a unique name and any number of versions.
3. **Edit → next version.** Editing a prompt and saving it creates the next version under the same name.
4. **Full history.** All versions and their details are available for the project.
5. **Simple saving.** One call saves a prompt; no setup, server, or database.

## Non-goals (v1)

Do not build these in v1. They make similar tools heavy.

- Hosted server, remote access, or any UI reachable from another machine
- User accounts or permissions
- Evals, A/B testing, analytics
- Integration with any specific LLM provider

A **local-only UI** launched from the CLI (`prompts ui`) is allowed; see "UI".

The backend interface and labels leave room to add some of these later.

---

## Data model

```
Project (a store = a folder)
 └── Prompt   (unique name, e.g. "chatbot")
      └── Version (1, 2, 3, …)   ← immutable
```

### Version

| Field          | Type            | Notes                                                    |
|----------------|-----------------|----------------------------------------------------------|
| `version`      | `int`           | Starts at 1, increments automatically per prompt.        |
| `template`     | `str`           | The prompt text.                                         |
| `created_at`   | `datetime`      | UTC, ISO 8601 on disk.                                   |
| `message`      | `str \| None`   | Optional note, like a commit message.                    |
| `content_hash` | `str`           | SHA-256 of `template`. Used to skip unchanged saves.     |
| `metadata`     | `dict`          | Optional, free-form (model, temperature, author, …).     |

**Rule: versions are immutable.** Once saved, a version is never modified or
overwritten. "Editing" a prompt always means saving a new version.

### Labels

Named pointers from a label to a version number, per prompt
(e.g. `production → 2`, `staging → 3`).

- Apps can fetch `"chatbot"` by label instead of a hard-coded version.
- Promoting = moving a label forward. Rolling back = moving it back.
- Moving a label never changes any version.

### Prompt names

- Lowercase letters, digits, `-` and `_`. Must start with a letter or digit.
- Validated on save. Invalid names raise a clear error.
- Names map directly to folder names, so validation also keeps paths safe.

---

## Storage

### Default: filesystem backend

Plain files inside the user's project, so prompts are git-friendly,
human-readable, and ship with the app.

```
prompts/                 # store root, default "./prompts"
  chatbot/
    v1.yaml
    v2.yaml
    v3.yaml
    _labels.yaml         # { production: 2, staging: 3 }
  summarizer/
    v1.yaml
```

Version file format (YAML, so multi-line prompts stay readable):

```yaml
version: 3
created_at: 2026-11-03T10:15:00Z
message: Made tone more formal
content_hash: sha256:…
metadata:
  model: some-model
template: |
  You are a helpful assistant for {company}.
  Answer the user's question politely.
```

- The store folder is created automatically if it does not exist.
- **Writes are atomic:** write to a temp file in the same folder, then rename.
- Saving refuses to overwrite an existing version file.
- Use a simple lock file (`_lock`, created exclusively) per prompt when assigning
  the next version number, so two processes saving at once cannot both create the
  same version. If the lock cannot be acquired within a timeout, raise
  `LockTimeout` explaining how to remove a stale lock file.
- `save_version` raises `VersionExists` rather than overwrite an existing version
  file (the file is published with an atomic no-overwrite link, not a plain rename).
- A prompt folder with no version files is not a prompt (it is ignored by `list`).

### Backend interface

All storage goes through one small interface. The public API never touches
files directly.

```
lock(name) -> context manager   # exclusive per-prompt lock; held while assigning a version
save_version(name, version_record)
get_version(name, version) -> VersionRecord
list_versions(name) -> list[VersionRecord]
list_prompts() -> list[str]
get_labels(name) -> dict[str, int]
set_label(name, label, version)
```

v1 ships only `FileSystemBackend`. Later options: SQLite, Postgres, S3.

---

## Public API

Keep it minimal. Adding a public function or parameter is a design change.

| Call | Behavior |
|------|----------|
| `PromptWhere(path="./prompts")` | Open (and create if needed) a store. The store holds many prompts; each is addressed by name in the methods below. |
| `save(name, text, message=None, metadata=None)` | Creates the prompt if new, otherwise saves the next version. Returns the `Prompt` saved. If `text` equals the latest version's text, saves nothing and returns the latest version. |
| `get(name, version=None, label=None)` | Latest by default. `version` and `label` are mutually exclusive. |
| `history(name)` | All versions, oldest first, with metadata. |
| `list()` | All prompt names in the store. |
| `diff(name, a, b)` | Unified diff between two versions (`difflib`). |
| `render(name, version=None, label=None, **variables)` | Fetch and fill template variables. |
| `set_label(name, label, version)` | Point a label at a version. |
| `labels(name)` | Current labels for a prompt. |

### Returned object

`get()` and `save()` return a small immutable `Prompt` object with
`name`, `version`, `template`, `created_at`, `message`, `metadata`.

- `str(prompt)` returns the template text, so beginners can pass it straight
  to an LLM call.
- `prompt.render(**variables)` fills in variables.
- `prompt.variables` lists the variable names found in the template.

### Edit flow

There is no separate "edit" concept:

```
get("chatbot")  →  change the text  →  save("chatbot", new_text)  →  version N+1
```

### Errors

One base exception plus a few specific ones, all with helpful messages:

- `PromptNotFound`: include a "did you mean …?" suggestion (`difflib.get_close_matches`).
- `VersionNotFound`, `LabelNotFound`
- `InvalidPromptName`
- `VersionExists`, `LockTimeout`: storage safety errors (see Storage).
- `MissingVariables`: list exactly which variables were not provided.

---

## Templating

- **Core:** Python `{variable}` syntax via `str.format`-style parsing. No dependencies.
- **Optional:** Jinja2 for loops and conditionals, installed with
  `pip install promptwhere[jinja]`. Never imported by the core unless requested.
- Detect variables in a template and raise `MissingVariables` at render time
  when any are missing.

---

## CLI

Installed as a `prompts` command. Thin layer over the public API; no logic of its own.

A global `--path DIR` option (before the command, default `./prompts`) selects
the store folder, mirroring `PromptWhere(path=...)`.

```
prompts [--path DIR] <command>
prompts list
prompts show chatbot [--version 2 | --label production]
prompts history chatbot
prompts edit chatbot [-m "message"]   # opens latest in $EDITOR; saving creates next version
prompts diff chatbot 2 3
prompts label chatbot production 3
prompts ui [--port N] [--no-browser]  # launches the local UI (see "UI")
```

`edit` does nothing if the file is unchanged or empty after the editor closes.
`ui` only starts the UI server for the selected `--path`; it has no other logic.

---

## UI

A local, browser-based UI to see the prompts in a project. It follows every
rule above: versions are immutable, labels are pointers, storage goes through
the backend.

- **Launch:** `prompts ui`. Python standard library only (`http.server`); no new
  dependencies. Serves one bundled static HTML/JS page plus a small JSON API.
- **Internal module:** `promptwhere.ui`, imported lazily by the CLI. It is *not*
  part of the public API (no new export from `promptwhere`). Making it public is
  a design change.
- **Layering:** the server calls only the public `PromptWhere` API
  (`list`, `history`, `get`, `diff`, `labels`, `render`). It never touches files.
  The CLI command only starts it.
- **Local only:**
  - Binds to `127.0.0.1`.
  - A random per-launch token is required in the URL.
  - Host and Origin headers are checked (blocks DNS rebinding and cross-site requests).
- **Screens:** prompt list with search; prompt view with version timeline, labels
  and metadata; diff between two versions; render preview with variables.
- **Errors:** library error messages are shown unchanged.

### Phases

- **7a (first release): read-only.** GET endpoints only; no endpoint can create
  or change anything.
- **7b: write path.** New prompt, new version (an "edit" is always a new
  version, never in place), move label, and a warning if the latest version
  changed since the edit began. There is still no update or delete of versions.
- **7c: polish.** Variable highlighting, keyboard shortcuts.

Out of scope for the UI, as for the library: accounts, hosting, evals, LLM
playgrounds.

---

## Decisions

1. **Integer version numbers.** Friendly and readable. Known tradeoff: two git
   branches can both create `v4`, causing a merge conflict. Documented, not solved.
2. **Pinning in production.** "Latest" is convenient in development but changes
   behavior silently. Docs encourage pinning a version or label in production code.
3. **Text-only prompts in v1.** The version format must allow adding a
   `messages` field (list of role/content) later without breaking existing files.
4. **Unchanged saves are skipped** using `content_hash`, so history stays meaningful.
5. **Filesystem storage by default**, behind a backend interface.

---

## Build order

Implement one phase at a time, with tests, before starting the next.

1. **Core:** data model, `FileSystemBackend`, `save` / `get` / `history` / `list`, name validation, errors.
2. **Safety:** content-hash dedupe, atomic writes, no-overwrite, per-prompt locking.
3. **Templating:** variable detection, `render`, `MissingVariables`.
4. **Labels:** `set_label`, `labels`, `get(label=…)`.
5. **CLI:** `list`, `show`, `history`, `edit`, `diff`, `label`.
6. **Extras:** `diff` polish, optional Jinja2, additional backends.
7. **UI** (see "UI"): 7a read-only viewer, 7b write path, 7c polish.

## Key behaviors to test

- Saving a new name creates version 1; saving again creates version 2.
- Saving identical text creates no new version.
- An existing version file is never overwritten or modified.
- `get()` with no arguments returns the latest version.
- `history()` returns all versions in order.
- Missing template variables raise `MissingVariables` naming them.
- Moving a label does not change any version.
- Invalid names (e.g. `../x`, empty, uppercase) are rejected.

UI (phase 7a):

- The UI server binds to loopback only.
- Requests with a missing or wrong token, or a bad Host/Origin, are rejected.
- Any non-GET request is rejected, and no UI request changes any file in the store.
- The UI returns the same data as `list`, `history`, `get`, `diff`, `labels` and `render`.
