#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Update the pinned `landscape-debarchive` snap revisions in `src/snap_revisions.json`.

Used by the charm release automation: when a new snap revision is released to a
channel, the per-architecture revisions pinned by the charm are rewritten so a
charm release can pin the matching snap revisions.

Only positive-integer revisions are accepted, so untrusted workflow inputs can
never inject arbitrary content into the charm source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO_ROOT / "src" / "snap_revisions.json"
DEFAULT_SNAP = "landscape-debarchive"

AMD64 = "amd64"
ARM64 = "arm64"

_REVISION_PATTERN = re.compile(r"^[0-9]+$")


def update_manifest(manifest: dict, snap: str, amd64: str, arm64: str) -> dict:
    """Return `manifest` with the amd64/arm64 snap revisions replaced for `snap`."""
    if snap not in manifest:
        raise ValueError(f"Could not find {snap!r} entry in the revisions manifest.")
    revisions = manifest[snap]
    for arch in (AMD64, ARM64):
        if arch not in revisions:
            raise ValueError(f"Could not find {arch!r} revision for {snap!r}.")
    revisions[AMD64] = amd64
    revisions[ARM64] = arm64
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and rewrite the pinned revisions in the target file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amd64", required=True, help="New amd64 snap revision.")
    parser.add_argument("--arm64", required=True, help="New arm64 snap revision.")
    parser.add_argument(
        "--snap",
        default=DEFAULT_SNAP,
        help="Snap name whose revisions are updated (defaults to landscape-debarchive).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_TARGET,
        help="Path to the manifest file (defaults to src/snap_revisions.json).",
    )
    args = parser.parse_args(argv)

    for name, value in (("amd64", args.amd64), ("arm64", args.arm64)):
        if not _REVISION_PATTERN.match(value):
            parser.error(f"--{name} must be a positive integer, got {value!r}.")

    original = args.file.read_text(encoding="utf-8")
    manifest = json.loads(original)
    manifest = update_manifest(manifest, args.snap, args.amd64, args.arm64)
    updated = json.dumps(manifest, indent=2) + "\n"

    if updated != original:
        args.file.write_text(updated, encoding="utf-8")
        print(f"Updated {args.file}: amd64={args.amd64}, arm64={args.arm64}.")
    else:
        print(f"No change: {args.file} already pins amd64={args.amd64}, arm64={args.arm64}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
