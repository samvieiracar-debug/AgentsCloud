"""Git real local, uv registrador e processos isolados para os quatro atalhos."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

from test_launchers import ROOT, launcher
from test_agentscloud import FakeUI, agent_bytes, write_bundle
from agentscloud.cli import main
from agentscloud.git import Repository
from agentscloud.prepared import PreparedCheckout


BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)
CLI_PROBE = '''import json, os, sys
from pathlib import Path
from .arguments import build_parser
from .git import Repository
MARKER = "old"
def main(arguments, default_repo, prepared):
    args = build_parser(default_repo).parse_args(arguments)
    repo = Repository(args.repo)
    prepared.check_upstream(repo, repo.fetch_upstream())
    Path(os.environ["PROBE_RECORD"]).write_text(json.dumps({
        "marker": MARKER, "arguments": arguments, "root": str(args.repo),
        "prefix": sys.prefix, "prepared": prepared.head}), encoding="utf-8")
    return int(os.environ.get("PROBE_EXIT", "0"))
'''
UV_PROBE = r'''import json, os, shutil, subprocess, sys
from pathlib import Path
root = Path.cwd()
with Path(os.environ["PROBE_SYNC"]).open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": sys.argv[1:], "root": str(root),
        "lock": (root / "uv.lock").read_text(encoding="utf-8"),
        "environment": os.environ.get("UV_PROJECT_ENVIRONMENT"),
        "active": os.environ.get("VIRTUAL_ENV"),
        "redirects": [os.environ.get(key) for key in ("UV_PROJECT", "UV_WORKING_DIR", "UV_WORKING_DIRECTORY")]}) + "\n")
code = int(os.environ.get("PROBE_SYNC_EXIT", "0"))
if code:
    print("sync failure / ambiente em uso", file=sys.stderr)
    sys.exit(code)
if not (root / ".venv").exists():
    shutil.copytree(os.environ["PROBE_VENV"], root / ".venv", symlinks=True)
if os.environ.get("PROBE_CHANGE_HEAD"):
    subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-m", "concurrent"], check=True)
if os.environ.get("PROBE_CHANGE_UPSTREAM"):
    subprocess.run(["git", "-C", str(root), "config", "branch.trunk.merge", "refs/heads/other"], check=True)
if os.environ.get("PROBE_PUSH"):
    seed = os.environ["PROBE_PUSH"]
    subprocess.run(["git", "-C", seed, "commit", "--allow-empty", "-m", "remote concurrent"], check=True)
    subprocess.run(["git", "-C", seed, "push"], check=True)
'''


@unittest.skipUnless(shutil.which("git"), "Git necessário para os remotos locais.")
class PreparationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix="agentscloud-bootstrap-venv-")
        cls.addClassCleanup(cls.shared.cleanup)
        cls.venv_template = Path(cls.shared.name) / "template"
        venv.EnvBuilder(with_pip=False).create(cls.venv_template)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agentscloud-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith("GIT_") or key.startswith("PROBE_"):
                self.env.pop(key)
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.base / "empty-config"),
                        GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid",
                        CODEX_HOME=str(self.base / "personal"), AGENTSCLOUD_NO_PAUSE="1",
                        PROBE_RECORD=str(self.base / "runtime.json"), PROBE_SYNC=str(self.base / "sync.jsonl"),
                        PROBE_VENV=str(self.venv_template), PYTHONIOENCODING="utf-8")
        self.record = self.base / "runtime.json"
        self.sync = self.base / "sync.jsonl"
        self.tools = self.base / "tools"
        self.tools.mkdir()
        self.make_tool("uv", UV_PROBE)
        self.env["PATH"] = str(self.tools) + os.pathsep + self.env["PATH"]
        self.remote = self.base / "remote.git"
        self.seed = self.base / "seed"
        self.clone = self.base / "clone & (qa)!^% data"
        self.seed.mkdir()
        self.git(self.base, "init", "--bare", str(self.remote))
        self.git(self.seed, "init", "-b", "trunk")
        self.copy_product(self.seed)
        (self.seed / "src/agentscloud/cli.py").write_text(CLI_PROBE, encoding="utf-8")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-m", "initial")
        self.git(self.seed, "remote", "add", "team", str(self.remote))
        self.git(self.seed, "push", "-u", "team", "trunk")
        self.git(self.base, "clone", "--branch", "trunk", str(self.remote), str(self.clone))
        self.git(self.clone, "remote", "rename", "origin", "team")
        self.caller = self.base / "caller"
        self.caller.mkdir()

    def make_tool(self, name, source):
        script = self.tools / f"{name}_probe.py"
        script.write_text(source, encoding="utf-8")
        if os.name == "nt":
            (self.tools / f"{name}.cmd").write_text(
                f'@"{BASE_PYTHON}" "{script}" %*\n', encoding="utf-8")
        else:
            tool = self.tools / name
            tool.write_text(f"#!{BASE_PYTHON}\n" + source, encoding="utf-8")
            tool.chmod(0o755)

    @staticmethod
    def copy_product(folder):
        for name in ("_launcher.py", "_runtime.py", "update.py", "upload.py", "update.cmd", "upload.cmd",
                     "pyproject.toml", "uv.lock", "README.md", "catalog.toml", ".gitignore"):
            shutil.copy2(ROOT / name, folder / name)
        for name in ("src", "Agents"):
            shutil.copytree(ROOT / name, folder / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (folder / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/_launcher_console.ps1", folder / "scripts/_launcher_console.ps1")

    def git(self, folder, *args, check=True):
        result = subprocess.run(["git", "-C", str(folder), *args], env=self.env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def launch(self, command="update", arguments=(), folder=None, cmd=False, python=None):
        folder = folder or self.clone
        if cmd:
            self.env["PROBE_WRAPPER"] = str(folder / f"{command}.cmd")
            # Valores são expandidos uma vez, sem transformar metacaracteres em comandos.
            words = []
            for index, arg in enumerate(arguments):
                key = f"PROBE_ARG_{index}"
                self.env[key] = str(arg)
                words.append(f'"%{key}%"')
            comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
            invocation = f'"{comspec}" /d /v:off /s /c ""%PROBE_WRAPPER%" {" ".join(words)}"'
        else:
            invocation = [python or BASE_PYTHON, str(folder / f"{command}.py"), *map(str, arguments)]
        return subprocess.run(invocation, cwd=self.caller, env=self.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=45)

    def pushed_change(self, marker="new", cmd_change=False):
        (self.seed / "src/agentscloud/cli.py").write_text(CLI_PROBE.replace('"old"', f'"{marker}"'), encoding="utf-8")
        with (self.seed / "uv.lock").open("a", encoding="utf-8") as f:
            f.write("\n# new lock from upstream\n")
        if cmd_change:
            for name in ("update.cmd", "upload.cmd"):
                (self.seed / name).write_text("@echo off\necho UPDATED_FILE_MUST_NOT_RESUME\nexit /b 93\n", encoding="utf-8")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-m", "new version")
        self.git(self.seed, "push")
        return self.git(self.seed, "rev-parse", "HEAD")

    def assert_no_sync_or_runtime(self):
        self.assertFalse(self.sync.exists())
        self.assertFalse(self.record.exists())
        self.assertFalse((self.clone / ".venv").exists())
        self.assertFalse((self.base / "personal").exists())

    def test_first_use_pull_before_sync_and_fresh_runtime_for_both_commands(self):
        expected = self.pushed_change()
        self.env["UV_PROJECT_ENVIRONMENT"] = str(self.base / "wrong-env")
        self.env["VIRTUAL_ENV"] = str(self.base / "active-env")
        self.env["UV_PROJECT"] = str(self.base / "wrong-project")
        self.env["UV_WORKING_DIR"] = str(self.base / "wrong-directory")
        self.env["UV_WORKING_DIRECTORY"] = str(self.base / "wrong-directory-alias")
        for command in ("update", "upload"):
            with self.subTest(command=command):
                result = self.launch(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                record = json.loads(self.record.read_text(encoding="utf-8"))
                self.assertEqual(record["marker"], "new")
                self.assertEqual(record["prepared"], expected)
                self.assertEqual(Path(record["prefix"]), self.clone / ".venv")
        syncs = [json.loads(line) for line in self.sync.read_text().splitlines()]
        self.assertEqual(len(syncs), 2)
        for record in syncs:
            self.assertIn("# new lock from upstream", record["lock"])
            self.assertEqual(record["args"][:2], ["sync", "--locked"])
            self.assertEqual(Path(record["root"]), self.clone)
            self.assertEqual(Path(record["environment"]), self.clone / ".venv")
            self.assertIsNone(record["active"])
            self.assertEqual(record["redirects"], [None, None, None])
        self.assertFalse((self.base / "wrong-env").exists())

    def test_git_failure_does_not_sync_or_run(self):
        self.git(self.clone, "remote", "set-url", "team", str(self.base / "missing.git"))
        before = self.git(self.clone, "rev-parse", "HEAD")
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git pull", result.stderr)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), before)
        self.assert_no_sync_or_runtime()

    def test_sync_failure_preserves_new_checkout_and_exit_for_both(self):
        expected = self.pushed_change()
        self.env["PROBE_SYNC_EXIT"] = "17"
        for command in ("update", "upload"):
            result = self.launch(command)
            self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
            self.assertIn(expected, result.stderr)
            self.assertIn("ambiente não foi preparado", result.stderr)
            self.assertIn("Python externo", result.stderr)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), expected)

    def test_dirty_index_worktree_and_untracked_are_preserved_before_pull(self):
        tracked = self.clone / "README.md"
        original = tracked.read_bytes()
        for state in ("worktree", "index", "untracked"):
            with self.subTest(state=state):
                changed = tracked if state != "untracked" else self.clone / "my-work.txt"
                changed.write_bytes(b"my work\n")
                if state == "index":
                    self.git(self.clone, "add", "README.md")
                before = self.git(self.clone, "status", "--porcelain=v1")
                index = self.git(self.clone, "diff", "--cached")
                result = self.launch()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("não está limpo", result.stderr)
                self.assertEqual(changed.read_bytes(), b"my work\n")
                self.assertEqual(self.git(self.clone, "status", "--porcelain=v1"), before)
                self.assertEqual(self.git(self.clone, "diff", "--cached"), index)
                self.assertFalse((self.clone / ".git/FETCH_HEAD").exists())
                self.assert_no_sync_or_runtime()
                # Restauração somente da fixture temporária, entre cenários.
                tracked.write_bytes(original)
                self.git(self.clone, "add", "README.md")
                if state == "untracked":
                    changed.unlink()

    def test_local_commits_and_divergence_stop_with_rebase_autostash_enabled(self):
        self.git(self.clone, "config", "pull.rebase", "true")
        self.git(self.clone, "config", "rebase.autoStash", "true")
        self.git(self.clone, "config", "merge.autoStash", "true")
        self.git(self.clone, "commit", "--allow-empty", "-m", "local")
        head = self.git(self.clone, "rev-parse", "HEAD")
        for diverged in (False, True):
            if diverged:
                self.pushed_change()
            result = self.launch()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), head)
            self.assertEqual(self.git(self.clone, "stash", "list"), "")
            self.assert_no_sync_or_runtime()

    def test_no_upstream_and_detached_head_stop_before_pull(self):
        self.git(self.clone, "config", "--unset", "branch.trunk.remote")
        result = self.launch()
        self.assertIn("sem upstream", result.stderr)
        self.assert_no_sync_or_runtime()
        self.git(self.clone, "checkout", "--detach")
        result = self.launch()
        self.assertIn("HEAD destacado", result.stderr)
        self.assert_no_sync_or_runtime()

    def test_repo_selects_only_complete_target_relative_to_original_cwd(self):
        other = self.base / "B & (target)!^%"
        self.git(self.base, "clone", "--branch", "trunk", str(self.remote), str(other))
        self.pushed_change()
        original_head = self.git(self.clone, "rev-parse", "HEAD")
        for target in (os.path.relpath(other, self.caller), str(other)):
            result = self.launch("upload", ("--repo", target))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(Path(json.loads(self.record.read_text())["root"]), other)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), original_head)
        self.assertFalse((self.clone / ".venv").exists())
        self.assertFalse((self.caller / ".venv").exists())

    def test_incomplete_target_and_subfolder_do_not_sync_ancestor(self):
        (self.clone / "pyproject.toml").unlink()
        result = self.launch()
        self.assertIn("Alvo incompleto", result.stderr)
        self.assert_no_sync_or_runtime()
        result = self.launch(arguments=("--repo", self.clone / "src"))
        self.assertIn("raiz Git", result.stderr)
        self.assert_no_sync_or_runtime()

    def test_parser_has_no_git_uv_or_runtime_effects_in_all_four_launchers(self):
        marker = self.base / "git-called"
        self.env["PROBE_GIT"] = str(marker)
        self.make_tool("git", 'import os, pathlib, sys\npathlib.Path(os.environ["PROBE_GIT"]).touch()\nsys.exit(91)\n')
        # O pacote de UI nem pode ser importado durante parsing.
        (self.clone / "src/agentscloud/cli.py").write_text("raise AssertionError('CLI imported')\n", encoding="utf-8")
        for cmd in ((False, True) if os.name == "nt" else (False,)):
            for command in ("update", "upload"):
                for args, code in ((("--help",), 0), (("--unknown",), 2), (("--repo",), 2)):
                    with self.subTest(cmd=cmd, command=command, args=args):
                        result = self.launch(command, args, cmd=cmd)
                        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                        self.assertIn("usage:", result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        self.assert_no_sync_or_runtime()

    def test_head_change_during_sync_stops_before_runtime(self):
        self.env["PROBE_CHANGE_HEAD"] = "1"
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mudou durante o sync", result.stderr)
        self.assertFalse(self.record.exists())


    def test_upstream_ref_change_with_same_head_during_sync_stops(self):
        head = self.git(self.clone, "rev-parse", "HEAD")
        self.env["PROBE_CHANGE_UPSTREAM"] = "1"
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream mudou durante o sync", result.stderr)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), head)
        self.assertFalse(self.record.exists())


    def test_remote_change_after_sync_is_detected_without_another_merge(self):
        head = self.git(self.clone, "rev-parse", "HEAD")
        self.env["PROBE_PUSH"] = str(self.seed)
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream mudou", result.stderr)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), head)
        self.assertEqual(len(self.sync.read_text().splitlines()), 1)
        self.assertFalse(self.record.exists())

    @unittest.skipUnless(os.name == "nt", "Atualização de .cmd exige Windows.")
    def test_cmd_can_be_replaced_by_pull_without_resuming_new_file(self):
        expected = self.pushed_change(cmd_change=True)
        self.env["PROBE_EXIT"] = "7"
        result = self.launch("update", ("--repo", str(self.clone)), cmd=True)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertNotIn("UPDATED_FILE_MUST_NOT_RESUME", result.stdout)
        self.assertNotIn("Pressione", result.stdout)
        self.assertEqual(json.loads(self.record.read_text())["prepared"], expected)
        self.assertIn("UPDATED_FILE_MUST_NOT_RESUME", (self.clone / "update.cmd").read_text())

    @unittest.skipUnless(os.name == "nt", "Lançador .cmd exige Windows.")
    def test_cmd_upload_preserves_target_metacharacters_and_exit(self):
        self.env["PROBE_EXIT"] = "19"
        result = self.launch("upload", ("--repo", str(self.clone)), cmd=True)
        self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
        self.assertEqual(Path(json.loads(self.record.read_text())["root"]), self.clone)
        self.assertNotIn("Pressione", result.stdout)

    def test_python_in_own_venv_reports_sync_lock_failure_without_fallback(self):
        shutil.copytree(self.venv_template, self.clone / ".venv", symlinks=True)
        interpreter = self.clone / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.env["PROBE_SYNC_EXIT"] = "23"
        result = self.launch(python=str(interpreter))
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertIn("Python externo", result.stderr)
        self.assertFalse(self.record.exists())

    def test_missing_git_and_uv_report_setup_without_running_subprocess(self):
        for missing in ("git", "uv"):
            with self.subTest(missing=missing),                  patch.object(launcher.shutil, "which", side_effect=lambda name: None if name == missing else name),                  patch.object(launcher.subprocess, "run") as run:
                self.assertEqual(launcher._run("update", self.clone / "update.py", []), 1)
                run.assert_not_called()

    def test_prepared_cli_retains_personal_and_publication_confirmation(self):
        # Dados reais, com o código da CLI deste checkout e somente Git temporário.
        for path in (self.clone / "Agents").glob("*.toml"):
            if path.name != "base.toml":
                path.unlink()
        write_bundle(self.clone, {"base.toml": agent_bytes()})
        self.git(self.clone, "add", ".")
        self.git(self.clone, "commit", "-m", "data fixture")
        self.git(self.clone, "push")
        repo = Repository(self.clone)
        with patch.dict(os.environ, self.env, clear=True):
            upstream = repo.fetch_upstream()
            prepared = PreparedCheckout(repo.head(), "trunk", upstream.remote, upstream.branch_ref)
            ui = FakeUI(confirms=[False])
            self.assertEqual(main(["update", "--repo", str(self.clone)], ui=ui, prepared=prepared), 0)
            self.assertEqual(len(ui.prompts), 1)
            self.assertIn("Deseja instalar", ui.prompts[0])
            source = self.base / "new.toml"
            source.write_bytes(agent_bytes("new"))
            ui = FakeUI(confirms=[False, False], texts=[str(source), "Test", ""])
            self.assertEqual(main(["upload", "--repo", str(self.clone)], ui=ui, prepared=prepared), 0)
            self.assertIn("executar git push", ui.prompts[-1])
            self.assertFalse((self.clone / "Agents/new.toml").exists())

    def test_prepared_update_remote_change_during_confirmation_prevents_install(self):
        with patch.dict(os.environ, self.env, clear=True):
            repo = Repository(self.clone)
            upstream = repo.fetch_upstream()
            prepared = PreparedCheckout(repo.head(), "trunk", upstream.remote, upstream.branch_ref)
            ui = FakeUI(confirms=[True], on_confirm=lambda _: self.pushed_change())
            result = main(["update", "--repo", str(self.clone)], ui=ui, prepared=prepared)
            self.assertEqual(result, 1, ui.output)
            self.assertIn("upstream mudou", ui.output)
            self.assertFalse((self.base / "personal").exists())


    def real_cli_upstream(self, invalid=False):
        shutil.copy2(ROOT / "src/agentscloud/cli.py", self.seed / "src/agentscloud/cli.py")
        (self.seed / "src/agentscloud/ui.py").write_text(r"""import json, os
