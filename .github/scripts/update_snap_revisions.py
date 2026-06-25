#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Update the pinned `landscape-debarchive` snap revisions in `src/debarchive.py`.

Used by the charm release automation: when a new snap revision is released to a
channel, the per-architecture revisions pinned by the charm are rewritten so a
charm release can pin the matching snap revisions.

Only positive-integer revisions are accepted, so untrusted workflow inputs can
never inject arbitrary content into the charm source.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO_ROOT / "src" / "debarchive.py"

_BLOCK_PATTERN = re.compile(
    r"(?P<prefix>DEBARCHIVE_SNAP_REVISIONS\s*=\s*\{)(?P<body>.*?)(?P<suffix>\})",
    re.DOTALL,
)
_REVISION_PATTERN = re.compile(r"^[0-9]+$")


def _replace_revision(body: str, key: str, revision: str) -> str:
    """Replace the integer value for `key` within a revisions-map body."""
    pattern = re.compile(rf'(?P<lead>\b{key}\s*:\s*")[0-9]+(?P<trail>")')
    new_body, count = pattern.subn(rf"\g<lead>{revision}\g<trail>", body)
    if count != 1:
        raise ValueError(f"Expected exactly one {key!r} revision entry, found {count}.")
    return new_body


def update_source(source: str, amd64: str, arm64: str) -> str:
    """Return `source` with the amd64/arm64 snap revisions replaced."""
    match = _BLOCK_PATTERN.search(source)
    if match is None:
        raise ValueError("Could not find DEBARCHIVE_SNAP_REVISIONS block.")
    body = match.group("body")
    body = _replace_revision(body, "AMD64", amd64)
    body = _replace_revision(body, "ARM64", arm64)
    return source[: match.start("body")] + body + source[match.end("body") :]


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and rewrite the pinned revisions in the target file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amd64", required=True, help="New amd64 snap revision.")
    parser.add_argument("--arm64", required=True, help="New arm64 snap revision.")
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_TARGET,
        help="Path to the source file (defaults to src/debarchive.py).",
    )
    args = parser.parse_args(argv)

    for name, value in (("amd64", args.amd64), ("arm64", args.arm64)):
        if not _REVISION_PATTERN.match(value):
            parser.error(f"--{name} must be a positive integer, got {value!r}.")

    source = args.file.read_text(encoding="utf-8")
    updated = update_source(source, args.amd64, args.arm64)
    if updated != source:
        args.file.write_text(updated, encoding="utf-8")
        print(f"Updated {args.file}: amd64={args.amd64}, arm64={args.arm64}.")
    else:
        print(f"No change: {args.file} already pins amd64={args.amd64}, arm64={args.arm64}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
