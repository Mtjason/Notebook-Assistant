"""Find, resolve and rewrite links in notes and canvases.

Link forms handled (all may appear in the body or inside a frontmatter value):

- wikilinks ``[[target]]``, ``[[target|alias]]``, ``[[target#Heading]]``, ``[[target#^block]]``,
  ``[[#Heading]]`` (same note), with a path (``[[folder/note]]``) or an extension
  (``[[image.png]]``), and embeds ``![[…]]``;
- Markdown links ``[text](path)`` and ``![alt](path)``, URL-encoded (``%20``) or in angle
  brackets (``<path with spaces.md>``); URLs with a scheme (``https:``, ``obsidian:``) are ignored.

Links inside fenced code blocks and inline code are ignored.

Resolution follows Obsidian: a target without ``/`` matches a file name anywhere in the vault
(case-insensitive); with ``/`` it matches a path from the vault root, then a path suffix. When
several files match, the one in the linking note's folder wins, then the shortest path.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, unquote

from notebook_assistant.domain.names import name_key

_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.S)
_WIKI = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
_MD = re.compile(r"(!?)\[((?:[^\[\]\n]|\[[^\[\]\n]*\])*)\]\((<[^>\n]+>|[^)\s]+)(\s+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class Link:
    """One link occurrence. ``start``/``end`` delimit the whole link text in the source."""

    kind: str  # "wiki" or "md"
    embed: bool
    target: str  # the file part, decoded; "" for same-note links like [[#Heading]]
    subpath: str  # "#Heading" / "#^block" or ""
    alias: str | None  # wiki: text after "|"; md: the link text
    start: int
    end: int
    angle: bool = False  # md link written as (<path>)
    encoded: bool = False  # md link path was URL-encoded
    title_part: str = ""  # md: optional ' "title"'
    table_escape: bool = False  # wiki: alias separator written "\\|" inside a table


def _code_mask(text: str) -> list[tuple[int, int]]:
    """Spans of fenced code blocks and inline code, where links must be ignored."""
    spans: list[tuple[int, int]] = []
    pos = 0
    fence: str | None = None
    fence_start = 0
    for line in text.splitlines(keepends=True):
        m = _FENCE.match(line)
        if fence is None and m:
            fence, fence_start = m.group(1), pos
        elif (
            fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)
        ):
            spans.append((fence_start, pos + len(line)))
            fence = None
        pos += len(line)
    if fence is not None:
        spans.append((fence_start, len(text)))
    outside = _invert(spans, len(text))
    for a, b in outside:
        for m in _INLINE_CODE.finditer(text, a, b):
            spans.append((m.start(), m.end()))
    return sorted(spans)


def _invert(spans: list[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    out, pos = [], 0
    for a, b in spans:
        if a > pos:
            out.append((pos, a))
        pos = max(pos, b)
    if pos < length:
        out.append((pos, length))
    return out


def _inside(spans: list[tuple[int, int]], i: int) -> bool:
    return any(a <= i < b for a, b in spans)


def find_links(text: str) -> list[Link]:
    """Every wikilink, embed and internal Markdown link in ``text``, in order."""
    mask = _code_mask(text)
    links: list[Link] = []
    for m in _WIKI.finditer(text):
        if _inside(mask, m.start()):
            continue
        inner = m.group(2)
        target_part, _, alias = inner.partition("|")
        # inside a table the separator is written "\|"; the backslash isn't part of the target
        escaped = "|" in inner and target_part.endswith("\\")
        target_part = target_part.removesuffix("\\")
        target, hash_, sub = target_part.partition("#")
        links.append(
            Link(
                kind="wiki",
                embed=m.group(1) == "!",
                target=target.strip(),
                subpath=(hash_ + sub) if hash_ else "",
                alias=alias if "|" in inner else None,
                start=m.start(),
                end=m.end(),
                table_escape=escaped,
            )
        )
    for m in _MD.finditer(text):
        if _inside(mask, m.start()):
            continue
        raw = m.group(3)
        angle = raw.startswith("<")
        path = raw[1:-1] if angle else raw
        if _SCHEME.match(path) or (path.startswith("#") and not path[1:]):
            continue
        file_part, hash_, sub = path.partition("#")
        decoded = unquote(file_part)
        links.append(
            Link(
                kind="md",
                embed=m.group(1) == "!",
                target=decoded,
                subpath=(hash_ + sub) if hash_ else "",
                alias=m.group(2),
                start=m.start(),
                end=m.end(),
                angle=angle,
                encoded=decoded != file_part,
                title_part=m.group(4) or "",
            )
        )
    links.sort(key=lambda link: link.start)
    return links


class Resolver:
    """Resolves link targets against the set of files in the vault."""

    def __init__(self, paths: Iterable[PurePosixPath]) -> None:
        self._by_path: dict[str, PurePosixPath] = {}
        self._by_name: dict[str, list[PurePosixPath]] = defaultdict(list)
        for p in paths:
            self._by_path[name_key(p.as_posix())] = p
            self._by_name[name_key(p.name)].append(p)

    def resolve(self, link: Link, source: PurePosixPath) -> PurePosixPath | None:
        if link.target == "":
            return source
        if link.kind == "md":
            return self._resolve_md(link.target, source)
        return self._resolve_wiki(link.target, source)

    def _resolve_wiki(self, target: str, source: PurePosixPath) -> PurePosixPath | None:
        target = target.strip().lstrip("/")
        # [[Python os.execv]] is a note even though ".execv" looks like an extension
        candidates_names = [target] if target.lower().endswith(".md") else [target + ".md", target]
        for cand in candidates_names:
            if "/" in cand:
                exact = self._by_path.get(name_key(cand))
                if exact:
                    return exact
                suffix = name_key("/" + cand)
                matches = [p for k, p in self._by_path.items() if ("/" + k).endswith(suffix)]
                if matches:
                    return _closest(matches, source)
            else:
                matches = self._by_name.get(name_key(cand), [])
                if matches:
                    return _closest(matches, source)
        return None

    def _resolve_md(self, target: str, source: PurePosixPath) -> PurePosixPath | None:
        relative = posixpath.normpath(posixpath.join(source.parent.as_posix(), target))
        for cand in (relative, target.lstrip("/")):
            for name in (cand, cand + ".md") if not _has_extension(cand) else (cand,):
                hit = self._by_path.get(name_key(name))
                if hit:
                    return hit
        return None

    def names_matching(self, filename: str) -> list[PurePosixPath]:
        return list(self._by_name.get(name_key(filename), []))


def _has_extension(target: str) -> bool:
    name = target.rsplit("/", 1)[-1]
    return bool(re.search(r"\.[A-Za-z0-9]{1,8}$", name))


def _closest(matches: list[PurePosixPath], source: PurePosixPath) -> PurePosixPath:
    same_folder = [p for p in matches if p.parent == source.parent]
    pool = same_folder or matches
    return sorted(pool, key=lambda p: (len(p.parts), p.as_posix()))[0]


# --------------------------------------------------------------------------- rewriting


def wiki_target_for(new_path: PurePosixPath, old_link: Link, *, bare_name_is_unique: bool) -> str:
    """Target text for a wikilink to ``new_path``, keeping the old link's style.

    A bare-name link stays a bare name when that name is unique; otherwise the full path is
    used. Notes drop ``.md``; other files keep their extension.
    """
    is_note = new_path.name.endswith(".md")
    full = new_path.as_posix()[: -len(".md")] if is_note else new_path.as_posix()
    name = new_path.name[: -len(".md")] if is_note else new_path.name
    if "/" not in old_link.target and bare_name_is_unique:
        return name
    return full


def md_target_for(
    new_path: PurePosixPath, old_link: Link, source: PurePosixPath, *, was_relative: bool
) -> str:
    """Path text for a Markdown link to ``new_path`` from ``source``.

    Keeps the old link's style: relative to the linking note or from the vault root, with or
    without ``.md``, URL-encoded or not. Spaces and parentheses are always encoded unless the
    path is in angle brackets, because either would end a Markdown link early.
    """
    if was_relative:
        text = posixpath.relpath(new_path.as_posix(), source.parent.as_posix() or ".")
    else:
        text = new_path.as_posix()
        if old_link.target.startswith("/"):
            text = "/" + text
    if not old_link.target.endswith(".md") and text.endswith(".md"):
        text = text[: -len(".md")]
    if old_link.encoded:
        text = quote(text, safe="/-_.~!")
    elif not old_link.angle:
        # a bare space or parenthesis would end the Markdown link early
        text = text.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return text


def md_link_is_relative(link: Link, source: PurePosixPath, resolved: PurePosixPath) -> bool:
    """Whether a Markdown link was written relative to its note's folder (vs. the vault root)."""
    if link.target.startswith("/"):
        return False
    joined = posixpath.normpath(posixpath.join(source.parent.as_posix(), link.target))
    return any(name_key(c) == name_key(resolved.as_posix()) for c in (joined, joined + ".md"))


def render_link(link: Link, target_text: str) -> str:
    """The full link text for ``link`` pointing at ``target_text``."""
    bang = "!" if link.embed else ""
    if link.kind == "wiki":
        sep = "\\|" if link.table_escape else "|"
        alias = f"{sep}{link.alias}" if link.alias is not None else ""
        return f"{bang}[[{target_text}{link.subpath}{alias}]]"
    path = f"{target_text}{link.subpath}"
    if link.angle:
        path = f"<{path}>"
    return f"{bang}[{link.alias or ''}]({path}{link.title_part})"


def rewrite_links(text: str, replace: Callable[[Link], str | None]) -> str:
    """Return ``text`` with each link replaced by ``replace(link)`` (``None`` keeps it)."""
    out: list[str] = []
    pos = 0
    for link in find_links(text):
        new = replace(link)
        if new is None:
            continue
        out.append(text[pos : link.start])
        out.append(new)
        pos = link.end
    out.append(text[pos:])
    return "".join(out)
