"""Stop hook: when the design docs changed, Claude checks they still agree before finishing.

The tests catch mechanical drift (``tests/test_docs_consistency.py``); this catches what needs
reading: two documents that now say different things. When ``docs/``, ``CLAUDE.md`` or
``README.md`` differ from the merge base with ``main``, the first stop is blocked and Claude is
sent to the procedure in CLAUDE.md, *Doc consistency review*.

Each reviewed state is remembered (a hash in ``.git/``), so the same change is reviewed once and a
new edit triggers a new review. ``stop_hook_active`` ends the chain after one review per stop, so
edits made during the review can't loop.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WATCHED = ("docs", "CLAUDE.md", "README.md")
BASE_BRANCH = "main"
MARKER = "na-docs-reviewed"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _changed_files(base: str) -> list[str]:
    tracked = _git("diff", "--name-only", base, "--", *WATCHED).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *WATCHED).split()
    return sorted(set(tracked) | set(untracked))


def _fingerprint(base: str, files: list[str]) -> str:
    digest = hashlib.sha256(_git("diff", base, "--", *WATCHED).encode("utf-8"))
    for name in files:
        path = Path(name)
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    if json.load(sys.stdin).get("stop_hook_active"):
        return 0
    base = _git("merge-base", "HEAD", BASE_BRANCH).strip()
    files = _changed_files(base)
    if not files:
        return 0
    marker = Path(_git("rev-parse", "--git-dir").strip()) / MARKER
    fingerprint = _fingerprint(base, files)
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == fingerprint:
        return 0
    marker.write_text(fingerprint, encoding="utf-8")
    reason = (
        "Design docs changed since main: "
        + ", ".join(files)
        + ". Before finishing, follow CLAUDE.md, 'Doc consistency review', and report what you"
        " checked and changed."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
