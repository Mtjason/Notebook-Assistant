"""Command-line entry point.

Branch 1 ships developer commands for exercising the core library against a real vault:

    notebook-assistant check --vault PATH            rule check of every note (read-only)
    notebook-assistant links --vault PATH            broken links (read-only)
    notebook-assistant plan-move --vault PATH SRC DEST
                                                     propose a link-safe rename/move (pending)
    notebook-assistant changesets --vault PATH       list changeset records
    notebook-assistant apply --vault PATH ID         apply a pending changeset (your approval)
    notebook-assistant undo --vault PATH ID          revert an applied changeset

``serve`` (the web app) arrives with the service-shell branch.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

from notebook_assistant import __version__
from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.app.apply import apply_changeset, undo_changeset
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.rename import PlanError, plan_move
from notebook_assistant.domain.invariants import check_note, is_checked
from notebook_assistant.store import changesets as cs_store


def _now() -> datetime:
    return datetime.now().astimezone()


def _machine() -> str:
    return os.environ.get("NA_MACHINE") or socket.gethostname()


def _vault(args: argparse.Namespace) -> FsVault:
    return FsVault(Path(args.vault).expanduser())


def cmd_check(args: argparse.Namespace) -> int:
    index = VaultIndex.build(_vault(args))
    facts = index.facts()
    results = {
        n.path.as_posix(): [v.__dict__ for v in check_note(n, facts)]
        for n in sorted(index.notes.values(), key=lambda n: n.path.as_posix())
    }
    results = {k: v for k, v in results.items() if v}
    unparseable = {
        p: e for p, e in index.unparseable.items() if is_checked(PurePosixPath(p), facts.rules)
    }
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        by_code: Counter[str] = Counter(v["code"] for vs in results.values() for v in vs)
        for path, violations in results.items():
            print(path)
            for v in violations:
                print(f"  {v['code']:<6} {v['message']}  ({v['section']})")
        for path, err in unparseable.items():
            print(f"{path}\n  parse  {err}")
        total = sum(by_code.values())
        print(
            f"\n{len(index.notes)} notes checked · {total} violation(s)"
            + (" · " + ", ".join(f"{c}: {n}" for c, n in sorted(by_code.items())) if total else "")
        )
    return 1 if results or unparseable else 0


def cmd_links(args: argparse.Namespace) -> int:
    index = VaultIndex.build(_vault(args))
    for source, link in index.broken:
        print(f"{source}: {link.target}{link.subpath}")
    print(f"\n{len(index.broken)} broken link(s)")
    return 1 if index.broken else 0


def cmd_plan_move(args: argparse.Namespace) -> int:
    store = _vault(args)
    index = VaultIndex.build(store)
    try:
        cs = plan_move(
            index,
            PurePosixPath(args.src),
            PurePosixPath(args.dest),
            reason=args.reason or f"Move {args.src} → {args.dest}",
            created_by="user:cli",
            now=_now(),
        )
    except PlanError as exc:
        print(f"not planned: {exc}", file=sys.stderr)
        return 2
    cs.machine = _machine()
    path = cs_store.save(store, cs)
    print(f"{cs.id} pending · {len(cs.ops)} operation(s) · record: {path}")
    for op in cs.ops:
        dest = f" → {op.dest}" if op.dest else ""
        print(f"  {op.kind:<6} {op.path}{dest}  {op.label}")
    print(f"\nReview the record in Obsidian, then: notebook-assistant apply --vault ... {cs.id}")
    return 0


def _find_record(store: FsVault, cs_id: str) -> PurePosixPath | None:
    return next((p for p in cs_store.list_records(store) if p.stem == cs_id), None)


def cmd_changesets(args: argparse.Namespace) -> int:
    store = _vault(args)
    for path in sorted(cs_store.list_records(store)):
        cs = cs_store.load(store, path)
        print(f"{cs.id}  {cs.status.value:<9} {cs.created}  {cs.reason}")
    return 0


def cmd_apply(args: argparse.Namespace, *, undo: bool = False) -> int:
    store = _vault(args)
    path = _find_record(store, args.id)
    if path is None:
        print(f"no changeset {args.id}", file=sys.stderr)
        return 2
    cs = cs_store.load(store, path)
    result = (
        undo_changeset(store, cs, now=_now())
        if undo
        else apply_changeset(store, cs, now=_now(), machine=_machine())
    )
    cs_store.save(store, result.changeset, with_diff=False)
    print(
        f"{cs.id}: {result.changeset.status.value}" + (f" — {result.error}" if result.error else "")
    )
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notebook-assistant", description=__doc__.split("\n")[0])
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_vault(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--vault", required=True, help="path to the Obsidian vault")
        return p

    p = with_vault(sub.add_parser("check", help="check every note against the handbook"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)
    with_vault(sub.add_parser("links", help="list broken links")).set_defaults(func=cmd_links)
    p = with_vault(sub.add_parser("plan-move", help="propose a link-safe rename or move"))
    p.add_argument("src")
    p.add_argument("dest")
    p.add_argument("--reason")
    p.set_defaults(func=cmd_plan_move)
    with_vault(sub.add_parser("changesets", help="list changesets")).set_defaults(
        func=cmd_changesets
    )
    p = with_vault(sub.add_parser("apply", help="apply a pending changeset"))
    p.add_argument("id")
    p.set_defaults(func=cmd_apply)
    p = with_vault(sub.add_parser("undo", help="revert an applied changeset"))
    p.add_argument("id")
    p.set_defaults(func=lambda a: cmd_apply(a, undo=True))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