from pathlib import Path
class TerminalUI:
    def __init__(self):
        self.answers = iter(json.loads(os.environ.get("PROBE_ANSWERS", "[]")))
    def emit(self, text):
        with Path(os.environ["PROBE_UI"]).open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    def confirm(self, text):
        self.emit(text)
        return next(self.answers)
    def text(self, text):
        self.emit(text)
        return next(self.answers)
""", encoding="utf-8")
        if invalid:
            (self.seed / "catalog.toml").write_text("broken = [", encoding="utf-8")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-m", "real CLI with test UI")
        self.git(self.seed, "push")
        self.env["PROBE_UI"] = str(self.base / "ui.log")
        return self.base / "ui.log"

    def test_runtime_preserves_caller_for_relative_home_and_manual_upload(self):
        log = self.real_cli_upstream()
        self.env["CODEX_HOME"] = "relative-home"
        self.env["PROBE_ANSWERS"] = "[false]"
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(self.caller / "relative-home" / "agents"), log.read_text(encoding="utf-8"))
        self.assertNotIn("Deseja atualizar", log.read_text(encoding="utf-8"))
        (self.caller / "new.toml").write_bytes(agent_bytes("relative-new"))
        self.env["PROBE_ANSWERS"] = json.dumps([False, "new.toml", "Test", "", False])
        result = self.launch("upload")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = log.read_text(encoding="utf-8")
        self.assertIn(str(self.caller / "new.toml"), output)
        self.assertIn("executar git push", output)
        self.assertIn("Upload recusado", output)
        self.assertFalse((self.clone / "Agents/new.toml").exists())
        self.assertFalse((self.caller / "relative-home").exists())
        self.assertFalse((self.clone / "relative-home").exists())

    def test_invalid_catalog_pulled_blocks_real_flow_before_personal_prompts(self):
        log = self.real_cli_upstream(invalid=True)
        expected = self.git(self.seed, "rev-parse", "HEAD")
        for command in ("update", "upload"):
            result = self.launch(command)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), expected)
        self.assertIn("Erro:", log.read_text(encoding="utf-8"))
        self.assertNotIn("Deseja", log.read_text(encoding="utf-8"))
        self.assertFalse((self.base / "personal").exists())

    @unittest.skipUnless(os.name == "nt", "Descoberta Python do .cmd exige Windows.")
    def test_cmd_without_python_has_visible_setup_error(self):
        self.env["PATH"] = str(self.base / "empty-path")
        result = self.launch(cmd=True, arguments=("--help",))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Python nao encontrado", result.stdout)
        self.assert_no_sync_or_runtime()


if __name__ == "__main__":
    unittest.main()
