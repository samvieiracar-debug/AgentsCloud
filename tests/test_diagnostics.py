"""Diagnóstico usa stdlib, temporários e remotos Git locais; nenhum perfil real."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from agentscloud import diagnostics
from agentscloud.processes import CommandResult, EventLog, run_command

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)


def temporary():
    parent = Path(os.environ["LOCALAPPDATA"]) / "Temp" if os.name == "nt" else None
    return tempfile.TemporaryDirectory(prefix="agentscloud-diagnostic-tests-", dir=parent)


def manifests(root):
    (root / "pyproject.toml").write_text('[project]\nname="agentscloud"\nversion="0.1.0"\nrequires-python=">=3.11"\ndependencies=[]\n', encoding="utf-8")
    (root / "uv.lock").write_text('version=1\npackage=[]\n', encoding="utf-8")


def check(doctor, name):
    return next(item for item in doctor.checks if item.name == name)


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        manifests(self.root)

    def test_missing_tools_and_venv_do_not_require_questionary_or_execute_commands(self):
        runner = Mock()
        doctor = diagnostics.Diagnostics(self.root, runner=runner, lookup=lambda _: None)
        doctor.collect()
        self.assertEqual(check(doctor, "git").status, "falhou")
        self.assertEqual(check(doctor, "uv").status, "falhou")
        self.assertEqual(check(doctor, ".venv/dependências").status, "falhou")
        self.assertEqual(check(doctor, "Logs").status, "pulado")
        runner.assert_not_called()
        self.assertFalse((self.root / ".git").exists())

    def test_invalid_lock_does_not_run_uv_sync(self):
        (self.root / "uv.lock").write_text("broken = [", encoding="utf-8")
        runner = Mock(return_value=CommandResult(0, b"uv test"))
        doctor = diagnostics.Diagnostics(self.root, runner=runner, lookup=lambda name: "uv" if name == "uv" else None)
        doctor.collect()
        self.assertEqual(check(doctor, "uv.lock").status, "falhou")
        self.assertFalse(any("sync" in call.args[0] for call in runner.call_args_list))

    def test_uv_probe_is_offline_dry_run_targeted_and_cache_failure_inconclusive(self):
        seen = []
        def runner(argv, **kwargs):
            seen.append((argv, kwargs))
            if "sync" in argv:
                return CommandResult(1, stderr=b"package unavailable in cache while offline", category="indeterminado")
            return CommandResult(0, b"uv test")
        environment = {"UV_PROJECT": "wrong", "UV_WORKING_DIR": "wrong", "UV_WORKING_DIRECTORY": "wrong", "UV_PROJECT_ENVIRONMENT": "wrong", "VIRTUAL_ENV": "wrong"}
        with patch.dict(os.environ, environment):
            doctor = diagnostics.Diagnostics(self.root, runner=runner, lookup=lambda name: "uv" if name == "uv" else None)
            doctor.collect()
        self.assertEqual(check(doctor, "Consistência do lock").status, "inconclusivo")
        argv, kwargs = next(pair for pair in seen if "sync" in pair[0])
        for flag in ("--locked", "--dry-run", "--offline", "--no-python-downloads", "--cache-dir"):
            self.assertIn(flag, argv)
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["env"]["UV_PROJECT_ENVIRONMENT"], str(self.root / ".venv"))
        for key in ("UV_PROJECT", "UV_WORKING_DIR", "UV_WORKING_DIRECTORY", "VIRTUAL_ENV"):
            self.assertNotIn(key, kwargs["env"])
        self.assertFalse((self.root / ".venv").exists())
        self.assertTrue(all(pair[1]["log"] is None and not pair[1]["interactive"] for pair in seen))

    def test_venv_probe_checks_prefix_import_and_pinned_versions(self):
        interpreter = self.root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        interpreter.parent.mkdir(parents=True)
        interpreter.write_bytes(b"test interpreter")
        (self.root / "uv.lock").write_text('version=1\n[[package]]\nname="questionary"\nversion="2.1.1"\nsource={registry="https://example.invalid"}\n', encoding="utf-8")
        result = CommandResult(0, json.dumps({"prefix": str(self.root / ".venv"), "python": [3, 11, 9], "versions": {"questionary": "2.1.1"}}).encode())
        runner = Mock(return_value=result)
        doctor = diagnostics.Diagnostics(self.root, runner=runner, lookup=lambda _: None)
        doctor.collect()
        self.assertEqual(check(doctor, ".venv/dependências").status, "ok")
        self.assertIn("-I", runner.call_args.args[0])
        self.assertIn("-B", runner.call_args.args[0])
        self.assertIn("import questionary", runner.call_args.args[0][4])
        runner.return_value = CommandResult(1, stderr=b"No module named 'questionary'", category="indeterminado")
        doctor.collect()
        self.assertEqual(check(doctor, ".venv/dependências").status, "falhou")

    def test_repairs_decline_eof_and_manifest_race_do_not_sync(self):
        doctor = diagnostics.Diagnostics(self.root, lookup=lambda _: None)
        doctor.collect()
        doctor.tools["uv"] = "uv"
        doctor.runner = Mock(return_value=CommandResult(0))
        doctor.repairs(input_fn=lambda _: "n", emit=lambda _: None)
        doctor.runner.assert_not_called()
        with self.assertRaises(EOFError):
            doctor.repairs(input_fn=Mock(side_effect=EOFError), emit=lambda _: None)
        doctor.runner.assert_not_called()
        def confirm(_):
            (self.root / "uv.lock").write_text('version=2\npackage=[]\n', encoding="utf-8")
            return "s"
        doctor.repairs(input_fn=confirm, emit=lambda _: None)
        doctor.runner.assert_not_called()

    def test_sync_needs_explicit_consent_and_uses_target_venv(self):
        doctor = diagnostics.Diagnostics(self.root, offline=True, lookup=lambda _: None)
        doctor.collect()
        doctor.tools["uv"] = "uv"
        doctor.runner = Mock(return_value=CommandResult(0))
        self.assertTrue(doctor.repairs(input_fn=lambda _: "s", emit=lambda _: None))
        argv = doctor.runner.call_args.args[0]
        kwargs = doctor.runner.call_args.kwargs
        self.assertEqual(argv[:3], ["uv", "sync", "--locked"])
        self.assertIn("--offline", argv)
        self.assertEqual(argv[argv.index("--project") + 1], str(self.root))
        self.assertEqual(kwargs["env"]["UV_PROJECT_ENVIRONMENT"], str(self.root / ".venv"))
        self.assertTrue(kwargs["interactive"])

    @unittest.skipUnless(os.name == "nt", "Oferta winget específica do Windows")
    def test_missing_tool_installation_requires_separate_consent(self):
        available = {"winget": "winget"}
        doctor = diagnostics.Diagnostics(self.root, lookup=available.get, runner=Mock(return_value=CommandResult(0)))
        doctor.collect()
        doctor.repairs(input_fn=lambda _: "n", emit=lambda _: None)
        doctor.runner.assert_not_called()
        replies = iter(("s", "n"))
        output = []
        doctor.repairs(input_fn=lambda _: next(replies), emit=output.append)
        self.assertEqual(doctor.runner.call_count, 1)
        self.assertIn("Git.Git", doctor.runner.call_args.args[0])
        self.assertNotIn("--accept-source-agreements", doctor.runner.call_args.args[0])
        self.assertTrue(any("ainda não está disponível" in line for line in output))

    def test_junction_venv_never_runs_probe_or_sync(self):
        outside = self.root / "outside-environment"
        outside.mkdir()
        link = self.root / ".venv"
        if os.name == "nt":
            result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(link), str(outside)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(outside, target_is_directory=True)
        runner = Mock(return_value=CommandResult(0, b"uv test"))
        doctor = diagnostics.Diagnostics(self.root, runner=runner, lookup=lambda name: "uv" if name == "uv" else None)
        doctor.collect()
        self.assertEqual(check(doctor, ".venv/dependências").status, "falhou")
        self.assertIn("link/junção", check(doctor, ".venv/dependências").detail)
        doctor.repairs(input_fn=lambda _: "s", emit=lambda _: None)
        self.assertFalse(any("sync" in call.args[0] for call in runner.call_args_list))
        self.assertEqual(list(outside.iterdir()), [])

    def test_venv_link_race_after_consent_is_rejected(self):
        doctor = diagnostics.Diagnostics(self.root, lookup=lambda _: None)
        doctor.collect()
        doctor.tools["uv"] = "uv"
        doctor.runner = Mock(return_value=CommandResult(0))
        with patch.object(doctor, "venv_is_local", side_effect=[True, False]):
            doctor.repairs(input_fn=lambda _: "s", emit=lambda _: None)
        doctor.runner.assert_not_called()

    def test_progress_is_emitted_before_the_command_wait(self):
        order = []
        def runner(argv, **kwargs):
            order.append("command")
            return CommandResult(0, b"uv test")
        doctor = diagnostics.Diagnostics(self.root, runner=runner,
                                         lookup=lambda name: "uv" if name == "uv" else None,
                                         progress=lambda text: order.append(text))
        doctor.collect()
        self.assertTrue(order[0].startswith("Verificando uv"))
        self.assertEqual(order[1], "command")
        self.assertIn("limite: 30s", order[-2])

    def test_logs_are_readable_relevant_and_category_guides_next_action(self):
        event = {"time": "2026-09-07", "operation": "git-push", "category": "timeout", "returncode": "124", "commit": "a" * 40}
        self.assertTrue(diagnostics.Diagnostics.relevant_event(event))
        detail = diagnostics.Diagnostics.describe_event(event)
        self.assertIn("limite de tempo", detail)
        self.assertIn("consulte o remoto", detail)
        self.assertIn("a" * 40, detail)
        self.assertFalse(diagnostics.Diagnostics.relevant_event({"operation": "git-config", "category": "expected", "returncode": "1"}))

    def test_help_parser_and_noninteractive_never_offer_repairs(self):
        with patch.object(diagnostics.Diagnostics, "collect") as collect, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                diagnostics.main(["--help"])
            self.assertEqual(caught.exception.code, 0)
            collect.assert_not_called()
        with patch.object(diagnostics.Diagnostics, "collect"), patch.object(diagnostics.Diagnostics, "repairs") as repair, \
             patch.object(diagnostics.sys.stdin, "isatty", return_value=True), patch.object(diagnostics.sys.stdout, "isatty", return_value=True), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostics.main(["--non-interactive", "--repair", "--repo", str(self.root)]), 0)
            repair.assert_not_called()

    def test_default_interactive_offers_repairs_and_eof_returns_130(self):
        with patch.object(diagnostics.Diagnostics, "collect"), patch.object(diagnostics.Diagnostics, "render"), \
             patch.object(diagnostics.Diagnostics, "repairs", return_value=False) as repair, \
             patch.object(diagnostics.sys, "stdin", Mock(isatty=lambda: True)), \
             patch.object(diagnostics.sys, "stdout", Mock(isatty=lambda: True)):
            self.assertEqual(diagnostics.main(["--repo", str(self.root)]), 0)
            repair.assert_called_once()
            repair.side_effect = EOFError
            self.assertEqual(diagnostics.main(["--repo", str(self.root)]), 130)

    def test_outdated_lock_is_failure_not_merely_cache_inconclusion(self):
        def runner(argv, **kwargs):
            return (CommandResult(1, stderr=b"The lockfile needs to be updated, but --locked was provided", category="indeterminado")
                    if "sync" in argv else CommandResult(0, b"uv test"))
        doctor = diagnostics.Diagnostics(self.root, runner=runner, lookup=lambda name: "uv" if name == "uv" else None)
        doctor.collect()
        self.assertEqual(check(doctor, "Consistência do lock").status, "falhou")

    def test_export_sanitizes_and_never_overwrites(self):
        secret = "SECRET_SENTINEL"
        def collect(doctor):
            doctor.add("fake", "falhou", f"https://user:{secret}@example.invalid/r?token={secret} Authorization: {secret}")
        output = self.root / "report.json"
        with patch.object(diagnostics.Diagnostics, "collect", collect), redirect_stdout(io.StringIO()) as console:
            self.assertEqual(diagnostics.main(["--non-interactive", "--output", str(output)]), 1)
        self.assertNotIn(secret, output.read_text(encoding="utf-8") + console.getvalue())
        original = output.read_bytes()
        with patch.object(diagnostics.Diagnostics, "collect", collect), redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostics.main(["--non-interactive", "--output", str(output)]), 1)
        self.assertEqual(output.read_bytes(), original)


@unittest.skipUnless(GIT, "Git indisponível para laboratórios temporários")
class GitDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "clone & espaço"
        self.repo.mkdir()
        self.bare = self.base / "remote.git"
        self.environment = dict(os.environ, HOME=str(self.base), USERPROFILE=str(self.base), GIT_CONFIG_NOSYSTEM="1",
                                GIT_CONFIG_GLOBAL=str(self.base / "empty-global-config"), GIT_TERMINAL_PROMPT="0")
        self.git("init", "--bare", str(self.bare), cwd=self.base)
        self.git("init", "-b", "main")
        self.git("config", "--local", "user.name", "Diagnostic Fixture")
        self.git("config", "--local", "user.email", "fixture@example.invalid")
        manifests(self.repo)
        self.git("add", "pyproject.toml", "uv.lock")
        self.git("commit", "-m", "fixture")
        self.git("remote", "add", "origin", str(self.bare))
        self.git("push", "-u", "origin", "main")
        self.seen = []
        self.interceptor = None

    def git(self, *args, cwd=None):
        result = subprocess.run([GIT, "-C", str(cwd or self.repo), *args], env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if result.returncode:
            self.fail(result.stderr.decode(errors="replace"))
        return result.stdout.decode(errors="replace").strip()

    def runner(self, argv, **kwargs):
        self.seen.append((argv, kwargs))
        if self.interceptor:
            result = self.interceptor(argv, kwargs)
            if result is not None:
                return result
        kwargs["env"] = self.environment
        return run_command(argv, **kwargs)

    def doctor(self, offline=False):
        doctor = diagnostics.Diagnostics(self.repo, offline=offline, runner=self.runner,
                                         lookup=lambda name: GIT if name == "git" else None)
        doctor.collect()
        return doctor

    def test_offline_checks_local_status_upstream_counts_and_no_persistent_log(self):
        doctor = self.doctor(offline=True)
        self.assertEqual(check(doctor, "Upstream").status, "ok")
        self.assertEqual(check(doctor, "Ahead/behind em cache").status, "ok")
        self.assertEqual(check(doctor, "Leitura remota").status, "pulado")
        self.assertFalse(any("ls-remote" in argv for argv, _ in self.seen))
        self.assertFalse((self.repo / ".git/agentscloud").exists())
        forbidden = {"fetch", "pull", "push", "reset", "stash"}
        self.assertFalse(any(forbidden.intersection(argv) for argv, _ in self.seen))
        self.assertTrue(all(kwargs["timeout"] <= 30 for _, kwargs in self.seen))

    def test_public_read_is_not_push_proof_and_uses_exact_push_destination(self):
        other = self.base / "other.git"
        self.git("clone", "--bare", str(self.repo), str(other), cwd=self.base)
        self.git("remote", "set-url", "--push", "origin", str(other))
        doctor = self.doctor()
        self.assertEqual(check(doctor, "Leitura remota").status, "ok")
        self.assertIn("não comprova", check(doctor, "Leitura remota").detail)
        argv, kwargs = next(pair for pair in self.seen if "ls-remote" in pair[0])
        self.assertEqual(argv[-2:], [str(other), "refs/heads/main"])
        self.assertFalse(kwargs["interactive"])
        self.assertEqual(kwargs["timeout"], diagnostics.NETWORK_TIMEOUT)

    def test_dirty_and_ahead_are_distinguished(self):
        (self.repo / "change.txt").write_text("pending", encoding="utf-8")
        doctor = self.doctor(offline=True)
        self.assertEqual(check(doctor, "Checkout/índice").status, "falhou")
        self.git("add", "change.txt")
        self.git("commit", "-m", "pending")
        doctor = self.doctor()
        self.assertEqual(check(doctor, "Checkout/índice").status, "ok")
        self.assertEqual(check(doctor, "Relação remota atual").status, "ok")
        self.assertIn("Adiantado: 1", check(doctor, "Relação remota atual").detail)

    def test_missing_upstream_repair_is_validated_and_local(self):
        self.git("branch", "--unset-upstream")
        doctor = self.doctor(offline=True)
        self.assertEqual(check(doctor, "Upstream").status, "falhou")
        replies = iter(("refs/remotes/origin/main", "s"))
        self.assertTrue(doctor.repairs(input_fn=lambda _: next(replies), emit=lambda _: None))
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "@{upstream}"), "origin/main")
        self.assertTrue(any("--set-upstream-to=refs/remotes/origin/main" in argv for argv, _ in self.seen))
        self.assertTrue((self.repo / ".git/agentscloud/logs/events.jsonl").is_file())

    def test_missing_identity_is_not_login_and_repaired_only_after_specific_consent(self):
        self.git("config", "--local", "--unset", "user.name")
        doctor = self.doctor(offline=True)
        replies = iter(("New Fixture Name", "n"))
        doctor.repairs(input_fn=lambda _: next(replies), emit=lambda _: None)
        result = run_command([GIT, "-C", str(self.repo), "config", "--get", "user.name"], env=self.environment)
        self.assertEqual(result.returncode, 1)
        replies = iter(("New Fixture Name", "s"))
        doctor.repairs(input_fn=lambda _: next(replies), emit=lambda _: None)
        self.assertEqual(self.git("config", "--local", "--get", "user.name"), "New Fixture Name")
        self.assertIn("não é login", check(doctor, "user.name").detail)

    def test_remote_missing_auth_timeout_and_secret_outputs_are_actionable(self):
        scenarios = ((2, "indeterminado", b"", "ref exata não existe"),
                     (128, "autenticacao", b"Authentication failed https://user:SECRET_SENTINEL@example.invalid/r?token=SECRET_SENTINEL", "autenticacao"),
                     (124, "timeout", b"connection timed out", "timeout"))
        for code, category, stderr, expected in scenarios:
            with self.subTest(category=category, code=code):
                self.interceptor = lambda argv, kwargs: CommandResult(code, stderr=stderr, category=category) if "ls-remote" in argv else None
                doctor = self.doctor()
                self.assertIn(expected, check(doctor, "Leitura remota").detail)
                lines = []
                doctor.render(lines.append)
                self.assertNotIn("SECRET_SENTINEL", "\n".join(lines))

    def test_helper_content_is_not_read_and_old_logs_are_sanitized(self):
        self.git("config", "--local", "credential.helper", "!secret-SECRET_SENTINEL")
        log = EventLog(self.repo / ".git/agentscloud/logs")
        log.directory.mkdir(parents=True)
        log.path.write_text(json.dumps({"operation": "upload", "outcome": "token=SECRET_SENTINEL", "argv": "SECRET_SENTINEL"}) + "\n", encoding="utf-8")
        doctor = self.doctor(offline=True)
        lines = []
        doctor.render(lines.append)
        self.assertNotIn("SECRET_SENTINEL", "\n".join(lines))
        helper_calls = [argv for argv, _ in self.seen if any("credential" in arg for arg in argv)]
        self.assertTrue(all("--name-only" in argv for argv in helper_calls))
        self.assertIn("Helper configurado", check(doctor, "Credenciais").detail)

    def test_distinct_push_remote_override_blocks_every_destination_probe(self):
        for key in ("branch.main.pushRemote", "remote.pushDefault"):
            with self.subTest(key=key):
                self.git("config", "--local", key, "other")
                self.seen = []
                doctor = self.doctor()
                self.assertEqual(check(doctor, "Destino de push").status, "falhou")
                self.assertIn("pushRemote/pushDefault", check(doctor, "Destino de push").detail)
                self.assertEqual(check(doctor, "Leitura remota").status, "pulado")
                self.assertFalse(any("ls-remote" in argv or "get-url" in argv for argv, _ in self.seen))
                self.git("config", "--local", "--unset", key)

    def test_matching_push_override_is_allowed_and_branch_override_has_precedence(self):
        for key in ("branch.main.pushRemote", "remote.pushDefault"):
            with self.subTest(key=key):
                self.git("config", "--local", key, "origin")
                doctor = self.doctor()
                self.assertEqual(check(doctor, "Destino de push").status, "ok")
                self.assertEqual(check(doctor, "Leitura remota").status, "ok")
                self.git("config", "--local", "--unset", key)
        self.git("config", "--local", "remote.pushDefault", "other")
        self.git("config", "--local", "branch.main.pushRemote", "origin")
        self.seen = []
        doctor = self.doctor()
        self.assertEqual(check(doctor, "Leitura remota").status, "ok")
        self.assertFalse(any("remote.pushDefault" in argv for argv, _ in self.seen))
        query = next(argv for argv, _ in self.seen if "ls-remote" in argv)
        self.assertEqual(query[-2:], [str(self.bare), "refs/heads/main"])

    def test_multiple_destinations_are_not_queried(self):
        self.git("remote", "set-url", "--add", "--push", "origin", str(self.bare))
        self.git("remote", "set-url", "--add", "--push", "origin", str(self.base / "other.git"))
        doctor = self.doctor()
        self.assertEqual(check(doctor, "Destino de push").status, "falhou")
        self.assertFalse(any("ls-remote" in argv for argv, _ in self.seen))


class WrapperTests(unittest.TestCase):
    def test_redirected_cp1252_console_renders_and_exports_unicode(self):
        with temporary() as directory:
            report = Path(directory) / "report.json"
            script = (
                "import sys; from unittest.mock import patch; "
                "sys.stdout.reconfigure(encoding='cp1252', errors='strict'); "
                "sys.stderr.reconfigure(encoding='cp1252', errors='strict'); "
                "sys.path.insert(0, sys.argv[1]); "
                "sys.path.insert(0, sys.argv[1] + '/src'); "
                "import diagnostico; from agentscloud.diagnostics import Diagnostics; "
                "collect = lambda self: self.add('Destino', 'ok', 'origin \u2192 main \U0001f9ea'); "
                "p = patch.object(Diagnostics, 'collect', collect); p.start(); "
                "raise SystemExit(diagnostico.launch(sys.argv[2:]))"
            )
            env = dict(os.environ, AGENTSCLOUD_NO_PAUSE="1", PYTHONIOENCODING="utf-8")
            for arguments, expected in ((["--non-interactive", "--output", str(report)], 0),
                                        (["--unknown-\u2192"], 2)):
                with self.subTest(arguments=arguments):
                    result = subprocess.run([BASE_PYTHON, "-E", "-s", "-B", "-c", script, str(ROOT), *arguments],
                                            cwd=directory, env=env, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertNotIn(b"Traceback", result.stderr)
                    output = (result.stdout + result.stderr).decode("utf-8")
                    self.assertIn("\u2192", output)
            document = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(document["checks"][0]["detail"], "origin \u2192 main \U0001f9ea")

    def test_python_help_and_parser_work_without_site_venv_or_questionary(self):
        with temporary() as directory:
            root = Path(directory)
            for filename in ("diagnostico.py", "_launcher.py", "src/agentscloud/__init__.py", "src/agentscloud/processes.py", "src/agentscloud/diagnostics.py"):
                target = root / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / filename, target)
            for arguments, code in ((["--help"], 0), (["--unknown"], 2)):
                result = subprocess.run([BASE_PYTHON, "-S", "-B", str(root / "diagnostico.py"), *arguments],
                                        cwd=root, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, code, result.stderr)
            env = dict(os.environ, PATH="", HOME=str(root), USERPROFILE=str(root), AGENTSCLOUD_NO_PAUSE="1")
            result = subprocess.run([BASE_PYTHON, "-S", "-B", str(root / "diagnostico.py"), "--offline", "--non-interactive"],
                                    cwd=root, env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(b"[falhou] git:", result.stdout)
            self.assertIn(b"[falhou] uv:", result.stdout)
            self.assertNotIn(b"Traceback", result.stderr)
            self.assertFalse((root / ".venv").exists())
            self.assertFalse((root / ".git").exists())
            self.assertFalse(list(root.rglob("__pycache__")))

    def test_wrapper_preserves_pause_return_and_old_python_message(self):
        spec = importlib.util.spec_from_file_location("diagnostic_wrapper_test", ROOT / "diagnostico.py")
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        with patch.object(wrapper, "_owns_python_console", return_value=True), patch.object(wrapper, "_wait_for_close") as pause, \
             patch.object(diagnostics, "main", return_value=7):
            self.assertEqual(wrapper.launch(["--offline"]), 7)
            pause.assert_called_once()
        with patch.object(wrapper.sys, "version_info", (3, 9, 0)), patch.object(wrapper, "_owns_python_console", return_value=False), \
             patch.object(diagnostics, "main") as main:
            self.assertEqual(wrapper.launch([]), 1)
            main.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Lançador .cmd específico do Windows")
    def test_cmd_help_preserves_return_without_preparation_or_pause(self):
        env = dict(os.environ, AGENTSCLOUD_NO_PAUSE="1")
        for args, code in ((["--help"], 0), (["--unknown"], 2)):
            result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(ROOT / "diagnostico.cmd"), *args],
                                    cwd=ROOT, env=env, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertNotIn(b"Pressione", result.stdout)
            self.assertNotIn(b"Atualizando clone", result.stdout)


if __name__ == "__main__":
    unittest.main()
