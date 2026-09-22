from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cua_jev.tools")
    sub = parser.add_subparsers(dest="command", required=True)
    replace = sub.add_parser("replace-exact")
    replace.add_argument("path", type=Path)
    replace.add_argument("old")
    replace.add_argument("new")
    copy = sub.add_parser("copy-file")
    copy.add_argument("source", type=Path)
    copy.add_argument("destination", type=Path)
    write = sub.add_parser("write-text")
    write.add_argument("path", type=Path)
    write.add_argument("text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "replace-exact":
        text = args.path.read_text(encoding="utf-8")
        if text.count(args.old) != 1:
            raise SystemExit("expected exactly one matching text segment")
        args.path.write_text(text.replace(args.old, args.new), encoding="utf-8")
        return 0
    if args.command == "copy-file":
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.source, args.destination)
        return 0
    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(args.text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
