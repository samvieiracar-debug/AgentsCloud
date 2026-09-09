"""Atalhos da central em clones e ambientes temporários, sem Git nem perfil real."""

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
from unittest.mock import patch
import venv


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hub_launcher_test", ROOT / "hub.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)


class HubLauncherUnitTests(unittest.TestCase):
    def test_help_and_invalid_arguments_never_check_venv_or_start_process(self):
        for arguments, expected in ((["--help"], 0), (["--invalid"], 2)):
            with self.subTest(arguments=arguments), \
                 patch.object(launcher, "_owns_python_console", return_value=False), \
                 patch.object(launcher.Path, "is_file") as exists, \
                 patch.object(launcher.subprocess, "run") as run, \
                 patch.object(launcher.sys, "stdout", io.StringIO()), \
                 patch.object(launcher.sys, "stderr", io.StringIO()):
                self.assertEqual(launcher.launch(arguments), expected)
                exists.assert_not_called()
                run.assert_not_called()

    def test_missing_venv_explains_manual_preparation_and_independent_diagnostics(self):
        with patch.object(launcher.Path, "is_file", return_value=False), \
             patch.object(launcher.subprocess, "run") as run, \
             patch.object(launcher.sys, "stderr", io.StringIO()) as output:
            self.assertEqual(launcher._run(ROOT, []), 1)
            self.assertIn("uv sync --locked", output.getvalue())
            self.assertIn("diagnostico.cmd", output.getvalue())
            run.assert_not_called()

    def test_close_prompt_preserves_exit_code_and_cancellation(self):
        for result, expected in ((7, 7), (KeyboardInterrupt(), 130)):
            with self.subTest(result=result), \
                 patch.object(launcher, "_owns_python_console", return_value=True), \
                 patch.object(launcher, "_wait_for_close") as pause, \
                 patch.object(launcher, "_run") as run:
                if isinstance(result, Exception) or isinstance(result, KeyboardInterrupt):
                    run.side_effect = result
                else:
                    run.return_value = result
                self.assertEqual(launcher.launch([]), expected)
                pause.assert_called_once()


class HubLauncherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix="agentscloud-hub-venv-")
        cls.addClassCleanup(cls.shared.cleanup)
        cls.venv_template = Path(cls.shared.name).resolve() / "template"
        venv.EnvBuilder(with_pip=False).create(cls.venv_template)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agentscloud-hub-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "clone & (qa)!^% data"
        self.root.mkdir()
        for name in ("hub.py", "hub.cmd", "_hub_runtime.py", "_launcher.py"):
            shutil.copy2(ROOT / name, self.root / name)
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/_launcher_console.ps1", self.root / "scripts/_launcher_console.ps1")
        self.package = self.root / "src/agentscloud"
        self.package.mkdir(parents=True)
        shutil.copy2(ROOT / "src/agentscloud/arguments.py", self.package / "arguments.py")
        (self.package / "__init__.py").write_text("", encoding="utf-8")
        self.record = self.base / "record.json"
        self.environment = dict(os.environ)
        self.environment.update(AGENTSCLOUD_NO_PAUSE="1", HUB_PROBE=str(self.record),
                                VIRTUAL_ENV=str(self.base / "wrong-env"))

    def invoke(self, *arguments, cmd=False):
        environment = dict(self.environment)
        if cmd:
            environment["HUB_WRAPPER"] = str(self.root / "hub.cmd")
            words = []
            for index, argument in enumerate(arguments):
                name = f"HUB_ARG_{index}"
                environment[name] = str(argument)
                words.append(f'"%{name}%"')
            comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
            command = f'"{comspec}" /d /v:off /s /c ""%HUB_WRAPPER%" {" ".join(words)}"'
        else:
            command = [BASE_PYTHON, "-B", "-E", "-s", str(self.root / "hub.py"), *arguments]
        return subprocess.run(
            command, cwd=self.base, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )

    def prepare_venv(self):
        shutil.copytree(self.venv_template, self.root / ".venv", symlinks=True)

    def test_help_and_parser_errors_work_without_dependencies_or_package_import(self):
        (self.package / "__init__.py").write_text("raise AssertionError('package imported')", encoding="utf-8")
        before = {str(path.relative_to(self.root)) for path in self.root.rglob("*")}
        for arguments, expected in ((["--help"], 0), (["--invalid"], 2), (["--repo"], 2)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertNotIn("package imported", result.stderr)
                self.assertNotIn("uv sync", result.stdout + result.stderr)
        self.assertEqual(before, {str(path.relative_to(self.root)) for path in self.root.rglob("*")})

    @unittest.skipUnless(os.name == "nt", "Atalho .cmd exclusivo do Windows.")
    def test_windows_cmd_help_and_invalid_arguments_work_without_environment(self):
        for arguments, expected in ((["--help"], 0), (["--invalid"], 2)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments, cmd=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertNotIn("uv sync", result.stdout + result.stderr)
        self.assertFalse((self.root / ".venv").exists())

    def test_missing_environment_does_not_prepare_or_create_files(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("uv sync --locked", result.stderr)
        self.assertIn("diagnostico.cmd", result.stderr)
        self.assertFalse((self.root / ".venv").exists())

    def test_uses_own_runtime_while_repo_selects_data_and_preserves_exit_code(self):
        self.prepare_venv()
        (self.package / "hub.py").write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            "def run_hub(root):\n"
            "    Path(os.environ['HUB_PROBE']).write_text(json.dumps({\n"
            "        'root': str(root), 'prefix': sys.prefix,\n"
            "        'active': os.environ['VIRTUAL_ENV']}), encoding='utf-8')\n"
            "    return 7\n", encoding="utf-8")
        data = self.base / "outro clone"
        data.mkdir()
        for cmd in ([False, True] if os.name == "nt" else [False]):
            with self.subTest(cmd=cmd):
                result = self.invoke("--repo", data.name, cmd=cmd)
                self.assertEqual(result.returncode, 7, result.stderr)
                record = json.loads(self.record.read_text(encoding="utf-8"))
                self.assertEqual(Path(record["root"]), data)
                self.assertEqual(Path(record["prefix"]), self.root / ".venv")
                self.assertEqual(Path(record["active"]), self.root / ".venv")
                self.assertFalse((data / ".venv").exists())

    def test_missing_visual_dependency_is_actionable_without_runtime_fallback(self):
        self.prepare_venv()
        (self.package / "hub.py").write_text("import textual\n", encoding="utf-8")
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("textual", result.stderr)
        self.assertIn("uv sync --locked", result.stderr)
        self.assertIn("diagnostico.cmd", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.record.exists())

    def test_runtime_rejects_an_external_python_before_importing_hub(self):
        (self.package / "hub.py").write_text("raise AssertionError('hub imported')", encoding="utf-8")
        result = subprocess.run(
            [BASE_PYTHON, "-I", "-B", str(self.root / "_hub_runtime.py"), str(self.root)],
            env=self.environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(".venv", result.stderr)
        self.assertNotIn("hub imported", result.stderr)


if __name__ == "__main__":
    unittest.main()
