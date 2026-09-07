"""Regressões R04: consentimento do commit, alvo Git e sondagens sem askpass."""

import http.server
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_agentscloud as fixtures
import test_upload_recovery as recovery_fixtures
from agentscloud import processes
from agentscloud.cli import main
from agentscloud.diagnostics import Diagnostics
from agentscloud.git import Repository

GIT = shutil.which("git")


@unittest.skipUnless(GIT, "Git necessário para reproduções locais")
class CommitScopeTests(unittest.TestCase):
    setUp = fixtures.GitFlowTests.setUp
    git = fixtures.GitFlowTests.git
    identity = fixtures.GitFlowTests.identity
    head = fixtures.GitFlowTests.head
    personal_agent = fixtures.GitFlowTests.personal_agent
    local_commit = recovery_fixtures.RecoveryTests.local_commit

    def contribute(self):
        source = self.personal_agent()
        ui = fixtures.FakeUI([False, True], [str(source), "Revisão", ""])
        return main(["upload", "--repo", str(self.clone)], ui=ui), ui

    def assert_not_published(self, code, ui):
        self.assertEqual(code, 1, ui.output)
        self.assertEqual(self.head(self.bare), self.initial)
        self.assertNotEqual(self.head(self.clone), self.initial)
        self.assertEqual(len(ui.prompts), 5)  # Duas confirmações e três perguntas de metadados.
        self.assertIn("contribuição aprovada", ui.output)

    def test_commit_after_method_return_is_preserved_without_publication(self):
        original = Repository.commit_agent
        recorded = {}
        def concurrent(repo, paths, name):
            approved = original(repo, paths, name)
            recorded["approved"] = approved
            recorded["extra"] = self.local_commit("unreviewed-private.txt")
            return approved
        with patch.object(Repository, "commit_agent", concurrent):
            code, ui = self.contribute()
        self.assert_not_published(code, ui)
        self.assertEqual(self.head(self.clone), recorded["extra"])
        self.assertNotEqual(recorded["approved"], recorded["extra"])
        self.assertTrue((self.clone / "unreviewed-private.txt").exists())

    def test_real_post_commit_hook_cannot_publish_an_additional_commit(self):
        hook = self.clone / ".git/hooks/post-commit"
        hook.write_bytes(b"#!/bin/sh\nprintf unreviewed > unreviewed-private.txt\ngit add -- unreviewed-private.txt\ngit -c core.hooksPath=/dev/null commit -m concurrent\n")
        hook.chmod(0o755)
        code, ui = self.contribute()
        self.assert_not_published(code, ui)
        self.assertEqual(self.git(self.clone, "rev-list", "--count", self.initial + "..HEAD").strip(), b"2")
        self.assertTrue((self.clone / "unreviewed-private.txt").exists())

    def test_same_parent_amend_of_approved_file_is_not_approved_content(self):
        original = Repository.commit_agent
        def altered(repo, paths, name):
            original(repo, paths, name)
            with (self.clone / "README.md").open("a", encoding="utf-8") as out:
                out.write("\nConteúdo que não estava na prévia.\n")
            self.git(self.clone, "commit", "-am", "substituto", "--amend")
            return repo.head()
        with patch.object(Repository, "commit_agent", altered):
            code, ui = self.contribute()
        self.assert_not_published(code, ui)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD^").decode().strip(), self.initial)

    def test_same_parent_amend_with_unreviewed_path_is_refused(self):
        original = Repository.commit_agent
        def altered(repo, paths, name):
            original(repo, paths, name)
            (self.clone / "unreviewed-private.txt").write_text("unreviewed", encoding="utf-8")
            self.git(self.clone, "add", "unreviewed-private.txt")
            self.git(self.clone, "commit", "--amend", "--no-edit")
            return repo.head()
        with patch.object(Repository, "commit_agent", altered):
            code, ui = self.contribute()
        self.assert_not_published(code, ui)

    def test_approved_content_with_git_crlf_conversion_can_be_published(self):
        self.git(self.clone, "config", "core.autocrlf", "true")
        code, ui = self.contribute()
        self.assertEqual(code, 0, ui.output)
        self.assertEqual(self.head(self.clone), self.head(self.bare))
        self.assertEqual(self.git(self.clone, "rev-list", "--count", self.initial + "..HEAD").strip(), b"1")


