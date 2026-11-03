# CLAUDE.md

# promptwhere

A basic, easy-to-use Python library for managing named, versioned prompts.
Prompts are stored as plain YAML files in the user's project.

Full architecture, API and build order: @docs/DESIGN.md
Read it before making any design-level change.

## Non-negotiable rules

- **Versions are immutable.** Never modify or overwrite a saved version. An edit always creates a new version.
- **Keep the public API minimal.** Ask before adding a public function, class or parameter.
- **No required dependencies beyond PyYAML in the core.** Jinja2 and anything else are optional extras, imported lazily.
- **All storage goes through the backend interface.** The API layer never touches files directly.
- **Writes are atomic:** write to a temp file in the same folder, then rename.
- **The CLI is a thin layer over the public API**, with no logic of its own.
- **Stay in scope:** no web UI, server, accounts, evals, or LLM-provider integrations.
- If a change conflicts with docs/DESIGN.md, stop and ask. When a decision changes, update DESIGN.md first.

## Workflow

- Work one build phase at a time (see "Build order" in DESIGN.md).
- Every behavior change comes with tests. The "Key behaviors to test" list in DESIGN.md must always pass.
- Run tests, lint and type checks before saying a task is done.

## Commands

```bash
pip install -e ".[dev]"   # install with dev tools
pytest                    # run tests
ruff check .              # lint
ruff format .             # format
mypy src                  # type check
```

## Conventions

- Python 3.10+, `src/` layout: `src/promptwhere/`, tests in `tests/`.
- Full type hints on all public functions. Google-style docstrings on public API.
- Prefer the standard library (`pathlib`, `dataclasses`, `difflib`, `hashlib`).
- Error messages must say what went wrong and how to fix it.
- Tests use `tmp_path` for stores; never write to the real working directory.
