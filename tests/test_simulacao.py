"""Aceitação do roteiro completo: verifica artefatos sem confiar só nos checks internos."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/simular_fluxo.py"


@unittest.skipUnless(shutil.which("git"), "Git é obrigatório para a aceitação do laboratório")
class SimulationAcceptanceTests(unittest.TestCase):
    def test_complete_lab_is_local_reproducible_and_leaves_runtime_agent_installed(self):
        with tempfile.TemporaryDirectory(prefix="agentscloud-acceptance-") as temp:
            root = Path(temp)
            destination = root / "laboratorio-novo"
            personal = root / "perfil-que-nao-pode-ser-tocado"
            personal.mkdir()
            sentinel = personal / "preservar.txt"
            sentinel.write_bytes(b"Perfil anterior preservado.")
            before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
            environment = dict(os.environ)
            environment.update({
                "CODEX_HOME": str(personal),
                # Se escaparem do isolamento, esses valores desviariam operações Git.
                "GIT_DIR": str(personal / "nao-criar.git"),
                "GIT_WORK_TREE": str(personal),
                "GIT_INDEX_FILE": str(personal / "nao-criar.index"),
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            })
            result = subprocess.run([sys.executable, str(SCRIPT), "--destino", str(destination)],
                                    capture_output=True, env=environment, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((destination / "resultado.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["interaction"], "simulated")
            self.assertFalse(report["codex_runtime_executed"])
            self.assertTrue(all(check["passed"] for check in report["checks"]))
            self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before)
            self.assertEqual([p.name for p in personal.iterdir()], ["preservar.txt"])

            # Leitura independente dos objetos/refs Git deixados pelo roteiro.
            def git(path, *args):
                return subprocess.check_output(["git", "-C", str(path), *args]).decode().strip()

            remote = destination / "remote.git"
            contributor = destination / "contribuidor"
            consumer = destination / "consumidor"
            latest = git(remote, "rev-parse", "main")
            self.assertEqual(git(contributor, "rev-parse", "HEAD"), latest)
            self.assertEqual(git(consumer, "rev-parse", "HEAD"), latest)
            self.assertEqual(git(remote, "rev-list", "--count", "main"), "3")
            for scenario, filename in (("upload_scan", "qa-resumo.toml"), ("upload_manual", "qa-revisor.toml")):
                commit = report["commits"][scenario]
                changes = set(git(remote, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines())
                self.assertEqual(changes, {f"Agents/{filename}", "catalog.toml", "README.md"})
            for clone in (contributor, consumer):
                self.assertEqual(Path(git(clone, "remote", "get-url", "equipe")).resolve(), remote.resolve())
                self.assertEqual(git(clone, "status", "--porcelain"), "")
            installed = destination / "profiles/consumidor/agents"
            self.assertEqual(len(list(installed.glob("*.toml"))), 5)
            self.assertEqual((installed / "documentador.toml").read_bytes(),
                             (ROOT / "Agents/documentador.toml").read_bytes())
            self.assertEqual((installed / "qa-resumo.toml").read_bytes(),
                             (ROOT / "tests/fixtures/agents/qa-resumo.toml").read_bytes())
            self.assertEqual((installed / "qa-revisor.toml").read_bytes(),
                             (ROOT / "tests/fixtures/agents/qa-revisor.toml").read_bytes()
                             + b"\n# Ajuste pessoal exclusivo deste laboratorio.\n")
            self.assertEqual(list(installed.glob("*.bak-*")), [])
            scenarios = {scenario["name"]: scenario for scenario in report["scenarios"]}
            self.assertEqual(scenarios["duplicidade_cancelada"]["exit_code"], 1)
            scan = next(event for event in scenarios["upload_scan"]["transcript"] if event["kind"] == "select")
            self.assertEqual({item["value"] for item in scan["choices"]}, {"qa-resumo.toml", "qa-revisor.toml"})
            self.assertEqual(scan["answer"], "qa-resumo.toml")
            self.assertIn("Perguntas e seleção foram simuladas", (destination / "resultado.md").read_text(encoding="utf-8"))

    def test_existing_destination_is_refused_without_changing_its_contents(self):
        with tempfile.TemporaryDirectory(prefix="agentscloud-existing-") as temp:
            destination = Path(temp) / "ja-existe"
            destination.mkdir()
            marker = destination / "resultado.json"
            marker.write_bytes(b"Relatorio de uma execucao anterior.")
            before = (marker.read_bytes(), marker.stat().st_mtime_ns)
            result = subprocess.run([sys.executable, str(SCRIPT), "--destino", str(destination)],
                                    capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual((marker.read_bytes(), marker.stat().st_mtime_ns), before)
            self.assertEqual([p.name for p in destination.iterdir()], ["resultado.json"])


if __name__ == "__main__":
    unittest.main()
