"""Command-line entry point.

Branch 1 ships developer commands for exercising the core library against a real vault:

    notebook-assistant check --vault PATH            rule check of every note (read-only)
    notebook-assistant links --vault PATH            broken links (read-only)
    notebook-assistant plan-move --vault PATH SRC DEST
                                                     propose a link-safe rename/move (pending)
    notebook-assistant changesets --vault PATH       list changeset records
    notebook-assistant apply --vault PATH ID         apply a pending changeset (your approval)
    notebook-assistant undo --vault PATH ID          revert an applied changeset
    notebook-assistant serve [--vault PATH] [--port N] [--profile NAME]
                                                     run the local service and web app
    notebook-assistant autostart install|remove [--vault PATH] [--profile NAME]
                                                     start the service at login, or stop that
    notebook-assistant doctor [--vault PATH] [--profile NAME]
                                                     check that this host can run the assistant
    notebook-assistant digest --vault PATH --text FILE --origin ORIGIN
                                                     turn a capture into a pending changeset
    notebook-assistant eval-extract --vault PATH --captures DIR
                                                     score the planner on fixture captures

``serve`` binds to 127.0.0.1 only: the web app is for this PC alone.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

import uvicorn

from notebook_assistant import __version__
from notebook_assistant.adapters.anthropic_llm import AnthropicModel
from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.api.server import create_app, default_web_dir
from notebook_assistant.app.apply import apply_changeset, undo_changeset
from notebook_assistant.app.doctor import Status, run_checks, worst
from notebook_assistant.app.extract import (
    Capture,
    Extraction,
    ExtractionError,
    paths_after,
    plan_extraction,
)
from notebook_assistant.app.extract_eval import EvalFormatError, parse_expected, score
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.rename import PlanError, plan_move
from notebook_assistant.config import load_config
from notebook_assistant.domain.config import ConfigError
from notebook_assistant.domain.invariants import check_note, is_checked
from notebook_assistant.domain.jsontypes import JsonObject
from notebook_assistant.handbook import handbook_text, load_rules
from notebook_assistant.host import current_host
from notebook_assistant.machine import MachineConfigError
from notebook_assistant.platform import autostart
from notebook_assistant.platform.profiles import ProfileError
from notebook_assistant.ports.llm import LanguageModel, LLMError
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store


def _now() -> datetime:
    return datetime.now().astimezone()


def _machine(args: argparse.Namespace) -> str:
    """This install's name, recorded on the changesets it proposes and applies (§5.3)."""
    return current_host(args.vault).machine.name


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
    cs.machine = _machine(args)
    path = cs_store.save(store, cs)
    print(f"{cs.id} pending · {len(cs.ops)} operation(s) · record: {path}")
    for op in cs.ops:
        dest = f" → {op.dest}" if op.dest else ""
        print(f"  {op.kind:<6} {op.path}{dest}  {op.label}")
    print(f"\nReview the record in Obsidian, then: notebook-assistant apply --vault ... {cs.id}")
    return 0


def cmd_changesets(args: argparse.Namespace) -> int:
    store = _vault(args)
    for path in sorted(cs_store.list_records(store)):
        cs = cs_store.load(store, path)
        print(f"{cs.id}  {cs.status.value:<9} {cs.created}  {cs.reason}")
    return 0


def cmd_apply(args: argparse.Namespace, *, undo: bool = False) -> int:
    store = _vault(args)
    path = cs_store.find(store, args.id)
    if path is None:
        print(f"no changeset {args.id}", file=sys.stderr)
        return 2
    cs = cs_store.load(store, path)
    result = (
        undo_changeset(store, cs, now=_now())
        if undo
        else apply_changeset(store, cs, now=_now(), machine=_machine(args))
    )
    cs_store.save(store, result.changeset, with_diff=False)
    print(
        f"{cs.id}: {result.changeset.status.value}" + (f" — {result.error}" if result.error else "")
    )
    return 0 if result.ok else 1


