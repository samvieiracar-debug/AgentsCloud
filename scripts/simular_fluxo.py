"""Demonstra os fluxos reais em um laboratório local com respostas roteirizadas."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentscloud.agents import read_agent
from agentscloud.catalog import Bundle, END, START, load_bundle, serialize_catalog, updated_readme
from agentscloud.cli import main as cli_main

SEED_FILES = ("documentador.toml", "planejador-testes.toml", "revisor-codigo.toml")
FIXTURE_FILES = ("qa-resumo.toml", "qa-revisor.toml")


class SimulationError(Exception):
    """Um requisito do laboratório não foi atendido."""


class ScriptedUI:
    """Substitui somente a interação, registrando escolhas simuladas explicitamente."""

    def __init__(self, responses: list[tuple[str, object, str]]):
        self.responses = list(responses)
        self.transcript: list[dict] = []

    def emit(self, message: str) -> None:
        self.transcript.append({"kind": "output", "text": message})

    def answer(self, kind: str, prompt: str):
        if not self.responses:
            raise SimulationError(f"Pergunta não prevista na simulação: {prompt}")
        expected_kind, answer, contains = self.responses.pop(0)
        if kind != expected_kind or contains not in prompt:
            raise SimulationError(f"Interação diferente da prevista: {kind}, {prompt}")
        self.transcript.append({"kind": kind, "prompt": prompt, "answer": answer, "simulated": True})
        return answer

    def confirm(self, message: str) -> bool:
        answer = self.answer("confirm", message)
        if not isinstance(answer, bool):
            raise SimulationError("A resposta simulada de confirmação deve ser bool.")
        return answer

    def text(self, message: str) -> str:
        answer = self.answer("text", message)
        if not isinstance(answer, str):
            raise SimulationError("A resposta simulada de texto deve ser uma string.")
        return answer

    def select(self, message: str, choices: list[tuple[str, str]]) -> str:
        selected = self.answer("select", message)
        self.transcript[-1]["choices"] = [{"label": label, "value": value} for label, value in choices]
        if selected not in {value for _, value in choices}:
            raise SimulationError(f"Agente simulado ausente da seleção: {selected}")
        return selected

    def finish(self) -> None:
        if self.responses:
            raise SimulationError("O fluxo terminou antes de consumir todas as respostas previstas.")


@contextmanager
def isolated_environment():
    """Evita redirecionamentos Git pessoais e restaura o ambiente ao terminar."""
    previous = dict(os.environ)
    try:
        for key in list(os.environ):
            if key.startswith("GIT_") or key == "CODEX_HOME":
                del os.environ[key]
        os.environ.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            # A própria CLI usa subprocess: as restrições também alcançam seu Git.
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "protocol.allow",
            "GIT_CONFIG_VALUE_0": "never",
            "GIT_CONFIG_KEY_1": "protocol.file.allow",
            "GIT_CONFIG_VALUE_1": "always",
        })
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def fingerprint(path: Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def working_files(root: Path) -> dict[str, dict]:
    return {
        path.relative_to(root).as_posix(): {"sha256": fingerprint(path)["sha256"], "bytes": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def installed_state(folder: Path) -> dict[str, dict]:
    if not folder.exists():
        return {}
    return {
        path.name: {**fingerprint(path), "mtime_ns": path.stat().st_mtime_ns}
        for path in sorted(folder.glob("*.toml"))
    }


def render_report(report: dict) -> str:
    lines = [
        "# Simulação de sincronização do AgentsCloud", "",
        f"Resultado: **{report['status']}**", "",
        "Perguntas e seleção foram simuladas pela API de interface. Git, arquivos, commits, "
        "pushes locais e instalação foram reais. Nenhuma sessão Codex foi executada por este roteiro.", "",
        "## Caminhos", "",
    ]
    for label, path in report["paths"].items():
        lines.append(f"- {label}: {path}")
    lines.extend(["", "## Checks", "", "| Check | Resultado | Evidência |", "| --- | --- | --- |"])
    for check in report["checks"]:
        details = json.dumps(check["details"], ensure_ascii=False).replace("|", "&#124;")
        lines.append(f"| {check['id']} | {'passou' if check['passed'] else 'falhou'} | {details} |")
    lines.extend(["", "## Comandos da CLI", "", "| Cenário | Comando | Código retornado |",
                  "| --- | --- | --- |"])
    for scenario in report["scenarios"]:
        lines.append(f"| {scenario['name']} | {scenario['command']} | {scenario['exit_code']} |")
    lines.extend(["", "O código 1 no cenário de duplicidade é o cancelamento esperado, "
                  "verificado antes de qualquer cópia ou commit.", "",
                  "## Arquivos instalados ao final", "",
                  "| Arquivo | Bytes | SHA256 | Igual ao clone consumidor |", "| --- | --- | --- | --- |"])
    for item in report.get("installed_files", []):
        lines.append(f"| {Path(item['path']).name} | {item['bytes']} | {item['sha256']} | "
                     f"{'sim' if item['matches_repository'] else 'não (conflito pessoal preservado)'} |")
    if report.get("error"):
        lines.extend(["", "## Erro", "", report["error"]])
    lines.extend(["", "O JSON contém os SHAs Git, fingerprints, comandos e transcrições das respostas "
                  "simuladas: [resultado.json](resultado.json).", ""])
    return "\n".join(lines)


def run_simulation(destination: Path, source: Path = ROOT) -> dict:
    """Cria um laboratório novo. Não apaga, reutiliza ou publica fora dele."""
    destination = destination.expanduser().absolute()
    source = source.resolve()
    if destination.exists() or destination.is_symlink():
        raise SimulationError(f"O destino já existe e não será reutilizado: {destination}")
    if not shutil.which("git"):
        raise SimulationError("Git é obrigatório para esta simulação.")
    available = load_bundle(source)
    by_file = {agent.file: agent for agent in available.agents}
    if not set(SEED_FILES).issubset(by_file):
        raise SimulationError("A pasta Agents/ deve conter os três agentes usados no seed.")
    seed = Bundle([by_file[name] for name in SEED_FILES],
                  {name: available.categories[name] for name in SEED_FILES},
                  {name: available.maintainers[name] for name in SEED_FILES if name in available.maintainers})
    fixtures = [read_agent(source / "tests/fixtures/agents" / name) for name in FIXTURE_FILES]
    destination.mkdir(parents=True, exist_ok=False)
    remote = destination / "remote.git"
    contributor = destination / "contribuidor"
    consumer = destination / "consumidor"
    producer_home = destination / "profiles/contribuidor"
    consumer_home = destination / "profiles/consumidor"
    report = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "interaction": "simulated",
        "git_and_filesystem": "real, local",
        "codex_runtime_executed": False,
        "paths": {
            "laboratorio": str(destination),
            "remoto_local": str(remote),
            "clone_contribuidor": str(contributor),
            "clone_consumidor": str(consumer),
            "codex_home_contribuidor": str(producer_home),
            "codex_home_consumidor": str(consumer_home),
        },
        "checks": [],
        "scenarios": [],
        "git_commands": [],
        "commits": {},
        "source_files": [],
    }
    sources = ([source / "catalog.toml", source / "scripts/simular_fluxo.py"]
               + [source / "Agents" / name for name in SEED_FILES]
               + [source / "tests/fixtures/agents" / name for name in FIXTURE_FILES]
               + sorted((source / "src/agentscloud").glob("*.py")))
    report["source_files"] = [fingerprint(path) for path in sources]

    def check(identifier: str, condition: bool, **details) -> None:
        report["checks"].append({"id": identifier, "passed": bool(condition), "details": details})
        if not condition:
            raise SimulationError(f"Check falhou: {identifier}")

    def git(cwd: Path, *args: str) -> bytes:
        if not cwd.resolve().is_relative_to(destination.resolve()):
            raise SimulationError(f"Comando Git fora do laboratório recusado: {cwd}")
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)
        report["git_commands"].append({"cwd": str(cwd), "args": list(args), "exit_code": result.returncode})
        if result.returncode:
            raise SimulationError(result.stderr.decode("utf-8", errors="replace").strip())
        return result.stdout

    def head(path: Path) -> str:
        return git(path, "rev-parse", "HEAD").decode().strip()

    def identity(path: Path) -> None:
        for key, value in (
            ("user.name", "AgentsCloud Laboratório"),
            ("user.email", "laboratorio@invalid.example"),
            ("core.autocrlf", "false"),
            ("commit.gpgsign", "false"),
        ):
            git(path, "config", key, value)

    def command(name: str, verb: str, checkout: Path, home: Path,
                responses: list[tuple[str, object, str]], expected: int = 0) -> ScriptedUI:
        if not checkout.is_relative_to(destination) or not home.is_relative_to(destination):
            raise SimulationError("Clone ou perfil fora do laboratório.")
        os.environ["CODEX_HOME"] = str(home)
        ui = ScriptedUI(responses)
        exit_code = cli_main([verb, "--repo", str(checkout)], ui=ui)
        report["scenarios"].append({
            "name": name, "command": verb, "checkout": str(checkout),
            "codex_home": str(home), "exit_code": exit_code, "expected_exit_code": expected,
            "transcript": ui.transcript,
        })
        check(f"{name}_exit_code", exit_code == expected, actual=exit_code, expected=expected)
        ui.finish()
        return ui

    def check_contribution(filename: str, previous: str) -> str:
        commit = head(contributor)
        changed = sorted(git(contributor, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).decode().splitlines())
        expected = sorted([f"Agents/{filename}", "catalog.toml", "README.md"])
        content = (producer_home / "agents" / filename).read_bytes()
        check(f"{filename}_commit_seletivo",
              changed == expected and git(contributor, "rev-parse", "HEAD^").decode().strip() == previous,
              commit=commit, changed_files=changed, parent=previous)
        check(f"{filename}_push_local", head(remote) == commit,
              contributor_head=commit, remote_head=head(remote))
        check(f"{filename}_bytes_preservados",
              (contributor / "Agents" / filename).read_bytes() == content
              and git(remote, "show", f"HEAD:Agents/{filename}") == content,
              **fingerprint(producer_home / "agents" / filename))
        return commit

    try:
        with isolated_environment():
            git(destination, "init", "--bare", "--initial-branch=main", str(remote))
            git(destination, "clone", "--origin", "equipe", str(remote), str(contributor))
            identity(contributor)
            (contributor / "Agents").mkdir()
            for agent in seed.agents:
                (contributor / "Agents" / agent.file).write_bytes(agent.content)
            (contributor / "catalog.toml").write_bytes(serialize_catalog(seed.categories, seed.maintainers))
            readme = f"# Equipe de laboratório\n\n{START}\n\n{END}\n".encode("utf-8")
            (contributor / "README.md").write_bytes(updated_readme(readme, seed))
            git(contributor, "add", "--", "Agents", "catalog.toml", "README.md")
            git(contributor, "commit", "-m", "Seed local com agentes distribuídos")
            git(contributor, "push", "-u", "equipe", "HEAD")
            git(destination, "clone", "--origin", "equipe", str(remote), str(consumer))
            identity(consumer)
            initial = head(consumer)
            report["commits"]["seed"] = initial
            check("seed_3_agentes_reais",
                  len(load_bundle(consumer).agents) == 3
                  and all((consumer / "Agents" / a.file).read_bytes() == a.content for a in seed.agents),
                  commit=initial, files=list(SEED_FILES))
            check("remotos_exclusivamente_locais",
                  all(Path(git(path, "remote", "get-url", "equipe").decode().strip()).resolve() == remote.resolve()
                      for path in (contributor, consumer)),
                  remote=str(remote))
            (producer_home / "agents").mkdir(parents=True)
            for agent in fixtures:
                (producer_home / "agents" / agent.file).write_bytes(agent.content)

            selected = command("upload_scan", "upload", contributor, producer_home, [
                ("confirm", True, "scan automático"),
                ("select", "qa-resumo.toml", "Escolha um agente"),
                ("text", "Laboratório", "Categoria"),
                ("text", "Teste simulado", "Responsável"),
                ("confirm", True, "criar o commit"),
            ])
            selection = next(event for event in selected.transcript if event["kind"] == "select")
            check("scan_oferece_duas_fixtures",
                  {choice["value"] for choice in selection["choices"]} == set(FIXTURE_FILES),
                  selected=selection["answer"], choices=selection["choices"])
            first = check_contribution("qa-resumo.toml", initial)
            report["commits"]["upload_scan"] = first

            command("upload_manual", "upload", contributor, producer_home, [
                ("confirm", False, "scan automático"),
                ("text", str(producer_home / "agents/qa-revisor.toml"), "Caminho"),
                ("text", "Laboratório", "Categoria"),
                ("text", "", "Responsável"),
                ("confirm", True, "criar o commit"),
            ])
            latest = check_contribution("qa-revisor.toml", first)
            report["commits"]["upload_manual"] = latest
            check("catalogo_preserva_responsaveis",
                  all(load_bundle(contributor).maintainers.get(name) == owner for name, owner in seed.maintainers.items())
                  and load_bundle(contributor).maintainers.get("qa-resumo.toml") == "Teste simulado"
                  and "qa-revisor.toml" not in load_bundle(contributor).maintainers,
                  maintainers=load_bundle(contributor).maintainers)

            before_refusal = working_files(consumer)
            command("update_recusado", "update", consumer, consumer_home, [
                ("confirm", False, "atualizar o repositório"),
            ])
            check("recusa_preserva_checkout_e_perfil",
                  head(consumer) == initial and working_files(consumer) == before_refusal
                  and not consumer_home.exists(),
                  head=head(consumer), codex_home_exists=consumer_home.exists())

            command("update_e_instalacao", "update", consumer, consumer_home, [
                ("confirm", True, "atualizar o repositório"),
                ("confirm", True, "Deseja instalar"),
            ])
            installed = consumer_home / "agents"
            expected_agents = load_bundle(consumer).agents
            check("sincronismo_dos_dois_clones", head(consumer) == head(contributor) == head(remote),
                  contributor_head=head(contributor), consumer_head=head(consumer), remote_head=head(remote))
            check("instalacao_exata_5_agentes",
                  len(list(installed.glob("*.toml"))) == 5
                  and all((installed / a.file).read_bytes() == a.content for a in expected_agents),
                  files=installed_state(installed))
            stable = installed_state(installed)
            command("update_idempotente", "update", consumer, consumer_home, [
                ("confirm", True, "Deseja instalar"),
            ])
            check("idempotencia_bytes_e_mtime", installed_state(installed) == stable,
                  files=installed_state(installed))

            before_duplicate = working_files(contributor)
            duplicate = command("duplicidade_cancelada", "upload", contributor, producer_home, [
                ("confirm", False, "scan automático"),
                ("text", str(producer_home / "agents/qa-resumo.toml"), "Caminho"),
            ], expected=1)
            check("duplicidade_sem_copia_commit_ou_push",
                  head(contributor) == latest and head(remote) == latest
                  and working_files(contributor) == before_duplicate
                  and any("Esse nome está indisponível" in event.get("text", "") for event in duplicate.transcript),
                  head=head(contributor), remote_head=head(remote))

            personal = installed / "qa-revisor.toml"
            personal.write_bytes(personal.read_bytes() + b"\n# Ajuste pessoal exclusivo deste laboratorio.\n")
            personal_before = installed_state(installed)
            command("conflito_preservado", "update", consumer, consumer_home, [
                ("confirm", True, "Deseja instalar"),
                ("confirm", False, "Conflito"),
            ])
            check("recusa_preserva_conflito_pessoal",
                  installed_state(installed) == personal_before and not list(installed.glob("*.bak-*")),
                  conflict=fingerprint(personal), backups=[])
            check("documentador_pronto_para_runtime",
                  (installed / "documentador.toml").read_bytes() == by_file["documentador.toml"].content,
                  **fingerprint(installed / "documentador.toml"))
            check("clones_limpos_ao_final",
                  not git(contributor, "status", "--porcelain") and not git(consumer, "status", "--porcelain"),
                  contributor_head=head(contributor), consumer_head=head(consumer))
            report["installed_files"] = [
                {**fingerprint(path), "matches_repository": path.read_bytes() == (consumer / "Agents" / path.name).read_bytes()}
                for path in sorted(installed.glob("*.toml"))
            ]
            report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (destination / "resultado.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8", newline="\n")
        (destination / "resultado.md").write_text(render_report(report), encoding="utf-8", newline="\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simula respostas da CLI com Git real em um laboratório local novo.")
    parser.add_argument("--destino", type=Path, required=True, help="Diretório novo; alvos existentes são recusados.")
    args = parser.parse_args(argv)
    try:
        report = run_simulation(args.destino)
    except (SimulationError, OSError) as exc:
        print(f"Erro: {exc}")
        return 1
    print(f"Resultado: {report['status']}. Checks: {sum(item['passed'] for item in report['checks'])}/{len(report['checks'])}")
    print(f"Relatório: {Path(report['paths']['laboratorio']) / 'resultado.md'}")
    print(f"Perfil consumidor: {report['paths']['codex_home_consumidor']}")
    if report.get("error"):
        print(report["error"])
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
