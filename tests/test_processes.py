"""Timeouts e logs sem rede/credenciais reais."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agentscloud.processes import (EventLog, CommandResult, INTERACTIVE_NETWORK_TIMEOUT,
                                  NETWORK_TIMEOUT, classify, run_command, sanitize)


class ProcessTests(unittest.TestCase):
    def test_git_login_gets_longer_timeout_than_noninteractive_probe(self):
        import _launcher
        from agentscloud import processes
        from agentscloud.git import Repository, PushTarget
        repo = object.__new__(Repository)
        repo.path, repo.log = Path.cwd(), None
        with patch("agentscloud.git.run_command", return_value=CommandResult(0)) as runner:
            repo.run("fetch", "--", "team", "refs/heads/main")
            self.assertTrue(runner.call_args.kwargs["interactive"])
            self.assertEqual(runner.call_args.kwargs["timeout"], 180)
            repo.run("ls-remote", "--", "team", interactive=False)
            self.assertFalse(runner.call_args.kwargs["interactive"])
            self.assertEqual(runner.call_args.kwargs["timeout"], 30)
            repo.push(PushTarget("team", "refs/heads/main", "example.invalid"), "a" * 40)
            self.assertEqual(runner.call_args.kwargs["operation"], "git-push")
            self.assertEqual(runner.call_args.kwargs["timeout"], 180)
        with patch.object(_launcher, "_PROCESS", vars(processes)), patch.object(
                _launcher, "_LOG", None), patch.object(
                processes, "run_command", return_value=CommandResult(0)) as runner:
            _launcher._git(Path.cwd(), "pull", "--ff-only")
            self.assertTrue(runner.call_args.kwargs["interactive"])
            self.assertEqual(runner.call_args.kwargs["timeout"], INTERACTIVE_NETWORK_TIMEOUT)
        self.assertGreater(INTERACTIVE_NETWORK_TIMEOUT, NETWORK_TIMEOUT)

    def test_error_categories_do_not_treat_403_as_connection_or_token_proof(self):
        self.assertEqual(classify(128, "fatal: unable to access https://example.invalid: requested URL returned error: 403"), "permissao_ou_politica")
        self.assertEqual(classify(128, "fatal: Authentication failed"), "autenticacao")
        self.assertEqual(classify(128, "Could not resolve host"), "conexao")
        self.assertEqual(classify(128, "pre-receive hook declined"), "permissao_ou_politica")
        self.assertEqual(classify(128, "non-fast-forward"), "divergencia")
        self.assertEqual(classify(128, "unknown error"), "indeterminado")
        self.assertEqual(classify(0, ""), "ok")

    def test_sensitive_values_never_appear_in_message_or_events(self):
        with tempfile.TemporaryDirectory(prefix="agentscloud-process-") as temp:
            log = EventLog(Path(temp) / "logs")
            secret = "SENTINEL_PASSWORD_123"
            content = f"https://alice:{secret}@example.invalid/repo?token={secret}\nAuthorization: Bearer {secret}\npassword='{secret}'"
            command = [sys.executable, "-c", "import sys; sys.stderr.write(" + repr(content) + "); sys.exit(7)"]
            result = run_command(command, log=log, operation="test")
            self.assertNotIn(secret, result.message)
            self.assertIn("example.invalid/repo", result.message)
            events = log.path.read_text()
            self.assertNotIn(secret, events)
            self.assertNotIn("example.invalid", events)
            self.assertNotIn("stderr", events)
            self.assertEqual(result.returncode, 7)
            self.assertTrue(log.recent())

    def test_interactive_output_is_visible_before_exit_and_sanitized(self):
        with tempfile.TemporaryDirectory(prefix="agentscloud-live-") as temp:
            release = Path(temp) / "release"
            shown = threading.Event()
            class Observe(io.StringIO):
                def write(self, value):
                    result = super().write(value)
                    if "Enter code:" in self.getvalue():
                        shown.set()
                    return result
            output = Observe()
            code = ("import pathlib,time,sys\n"
                    "sys.stdout.write('Enter code: '); sys.stdout.flush()\n"
                    f"while not pathlib.Path({str(release)!r}).exists(): time.sleep(.02)\n"
                    "print('Authorization: Bearer LIVE_SECRET')\n")
            result = []
            with patch("sys.stdout", output):
                worker = threading.Thread(target=lambda: result.append(run_command(
                    [sys.executable, "-c", code], interactive=True, timeout=5)))
                worker.start()
                try:
                    self.assertTrue(shown.wait(3), "Prompt ficou oculto até o fim do processo")
                finally:
                    release.touch()
                    worker.join(6)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0].returncode, 0)
            self.assertNotIn("LIVE_SECRET", output.getvalue())

    def test_timeout_ends_own_child_tree_and_preserves_unrelated_process(self):
        with tempfile.TemporaryDirectory(prefix="agentscloud-timeout-") as temp:
            root = Path(temp)
            child_marker, other_marker = root / "child", root / "other"
            child_code = f"import time,pathlib;time.sleep(1.3);pathlib.Path({str(child_marker)!r}).touch();time.sleep(20)"
            other = subprocess.Popen([sys.executable, "-c", f"import time,pathlib;time.sleep(1.5);pathlib.Path({str(other_marker)!r}).touch()"])
            try:
                code = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child_code!r}]);time.sleep(20)"
                result = run_command([sys.executable, "-c", code], timeout=.5)
                self.assertEqual(result.returncode, 124)
                self.assertTrue(result.timed_out)
                other.wait(timeout=5)
                self.assertTrue(other_marker.exists())
                self.assertFalse(child_marker.exists())
            finally:
                if other.poll() is None:
                    other.kill()
                    other.wait()

    def test_explicit_input_is_exact_and_timeout_does_not_depend_on_child_reading(self):
        data = b"approved\0content\r\n" * 65536
        result = run_command([sys.executable, "-c", "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                             input_bytes=data, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, data)
        started = time.monotonic()
        result = run_command([sys.executable, "-c", "import time;time.sleep(20)"],
                             input_bytes=data, timeout=.3)
        self.assertTrue(result.timed_out)
        self.assertLess(time.monotonic() - started, 5)

    def test_rotation_and_unwritable_log_do_not_expose_process_output(self):
        with tempfile.TemporaryDirectory(prefix="agentscloud-log-") as temp:
            root = Path(temp)
            log = EventLog(root / "log")
            log.directory.mkdir()
            log.path.write_bytes(b"x" * (128 * 1024))
            self.assertTrue(log.write("run", outcome="ok"))
            self.assertTrue((log.directory / "events.previous.jsonl").exists())
            bad = root / "file"
            bad.write_bytes(b"keep")
            with patch("sys.stderr", io.StringIO()) as err:
                logger = EventLog(bad)
                self.assertFalse(logger.write("run"))
                self.assertFalse(logger.write("run"))
                self.assertEqual(err.getvalue().count("Aviso:"), 1)
            self.assertEqual(bad.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