def make_model() -> LanguageModel:
    """The language model the commands use: the Claude API. Tests replace this function."""
    return AnthropicModel()


def _extract(store: VaultStore, index: VaultIndex, capture: Capture) -> Extraction:
    return plan_extraction(
        capture,
        index,
        make_model(),
        config=load_config(store),
        handbook=handbook_text(),
        now=_now(),
        created_by="user:cli",
    )


def _save_answers(directory: str | None, name: str, answers: list[JsonObject]) -> None:
    """Write the model's raw answers to ``<directory>/<name>.answers.json``, for diagnosis."""
    if directory is None or not answers:
        return
    target = Path(directory) / f"{name}.answers.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(answers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"model answers saved: {target}", file=sys.stderr)


def cmd_digest(args: argparse.Namespace) -> int:
    store = _vault(args)
    source = Path(args.text)
    capture = Capture(source.read_text(encoding="utf-8"), args.origin, source.name)
    try:
        result = _extract(store, VaultIndex.build(store), capture)
    except ConfigError as exc:
        print(f"Config.md: {exc}", file=sys.stderr)
        return 2
    except ExtractionError as exc:
        _save_answers(args.save_answers, source.stem, exc.answers)
        print(f"not planned: {exc}", file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"not planned: {exc}", file=sys.stderr)
        return 1
    _save_answers(args.save_answers, source.stem, result.answers)
    cs = result.changeset
    cs.machine = _machine(args)
    path = cs_store.save(store, cs)
    print(f"{cs.id} pending · {len(cs.ops)} operation(s) · record: {path}")
    for op in cs.ops:
        print(f"  {op.kind:<6} {op.path}  {op.label}")
    if result.attempts > 1:
        print(f"(the first plan was rejected and redone: {'; '.join(result.rejected[0])})")
    print(
        f"\nReview the split map in the record, then: notebook-assistant apply --vault ... {cs.id}"
    )
    return 0


def cmd_eval_extract(args: argparse.Namespace) -> int:
    """Plan every fixture capture on a copy of the vault and score it (nothing is written)."""
    vault = _vault(args)
    cases = sorted(p for p in Path(args.captures).iterdir() if (p / "expected.yaml").is_file())
    fractions: list[float] = []
    for case in cases:
        try:
            expected = parse_expected((case / "expected.yaml").read_text(encoding="utf-8"))
        except EvalFormatError as exc:
            print(f"{case.name}: expected.yaml: {exc}", file=sys.stderr)
            return 2
        text = (case / expected.capture).read_text(encoding="utf-8")
        store = MemoryVault.copy_of(vault)
        index = VaultIndex.build(store)
        try:
            result = _extract(store, index, Capture(text, expected.origin, case.name))
        except (LLMError, ExtractionError) as exc:
            if isinstance(exc, ExtractionError):
                _save_answers(args.save_answers, case.name, exc.answers)
            print(f"{case.name}: no plan: {exc}")
            fractions.append(0.0)
            continue
        _save_answers(args.save_answers, case.name, result.answers)
        result_score = score(
            result.plan, result.outcomes, expected, paths_after(index, result.outcomes)
        )
        fractions.append(result_score.fraction)
        total = len(result_score.passed) + len(result_score.failed)
        print(
            f"{case.name}: {result_score.fraction:.0%} ({len(result_score.passed)}/{total})"
            f" · {result.attempts} attempt(s)"
        )
        for failure in result_score.failed:
            print(f"  ✗ {failure}")
    mean = sum(fractions) / len(fractions) if fractions else 0.0
    print(f"\n{len(cases)} capture(s) · mean {mean:.0%}")
    return 0 if fractions and all(f == 1.0 for f in fractions) else 1


def count_models() -> int:
    """How many models the Claude API offers these credentials. Tests replace this function."""
    return AnthropicModel().count_models()


