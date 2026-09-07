"""Inicialização real em ambientes isolados, sem acessar Git/remotos ou perfis pessoais."""

from contextlib import ExitStack
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agentscloud_launcher_test", ROOT / "_launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class ConsolePolicyTests(unittest.TestCase):
    def owns(self, names, tty=True, extra_env=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(launcher.os, "name", "nt"))
            stack.enter_context(patch.dict(os.environ, extra_env or {}, clear=True))
            stack.enter_context(patch.object(launcher.sys, "stdin", Mock(isatty=lambda: tty)))
            stack.enter_context(patch.object(launcher.sys, "stdout", Mock(isatty=lambda: tty)))
            stack.enter_context(patch.object(launcher, "_console_process_names", return_value=names))
            return launcher._owns_python_console()

    def test_python_launchers_own_console_but_existing_shell_does_not(self):
        self.assertTrue(self.owns(["python.exe", "python.exe"]))
        self.assertTrue(self.owns(["py.exe", "python.exe"]))
        self.assertFalse(self.owns(["powershell.exe", "python.exe"]))
        self.assertFalse(self.owns(["cmd.exe", "python.exe"]))
        self.assertFalse(self.owns([]))

    def test_redirection_child_and_explicit_opt_out_never_pause(self):
        self.assertFalse(self.owns(["python.exe"], tty=False))
        for key in ("AGENTSCLOUD_NO_PAUSE", "AGENTSCLOUD_CMD_WRAPPER", "AGENTSCLOUD_WRAPPER_CHILD"):
            with self.subTest(key=key):
                self.assertFalse(self.owns(["python.exe"], extra_env={key: "1"}))

    def test_pause_tracks_console_not_arguments_and_preserves_exit_code(self):
        for owns, arguments, code in ((True, [], 0), (True, ["--help"], 7),
                                      (False, [], 0), (False, ["--help"], 7)):
            with self.subTest(owns=owns, arguments=arguments, code=code):
                with patch.object(launcher, "_owns_python_console", return_value=owns), \
                     patch.object(launcher, "_run", return_value=code) as run, \
                     patch.object(launcher, "_wait_for_close") as pause:
                    self.assertEqual(launcher.launch("upload", ROOT / "upload.py", arguments), code)
                    run.assert_called_once_with("upload", ROOT / "upload.py", arguments)
                    self.assertEqual(pause.call_count, int(owns))

    def test_parser_failure_and_interruption_preserve_codes_and_close_prompt(self):
        for error, code in ((SystemExit(2), 2), (KeyboardInterrupt(), 130)):
            with self.subTest(error=error):
                with patch.object(launcher, "_owns_python_console", return_value=True), \
                     patch.object(launcher, "_run", side_effect=error), \
                     patch.object(launcher, "_wait_for_close") as pause:
                    self.assertEqual(launcher.launch("update", ROOT / "update.py", []), code)
                    pause.assert_called_once()

    def test_unexpected_failure_is_visible_before_pause(self):
        with patch.object(launcher, "_owns_python_console", return_value=True), \
             patch.object(launcher, "_run", side_effect=OSError("falha de leitura")), \
             patch.object(launcher, "_wait_for_close") as pause, \
             patch.object(launcher.sys, "stderr", io.StringIO()) as output:
            self.assertEqual(launcher.launch("update", ROOT / "update.py", []), 1)
            self.assertIn("falha de leitura", output.getvalue())
            pause.assert_called_once()



    def test_old_python_is_diagnosed_before_loading_parser_or_running_tools(self):
        with patch.object(launcher.sys, "version_info", (3, 9, 0)), \
             patch.object(launcher.runpy, "run_path") as parser, \
             patch.object(launcher.subprocess, "run") as run, \
             patch.object(launcher.sys, "stderr", io.StringIO()) as output:
            self.assertEqual(launcher._run("update", ROOT / "update.py", []), 1)
            self.assertIn("Python 3.11", output.getvalue())
            parser.assert_not_called()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
