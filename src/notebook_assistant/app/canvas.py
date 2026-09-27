"""Links inside Obsidian canvases (``.canvas`` JSON files).

A canvas references files through ``file`` nodes (``{"type": "file", "file": "path/to.md"}``)
and through ordinary links inside ``text`` nodes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from notebook_assistant.domain.links import Link, rewrite_links


def load(text: str) -> dict[str, Any]:
    data = json.loads(text) if text.strip() else {}
    return data if isinstance(data, dict) else {}


def file_refs(data: dict[str, Any]) -> list[PurePosixPath]:
    """Vault paths referenced by file nodes."""
    return [
        PurePosixPath(node["file"])
        for node in data.get("nodes", [])
        if isinstance(node, dict)
        and node.get("type") == "file"
        and isinstance(node.get("file"), str)
    ]


def text_nodes(data: dict[str, Any]) -> list[str]:
    return [
        node["text"]
        for node in data.get("nodes", [])
        if isinstance(node, dict)
        and node.get("type") == "text"
        and isinstance(node.get("text"), str)
    ]


def dump_like(original: str, data: dict[str, Any]) -> str:
    """Serialize ``data`` in the original file's style (Obsidian uses tab indentation)."""
    if "\n\t" in original:
        indent: str | None = "\t"
    elif "\n  " in original:
        indent = "  "
    else:
        indent = None
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    return text + ("\n" if original.endswith("\n") else "")


def rewrite(
    original: str,
    move_file: Callable[[PurePosixPath], PurePosixPath | None],
    replace_link: Callable[[Link], str | None],
) -> str:
    """Rewrite file nodes via ``move_file`` and text-node links via ``replace_link``.

    Returns the original text unchanged when nothing needed rewriting.
    """
    data = load(original)
    changed = False
    for node in data.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if node.get("type") == "file" and isinstance(node.get("file"), str):
            new = move_file(PurePosixPath(node["file"]))
            if new is not None and new.as_posix() != node["file"]:
                node["file"] = new.as_posix()
                changed = True
        elif node.get("type") == "text" and isinstance(node.get("text"), str):
            new_text = rewrite_links(node["text"], replace_link)
            if new_text != node["text"]:
                node["text"] = new_text
                changed = True
    return dump_like(original, data) if changed else original
