"""Inicialização real em ambientes isolados, sem acessar Git/remotos ou perfis pessoais."""

from contextlib import ExitStack
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
import venv


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


    def test_unavailable_project_interpreter_reports_preparation_error(self):
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(launcher.subprocess, "run", side_effect=OSError("execução indisponível")), \
             patch.object(launcher.sys, "stderr", io.StringIO()) as output:
            code = launcher._run("update", ROOT / "isolated" / "update.py", ["--help"])
            self.assertEqual(code, 1)
            self.assertIn("Python da .venv", output.getvalue())
            self.assertIn("uv sync --locked", output.getvalue())


    def test_inconsistent_venv_stops_before_second_reexecution(self):
        with patch.object(Path, "is_file", return_value=True), \
             patch.dict(os.environ, {"AGENTSCLOUD_WRAPPER_CHILD": "1"}), \
             patch.object(launcher.subprocess, "run") as run, \
             patch.object(launcher.sys, "stderr", io.StringIO()) as output:
            code = launcher._run("upload", ROOT / "isolated" / "upload.py", [])
            self.assertEqual(code, 1)
            self.assertIn("repare o ambiente", output.getvalue())
            self.assertIn("uv sync --locked", output.getvalue())
            run.assert_not_called()


class LauncherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="agentscloud-launchers-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        cls.project = cls.base / "repo with spaces & (qa)!^%"
        cls.project.mkdir()
        cls.copy_launchers(cls.project)
        cls.package = cls.project / "src" / "agentscloud"
        cls.package.mkdir(parents=True)
        (cls.package / "__init__.py").write_text("", encoding="utf-8")
        (cls.package / "cli.py").write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            "def main(arguments, default_repo):\n"
            "    Path(os.environ['AGENTSCLOUD_TEST_RECORD']).write_text(json.dumps({\n"
            "        'arguments': arguments, 'repo': str(default_repo),\n"
            "        'prefix': sys.prefix}), encoding='utf-8')\n"
            "    print('CLI isolada executada')\n"
            "    return int(os.environ.get('AGENTSCLOUD_TEST_EXIT', '0'))\n",
            encoding="utf-8",
        )
        venv.EnvBuilder(with_pip=False).create(cls.project / ".venv")

    @staticmethod
    def copy_launchers(folder):
        for name in ("_launcher.py", "update.py", "upload.py", "update.cmd", "upload.cmd"):
            shutil.copy2(ROOT / name, folder / name)
        (folder / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts" / "_launcher_console.ps1",
                     folder / "scripts" / "_launcher_console.ps1")

    def setUp(self):
        self.record = self.base / f"{self._testMethodName}.json"
        self.env = dict(os.environ)
        for key in ("AGENTSCLOUD_NO_PAUSE", "AGENTSCLOUD_CMD_WRAPPER", "AGENTSCLOUD_WRAPPER_CHILD"):
            self.env.pop(key, None)
        self.env["AGENTSCLOUD_TEST_RECORD"] = str(self.record)
        self.env["AGENTSCLOUD_TEST_EXIT"] = "0"

    def run_python(self, wrapper, *arguments):
        return subprocess.run([sys.executable, str(wrapper), *arguments], env=self.env,
                              capture_output=True, text=True, timeout=20, check=False)

    def assert_record(self, command, arguments):
        record = json.loads(self.record.read_text(encoding="utf-8"))
        self.assertEqual(record["arguments"], [command, *arguments])
        self.assertEqual(Path(record["repo"]), self.project)
        self.assertEqual(Path(record["prefix"]), self.project / ".venv")

    def test_python_reexecutes_project_venv_and_preserves_arguments(self):
        arguments = ["--repo", "destino com espaço & (qa)!^%", "--literal", "$()"]
        for command in ("update", "upload"):
            with self.subTest(command=command):
                result = self.run_python(self.project / f"{command}.py", *arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_record(command, arguments)
                self.assertNotIn("Pressione", result.stdout)

    def test_python_preserves_child_failure(self):
        self.env["AGENTSCLOUD_TEST_EXIT"] = "7"
        result = self.run_python(self.project / "upload.py", "--help")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assert_record("upload", ["--help"])

    def test_missing_dependency_without_venv_has_actionable_error(self):
        folder = self.base / "sem ambiente"
        folder.mkdir()
        self.copy_launchers(folder)
        package = folder / "src" / "agentscloud"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "cli.py").write_text("import agentscloud_test_missing_dependency\n", encoding="utf-8")
        result = self.run_python(folder / "update.py", "--help")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uv sync --locked", result.stderr)
        self.assertIn("agentscloud_test_missing_dependency", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def run_cmd(self, folder, command, arguments=""):
        # Expande os valores uma vez no cmd, inclusive caminhos com %, !, ^ e &.
        self.env["AGENTSCLOUD_TEST_WRAPPER"] = str(folder / f"{command}.cmd")
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        line = f'"{comspec}" /d /v:off /s /c ""%AGENTSCLOUD_TEST_WRAPPER%" {arguments}"'
        return subprocess.run(line, env=self.env, capture_output=True, text=True,
                              timeout=25, check=False)

    @unittest.skipUnless(os.name == "nt", "Lançador .cmd exige Windows.")
    def test_cmd_preserves_metacharacters_and_child_exit_without_pause_in_pipe(self):
        destination = "destino & (teste)!^%"
        self.env["AGENTSCLOUD_TEST_DESTINATION"] = destination
        for command, code in (("update", 0), ("upload", 7)):
            with self.subTest(command=command, code=code):
                self.env["AGENTSCLOUD_TEST_EXIT"] = str(code)
                result = self.run_cmd(self.project, command, '--repo "%AGENTSCLOUD_TEST_DESTINATION%"')
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assert_record(command, ["--repo", destination])
                self.assertNotIn("Pressione", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Lançador .cmd exige Windows.")
    def test_cmd_without_venv_or_python_on_path_explains_setup(self):
        folder = self.base / "sem Python & (qa)"
        folder.mkdir()
        self.copy_launchers(folder)
        self.env["PATH"] = ""
        result = self.run_cmd(folder, "update", "--help")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Python da .venv", result.stdout)
        self.assertIn("uv sync --locked", result.stdout)
        self.assertNotIn("Pressione", result.stdout)

    def test_real_cli_help_and_parser_error_do_not_touch_git(self):
        for command in ("update", "upload"):
            for argument, code in (("--help", 0), ("--argumento-inexistente", 2)):
                with self.subTest(command=command, argument=argument):
                    result = self.run_python(ROOT / f"{command}.py", argument)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertIn("usage:", result.stdout + result.stderr)
                    self.assertNotIn("Pressione", result.stdout)


if __name__ == "__main__":
    unittest.main()