@unittest.skipUnless(GIT, "Git necessário para reproduções locais")
class GitEnvironmentTests(unittest.TestCase):
    setUp = fixtures.GitFlowTests.setUp
    git = fixtures.GitFlowTests.git
    identity = fixtures.GitFlowTests.identity
    head = fixtures.GitFlowTests.head

    def redirect(self):
        external = self.root / "external"
        external.mkdir()
        self.git(external, "init", "-b", "main")
        before = (external / ".git/config").read_bytes()
        env = dict(os.environ, GIT_DIR=str(external / ".git"), GIT_WORK_TREE=str(self.clone),
                   GIT_COMMON_DIR=str(external / ".git"), GIT_INDEX_FILE=str(external / "foreign-index"),
                   GIT_OBJECT_DIRECTORY=str(external / ".git/objects"), GIT_NAMESPACE="unreviewed")
        return external, before, env

    def test_diagnostic_repairs_only_announced_repository_with_inherited_redirects(self):
        external, before, env = self.redirect()
        self.git(self.clone, "config", "--unset", "user.name")
        self.git(self.clone, "config", "--unset", "user.email")
        def runner(argv, **kwargs):
            return processes.run_command(argv, **{**kwargs, "env": env})
        doctor = Diagnostics(self.clone, offline=True, runner=runner,
                             lookup=lambda name: GIT if name == "git" else None)
        doctor.collect()
        self.assertTrue(doctor.git_root)
        replies = iter(("Visible User", "s", "visible@example.invalid", "s"))
        doctor.repairs(input_fn=lambda _: next(replies), emit=lambda _: None)
        self.assertEqual(self.git(self.clone, "config", "--local", "--get", "user.name").strip(), b"Visible User")
        self.assertEqual((external / ".git/config").read_bytes(), before)
        self.assertFalse((external / "foreign-index").exists())

    def test_repository_and_bootstrap_ignore_redirects_in_all_modes(self):
        import _launcher
        external, before, env = self.redirect()
        with patch.dict(os.environ, env):
            repo = Repository(self.clone)
            self.assertEqual(repo.head(), self.initial)
            repo.run("config", "--local", "agentscloud.fixture", "repository", interactive=True)
            with patch.object(_launcher, "_PROCESS", vars(processes)), patch.object(_launcher, "_LOG", None):
                _launcher._git(self.clone, "config", "--local", "agentscloud.fixture", "bootstrap")
                actual = _launcher._git(self.clone, "rev-parse", "--absolute-git-dir")
                self.assertEqual(Path(actual).resolve(), (self.clone / ".git").resolve())
        self.assertEqual(self.git(self.clone, "config", "--local", "--get", "agentscloud.fixture").strip(), b"bootstrap")
        self.assertEqual((external / ".git/config").read_bytes(), before)

    def test_config_environment_injection_cannot_restore_repository_redirection(self):
        external, before, env = self.redirect()
        env.update(GIT_CONFIG=str(external / ".git/config"),
                   GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.worktree", GIT_CONFIG_VALUE_0=str(external),
                   GIT_CONFIG_PARAMETERS="'core.worktree'='" + str(external) + "'")
        result = processes.run_command([GIT, "-C", str(self.clone), "rev-parse", "--show-toplevel"], env=env)
        self.assertEqual(result.returncode, 0, result.message)
        self.assertEqual(Path(result.stdout.decode().strip()).resolve(), self.clone.resolve())
        self.assertEqual((external / ".git/config").read_bytes(), before)

    def test_repair_revalidation_detects_git_config_path_change(self):
        doctor = Diagnostics(self.clone, offline=True, lookup=lambda name: GIT if name == "git" else None)
        doctor.collect()
        self.assertTrue(doctor._unchanged_root())
        doctor.git_config_path = self.root / "different-config"
        self.assertFalse(doctor._unchanged_root())


@unittest.skipUnless(GIT, "Git necessário para HTTP 401 local")
class AskpassTests(unittest.TestCase):
    def test_local_http401_does_not_prompt_but_interactive_git_still_can(self):
        parent = Path(os.environ["LOCALAPPDATA"]) / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(prefix="agentscloud-askpass-", dir=parent) as temp:
            root = Path(temp)
            marker = root / "invoked"
            askpass = root / ("askpass.cmd" if os.name == "nt" else "askpass.sh")
            if os.name == "nt":
                askpass.write_text('@echo off\necho called>>"' + str(marker) + '"\necho synthetic-user\n', encoding="utf-8")
            else:
                askpass.write_text("#!/bin/sh\nprintf called >> '" + str(marker) + "'\nprintf synthetic-user\n", encoding="utf-8")
                askpass.chmod(0o755)
            env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(root / "empty-global"),
                       GIT_TERMINAL_PROMPT="0")
            result = subprocess.run([GIT, "-C", str(root), "init", "-b", "main"], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            class Unauthorized(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="synthetic-local"')
                    self.end_headers()
                def log_message(self, *args):
                    pass
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Unauthorized)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            try:
                url = f"http://127.0.0.1:{server.server_port}/fixture.git"
                for mechanism in ("GIT_ASKPASS", "core.askPass", "SSH_ASKPASS"):
                    with self.subTest(mechanism=mechanism):
                        probe_env = dict(env)
                        if mechanism == "core.askPass":
                            result = subprocess.run([GIT, "-C", str(root), "config", "--local", "core.askPass", str(askpass)],
                                                    env=env, capture_output=True, timeout=10)
                            self.assertEqual(result.returncode, 0, result.stderr)
                        else:
                            probe_env[mechanism] = str(askpass)
                        def runner(argv, **kwargs):
                            return processes.run_command(argv, **{**kwargs, "env": probe_env})
                        doctor = Diagnostics(root, runner=runner)
                        doctor.tools["git"] = GIT
                        result = doctor.git("ls-remote", "--", url, "refs/heads/main", timeout=8)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(marker.exists(), mechanism + " foi executado na sondagem")
                interactive_env = dict(env, GIT_ASKPASS=str(askpass))
                result = processes.run_command([GIT, "-C", str(root), "ls-remote", "--", url, "refs/heads/main"],
                                               env=interactive_env, interactive=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(marker.exists(), "O fluxo interativo perdeu seu mecanismo de login")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)


if __name__ == "__main__":
    unittest.main()