_MARKS = {Status.OK: "✓", Status.WARN: "!", Status.FAIL: "✗"}


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        host = current_host(args.vault, args.profile)
    except (MachineConfigError, ProfileError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    vault = args.vault or host.machine.vault
    store = (
        FsVault(Path(vault).expanduser()) if vault and Path(vault).expanduser().is_dir() else None
    )
    checks = run_checks(
        host,
        store,
        vault,
        load_config=lambda: load_config(store) if store is not None else None,
        count_models=count_models,
    )
    for check in checks:
        print(f"{_MARKS[check.status]} {check.name:<11} {check.detail}")
    return 1 if worst(checks) is Status.FAIL else 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        host = current_host(args.vault, args.profile)
    except (MachineConfigError, ProfileError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    vault = args.vault or host.machine.vault
    if vault is None:
        print("no vault: pass --vault or set vault in config.yaml", file=sys.stderr)
        return 2
    folder = Path(vault).expanduser()
    if not folder.is_dir():
        print(f"no such vault folder: {folder}", file=sys.stderr)
        return 2
    port = args.port or host.machine.port
    app = create_app(FsVault(folder), host, vault_label=str(folder), web_dir=default_web_dir())
    print(f"notebook-assistant on http://127.0.0.1:{port} · vault {folder} · {host.profile.value}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    try:
        host = current_host(args.vault, args.profile)
    except (MachineConfigError, ProfileError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    vault = args.vault or host.machine.vault
    if args.action == "install" and vault is None:
        print("no vault: pass --vault or set vault in config.yaml", file=sys.stderr)
        return 2
    argv = [sys.executable, "-m", "notebook_assistant", "serve"]
    if args.vault:
        argv += ["--vault", str(Path(args.vault).expanduser().resolve())]
    try:
        entry = autostart.plan(host.profile, argv, home=Path.home(), distro=autostart.wsl_distro())
        autostart.apply(entry, install=args.action == "install")
    except autostart.AutostartError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"✗ {args.action} failed: {exc}", file=sys.stderr)
        return 1
    done = "starts at login" if args.action == "install" else "no longer starts at login"
    print(f"notebook-assistant {done} ({host.profile.value})")
    return 0


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
    p = sub.add_parser("serve", help="run the local service and web app (127.0.0.1 only)")
    p.add_argument("--vault", help="the vault to serve (default: vault in config.yaml)")
    p.add_argument("--port", type=int, help="port on 127.0.0.1 (default: port in config.yaml)")
    p.add_argument("--profile", help="force a host profile (architecture §5.1)")
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("autostart", help="start the service at login, or stop that")
    p.add_argument("action", choices=["install", "remove"])
    p.add_argument("--vault", help="the vault to serve (default: vault in config.yaml)")
    p.add_argument("--profile", help="force a host profile (architecture §5.1)")
    p.set_defaults(func=cmd_autostart)
    p = sub.add_parser("doctor", help="check that this host can run the assistant")
    p.add_argument("--vault", help="the vault to check (default: vault in config.yaml)")
    p.add_argument("--profile", help="force a host profile (architecture §5.1)")
    p.set_defaults(func=cmd_doctor)
    p = with_vault(sub.add_parser("digest", help="turn a capture into a pending changeset"))
    p.add_argument("--text", required=True, help="the capture, as a UTF-8 text file")
    p.add_argument(
        "--origin",
        required=True,
        choices=sorted(load_rules().common_enums["origin"]),
        help="where the material came from (Handbook §4.1)",
    )
    p.add_argument("--save-answers", metavar="DIR", help="also save the model's raw answers")
    p.set_defaults(func=cmd_digest)
    p = with_vault(
        sub.add_parser("eval-extract", help="(experimental) score the planner on fixture captures")
    )
    p.add_argument("--captures", required=True, help="folder of <case>/expected.yaml")
    p.add_argument("--save-answers", metavar="DIR", help="also save the model's raw answers")
    p.set_defaults(func=cmd_eval_extract)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
