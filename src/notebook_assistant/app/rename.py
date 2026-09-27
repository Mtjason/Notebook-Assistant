"""Plan a link-safe rename or move (Handbook §5.1).

The plan is a changeset. Nothing is written until it is approved and applied:

1. check the new path is valid on every OS and its title is unique (case-insensitive);
2. move the file; for a note whose title changes, add the old title to ``aliases``;
3. rewrite every reference to it: wikilinks (with ``|alias``, ``#heading``, ``#^block``),
   embeds, Markdown links (relative or from the root, encoded or not), links in properties,
   and canvas file and text nodes;
4. rewrite the moved note's own relative Markdown links, which would break from a new folder.

The apply step then verifies that no link which resolved before is broken after.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app import canvas
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.ids import content_hash, new_note_id
from notebook_assistant.domain.links import (
    Link,
    md_link_is_relative,
    md_target_for,
    render_link,
    rewrite_links,
    wiki_target_for,
)
from notebook_assistant.domain.names import name_key, validate_path
from notebook_assistant.domain.note import Note, is_canvas_path, is_note_path, title_of


class PlanError(ValueError):
    """The requested rename/move would break a rule; nothing was planned."""


def plan_move(
    index: VaultIndex,
    src: PurePosixPath,
    dest: PurePosixPath,
    *,
    reason: str,
    created_by: str,
    now: datetime,
) -> Changeset:
    stored_src = index.path_of(src)
    if stored_src is None:
        raise PlanError(f"no such file: {src}")
    src = stored_src
    if src.suffix != dest.suffix:
        raise PlanError("a rename must keep the file extension")
    problems = validate_path(dest)
    if problems:
        raise PlanError("invalid target path: " + "; ".join(problems))
    existing = index.path_of(dest)
    case_only = existing is not None and name_key(existing.as_posix()) == name_key(src.as_posix())
    if existing is not None and not case_only:
        raise PlanError(f"target already exists: {existing}")
    if src.as_posix() == dest.as_posix():
        raise PlanError("source and target are the same")

    old_title, new_title = title_of(src), title_of(dest)
    title_changed = name_key(old_title) != name_key(new_title)
    if is_note_path(src) and title_changed:
        clash = [
            p
            for p in index.resolver.names_matching(dest.name)
            if name_key(p.as_posix()) != name_key(src.as_posix())
        ]
        if clash:
            raise PlanError(f"title {new_title!r} is already used by {clash[0]} (Handbook §5)")

    others_with_new_name = [
        p for p in index.resolver.names_matching(dest.name)
        if name_key(p.as_posix()) != name_key(src.as_posix())
    ]  # fmt: skip
    bare_unique = not others_with_new_name

    def retarget(link: Link, source: PurePosixPath, new_source: PurePosixPath) -> str | None:
        resolved = index.resolver.resolve(link, source)
        if resolved is None or name_key(resolved.as_posix()) != name_key(src.as_posix()):
            return None
        if link.target == "":  # same-note link [[#Heading]] keeps working
            return None
        if link.kind == "wiki":
            return render_link(link, wiki_target_for(dest, link, bare_name_is_unique=bare_unique))
        relative = md_link_is_relative(link, source, resolved)
        return render_link(link, md_target_for(dest, link, new_source, was_relative=relative))

    cs = Changeset(reason=reason, created_by=created_by, created=now.isoformat(timespec="seconds"))

    # 1. the moved file itself
    moved_content: str | None = None
    src_text = index.text(src)
    if src_text is not None and is_note_path(src):
        note = Note.parse(src, src_text)
        body_rewritten = _rewrite_own_md_links(index, note, src, dest)
        new_note = Note.parse(dest, body_rewritten)
        if new_note.frontmatter is not None:
            fm = new_note.frontmatter
            if title_changed:
                aliases = [
                    a for a in fm.get_list("aliases") if name_key(str(a)) != name_key(new_title)
                ]
                if all(name_key(str(a)) != name_key(old_title) for a in aliases):
                    aliases.append(old_title)
                fm.set("aliases", aliases)
            if not fm.get("id"):
                fm.set("id", new_note_id())
        rendered = new_note.render()
        # a note linking to itself by title is rewritten like any other reference
        rendered = rewrite_links(rendered, lambda link: retarget(link, src, dest))
        moved_content = rendered if rendered != src_text else None
    # Binary files (attachments) aren't in the text index: the apply step only checks they exist.
    base = content_hash(src_text) if src_text is not None else None
    cs.ops.append(
        Operation(
            kind="move",
            path=src,
            dest=dest,
            content=moved_content,
            base_hash=base,
            label=f"rename {old_title} → {new_title}"
            if title_changed
            else f"move to {dest.parent}",
        )
    )

    def moved_file(path: PurePosixPath) -> PurePosixPath | None:
        return dest if name_key(path.as_posix()) == name_key(src.as_posix()) else None

    def _rewrite_source(text: str, source: PurePosixPath) -> str:
        def replace(link: Link) -> str | None:
            return retarget(link, source, source)

        if is_canvas_path(source):
            return canvas.rewrite(text, move_file=moved_file, replace_link=replace)
        return rewrite_links(text, replace)

    # 2. every file that references it
    sources = {name_key(r.source.as_posix()): r.source for r in index.backlinks(src)}
    sources.pop(name_key(src.as_posix()), None)
    for source in sorted(sources.values(), key=lambda p: p.as_posix()):
        text = index.text(source)
        if text is None:
            continue
        new_text = _rewrite_source(text, source)
        if new_text != text:
            count = sum(1 for r in index.backlinks(src) if r.source == source)
            cs.ops.append(
                Operation(
                    kind="write",
                    path=source,
                    content=new_text,
                    base_hash=content_hash(text),
                    label=f"update {count} link{'s' if count != 1 else ''}",
                )
            )
    return cs


def _rewrite_own_md_links(
    index: VaultIndex, note: Note, src: PurePosixPath, dest: PurePosixPath
) -> str:
    """Keep the moved note's relative Markdown links pointing at the same files."""
    text = note.render()
    if src.parent == dest.parent:
        return text

    def fix(link: Link) -> str | None:
        if link.kind != "md" or link.target == "":
            return None
        resolved = index.resolver.resolve(link, src)
        if resolved is None or not md_link_is_relative(link, src, resolved):
            return None
        return render_link(link, md_target_for(resolved, link, dest, was_relative=True))

    return rewrite_links(text, fix)
