"""The ``prompts`` command: a thin layer over the public API."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import PromptWhere, PromptWhereError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prompts", description="Manage named, versioned prompts.")
    parser.add_argument("--path", default="./prompts", help="store folder (default: ./prompts)")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list prompt names")

    show = commands.add_parser("show", help="print a prompt (latest by default)")
    show.add_argument("name")
    group = show.add_mutually_exclusive_group()
    group.add_argument("--version", type=int)
    group.add_argument("--label")

    history = commands.add_parser("history", help="list all versions of a prompt")
    history.add_argument("name")

    edit = commands.add_parser("edit", help="edit the latest version in $EDITOR")
    edit.add_argument("name")
    edit.add_argument("-m", "--message", help="note for the new version")

    diff = commands.add_parser("diff", help="unified diff between two versions")
    diff.add_argument("name")
    diff.add_argument("a", type=int)
    diff.add_argument("b", type=int)

    label = commands.add_parser("label", help="point a label at a version")
    label.add_argument("name")
    label.add_argument("label")
    label.add_argument("version", type=int)
    return parser


def _edit_in_editor(initial: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "notepad"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "prompt.txt"
        path.write_text(initial, encoding="utf-8", newline="")
        subprocess.run([*shlex.split(editor, posix=os.name != "nt"), str(path)], check=True)
        return path.read_text(encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    store = PromptWhere(args.path)
    if args.command == "list":
        for name in store.list():
            print(name)
    elif args.command == "show":
        sys.stdout.write(str(store.get(args.name, args.version, args.label)))
    elif args.command == "history":
        for prompt in store.history(args.name):
            when = prompt.created_at.strftime("%Y-%m-%d %H:%M:%S")
            print(f"v{prompt.version}  {when}  {prompt.message or ''}".rstrip())
    elif args.command == "edit":
        current = store.get(args.name).template
        edited = _edit_in_editor(current)
        if not edited.strip() or edited == current:
            print("No changes; nothing saved.")
        else:
            print(f"Saved {args.name} as v{store.save(args.name, edited, args.message).version}.")
    elif args.command == "diff":
        sys.stdout.write(store.diff(args.name, args.a, args.b))
    elif args.command == "label":
        store.set_label(args.name, args.label, args.version)
        print(f"{args.name}: {args.label} -> v{args.version}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``prompts`` command. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        return _run(args)
    except (PromptWhereError, ValueError, subprocess.CalledProcessError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
