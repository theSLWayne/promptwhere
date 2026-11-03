# promptwhere

Named, versioned prompts for Python, stored as plain YAML files in your project.
No server, no database, no setup.

```bash
pip install promptwhere
```

## 60-second tour

```python
from promptwhere import PromptWhere

store = PromptWhere()  # opens (or creates) ./prompts

store.save("chatbot", "You are a helpful assistant.")  # -> version 1
store.save("chatbot", "You are a formal assistant.", message="Tone")  # -> version 2

prompt = store.get("chatbot")  # latest version
print(prompt)  # str(prompt) is the template text
print(prompt.version, prompt.message)  # 2 Tone

store.get("chatbot", version=1)  # any past version
store.history("chatbot")  # every version, oldest first
store.list()  # ['chatbot']
```

### Editing

There is no separate "edit": get the prompt, change the text, save it again.

```python
text = store.get("chatbot").template
store.save("chatbot", text + "\nAnswer briefly.")  # -> version 3
```

Saving text identical to the latest version does nothing and returns that
version, so your history only records real changes.

### Metadata

```python
store.save(
    "chatbot",
    "…",
    message="Lower temperature",
    metadata={"model": "some-model", "temperature": 0.2},
)
```

A returned `Prompt` has `name`, `version`, `template`, `created_at` (UTC),
`message` and `metadata`. It is immutable.

### Variables and rendering

Templates use Python `{variable}` syntax, with no extra dependencies.

```python
store.save("greeter", "Hello {name}, welcome to {company}!")

store.render("greeter", name="Ada", company="Acme")  # 'Hello Ada, welcome to Acme!'
store.render("greeter", version=1, name="Ada", company="Acme")  # a specific version

prompt = store.get("greeter")
prompt.variables  # ['name', 'company']
prompt.render(name="Ada", company="Acme")  # same as store.render(...)
```

- Forgetting a variable raises `MissingVariables`, which names exactly what is
  missing. Extra variables are ignored.
- Write a literal brace as `{{` or `}}`, e.g. JSON in a prompt:
  `Reply as {{"answer": "{x}"}}`. Rendering turns that into `Reply as {"answer": "42"}`.
  An unescaped `{"a": 1}`, an empty `{}` or a numbered `{0}` raises a `ValueError`
  that says how to fix it.
- Format specs work (`{price:.2f}`), and `{user.name}` counts as the variable `user`.
- `render` takes the prompt name positionally, so a `{name}` variable is fine. A
  variable called `version` can't be passed to `store.render`; use
  `store.get("p").render(version=...)` instead.

## Rules

- **Names** use lowercase letters, digits, `-` and `_`, and start with a letter or
  digit (`chatbot`, `support-bot_2`). Anything else raises `InvalidPromptName`.
- **Versions are immutable.** A saved version is never modified or overwritten;
  editing always creates the next version.
- **Pin in production.** `get("chatbot")` returns the latest version, which is
  handy in development but changes behavior silently when someone saves a new one.
  In production code, pin a version: `get("chatbot", version=2)`.

## Where files go

```
prompts/
  chatbot/
    v1.yaml
    v2.yaml
  summarizer/
    v1.yaml
```

```yaml
version: 2
created_at: 2026-11-03T10:15:00.000000Z
message: Tone
content_hash: sha256:…
metadata: {}
template: |
  You are a formal assistant.
```

The files are readable and diff well in git, so commit them with your code.

## Safe saving

- Each version is written to a temporary file and then moved into place, so a
  crash never leaves a half-written version.
- Saving never overwrites an existing version file (`VersionExists`).
- A per-prompt lock file (`_lock`) stops two processes saving at once from
  creating the same version number. If a crashed save leaves it behind, you get
  a `LockTimeout` after 10 seconds that names the file to delete.

## Errors

All errors inherit from `PromptWhereError`.

| Error | When |
|-------|------|
| `InvalidPromptName` | The name breaks the naming rules. |
| `PromptNotFound` | No such prompt; suggests close matches ("did you mean …?"). |
| `VersionNotFound` | The prompt exists but not that version; lists the available ones. |
| `MissingVariables` | `render` was called without a variable the template uses; lists them. |
| `VersionExists` | Something tried to overwrite a saved version. |
| `LockTimeout` | Another process held the prompt's lock too long. |

## Known limitation

Version numbers are plain integers. If two git branches both save a new version
of the same prompt, both create the same `vN.yaml` and git reports a merge
conflict. This is documented, not solved.

## Status

Under development. Not yet available: labels (`production` → version), optional
Jinja2 templates and the `prompts` command line tool.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```
