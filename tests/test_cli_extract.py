"""The digest and eval-extract commands, with a scripted model in place of the Claude API."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path, PurePosixPath

import pytest

from notebook_assistant import cli
from notebook_assistant.adapters.fake_llm import ScriptedModel
from notebook_assistant.adapters.fs_vault import FsVault
from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.ports.llm import LLMError
from notebook_assistant.store import changesets as cs_store
from tests.conftest import FIXTURE_VAULT, UV_CAPTURE, uv_plan_json

NEW_NOTE = PurePosixPath("60-Knowledge/Systems/curl pipe to shell install.md")


def digest_args(vault: str) -> list[str]:
    capture = str(UV_CAPTURE / "capture.md")
    return ["digest", "--vault", vault, "--text", capture, "--origin", "ai-chat"]


def eval_args(captures: Path) -> list[str]:
    return ["eval-extract", "--vault", str(FIXTURE_VAULT), "--captures", str(captures)]


def use_model(monkeypatch: pytest.MonkeyPatch, model: ScriptedModel) -> None:
    monkeypatch.setattr(cli, "make_model", lambda: model)


def test_digest_proposes_then_apply_writes(
    fs_vault: FsVault, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_model(monkeypatch, ScriptedModel([uv_plan_json()]))
    vault = str(fs_vault.root)
    code = cli.main(digest_args(vault))
    out = capsys.readouterr().out
    assert code == 0 and "pending · 4 operation(s)" in out
    assert not fs_vault.exists(NEW_NOTE)  # nothing is written before approval

    [record] = cs_store.list_records(fs_vault)
    cs = cs_store.load(fs_vault, record)
    assert "### Split map" in cs.review and cs.reason == "Digest capture.md"
    assert cli.main(["apply", "--vault", vault, cs.id]) == 0
    assert fs_vault.exists(NEW_NOTE)
    assert cli.main(["check", "--vault", vault]) == 0


def test_digest_reports_a_failed_plan(
    fs_vault: FsVault, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_model(monkeypatch, ScriptedModel([LLMError("the model declined the request")]))
    code = cli.main(digest_args(str(fs_vault.root)))
    assert code == 1 and "not planned: the model declined" in capsys.readouterr().err
    assert cs_store.list_records(fs_vault) == []


def test_digest_reports_a_bad_config(
    fs_vault: FsVault, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fs_vault.write_text(
        PurePosixPath("99-System/Assistant/Config.md"), "---\nlimts:\n  x: 1\n---\n"
    )
    use_model(monkeypatch, ScriptedModel([uv_plan_json()]))
    code = cli.main(digest_args(str(fs_vault.root)))
    assert code == 2 and "unknown section(s): limts" in capsys.readouterr().err


def test_digest_accepts_only_handbook_origins(fs_vault: FsVault) -> None:
    with pytest.raises(SystemExit):
        cli.main(["digest", "--vault", str(fs_vault.root), "--text", "x", "--origin", "gpt"])


def test_eval_scores_every_capture_without_writing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_model(monkeypatch, ScriptedModel([uv_plan_json()]))
    before = MemoryVault.copy_of(FsVault(FIXTURE_VAULT)).snapshot()
    code = cli.main(eval_args(UV_CAPTURE.parent))
    out = capsys.readouterr().out
    assert code == 0 and "uv-install-answer: 100%" in out and "mean 100%" in out
    assert MemoryVault.copy_of(FsVault(FIXTURE_VAULT)).snapshot() == before


def test_eval_fails_when_a_plan_misses_or_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captures = tmp_path / "captures"
    shutil.copytree(UV_CAPTURE, captures / "a")
    shutil.copytree(UV_CAPTURE, captures / "b")
    weaker = copy.deepcopy(uv_plan_json())
    weaker["atoms"] = [a for a in weaker["atoms"] if a["role"] != "extracted"]
    use_model(monkeypatch, ScriptedModel([weaker, LLMError("offline"), LLMError("offline")]))
    code = cli.main(eval_args(captures))
    out = capsys.readouterr().out
    assert code == 1
    assert "✗ atom command-rows (extracted → Bash commands)" in out
    assert "b: no plan: offline" in out


def test_eval_rejects_a_malformed_expected_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "captures" / "bad"
    case.mkdir(parents=True)
    (case / "expected.yaml").write_text("[1]\n", encoding="utf-8")
    code = cli.main(eval_args(tmp_path / "captures"))
    assert (
        code == 2
        and "bad: expected.yaml: expected.yaml must be a mapping" in capsys.readouterr().err
    )
