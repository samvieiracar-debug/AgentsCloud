"""Diagnóstico stdlib, consultas limitadas e reparos individualmente consentidos."""

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

from .processes import (
    EventLog, LOCAL_TIMEOUT, NETWORK_TIMEOUT, SYNC_TIMEOUT,
    project_environment, run_command, sanitize,
)


@dataclass
class Check:
    name: str
    status: str
    detail: str


class Diagnostics:
    def __init__(self, root, *, offline=False, runner=None, lookup=None, progress=None):
        self.root = Path(root).expanduser().resolve()
        self.offline = offline
        self.runner = runner or run_command
        self.lookup = lookup or shutil.which
        self.checks = []
        self.tools = {}
        self.git_root = False
        self.git_dir = None
        self.git_config_path = None
        self.branch = None
        self.log = None
        self.manifests = {}
        self.events = []
        self.progress = progress

    def add(self, name, status, detail):
        check = Check(name, status, sanitize(detail))
        self.checks.append(check)
        return check

    def command(self, argv, *, timeout=LOCAL_TIMEOUT, env=None, repair=False, operation="diagnostico"):
        if self.progress:
            tool = Path(str(argv[0])).stem.casefold()
            label = "Git: " + str(argv[3]) if tool == "git" and len(argv) > 3 and argv[1] == "-C" else tool
            self.progress(sanitize(f"Verificando {label}... (limite: {timeout}s)"))
        return self.runner(argv, cwd=self.root, timeout=timeout, env=env,
                           interactive=repair, operation=operation, log=self.log if repair else None)

    def git(self, *args, **kwargs):
        return self.command([self.tools.get("git") or "git", "-C", str(self.root), *args], **kwargs)

    @staticmethod
    def text(result):
        return result.stdout.decode("utf-8", errors="replace").strip()

    def failure(self, name, result, advice=""):
        return self.add(name, "falhou", f"{result.category}: {result.message}. {advice}")

    def collect(self):
        self.checks = []
        self.events = []
        self.add("Python", "ok" if sys.version_info >= (3, 11) else "falhou",
                 f"{sys.version.split()[0]} — {sys.executable}; requisito: Python 3.11+.")
        for tool in ("git", "uv"):
            self.tools[tool] = self.lookup(tool)
            if not self.tools[tool]:
                self.add(tool, "falhou", f"{tool} não encontrado no PATH. Instale a ferramenta e reabra o terminal.")
                continue
            result = self.command([self.tools[tool], "--version"])
            if result.returncode:
                self.failure(tool, result)
            else:
                self.add(tool, "ok", f"{self.text(result)} — {self.tools[tool]}")
        self.environment()
        if self.tools.get("git"):
            self.repository()
        else:
            self.add("Git/configuração", "pulado", "Consultas Git dependem da instalação do Git.")
            self.add("Logs", "pulado", "Caminho de logs depende de git rev-parse --git-path agentscloud/logs.")
        return self.checks

    def environment(self):
        documents = {}
        self.manifests = {}
        for filename in ("pyproject.toml", "uv.lock"):
            try:
                data = (self.root / filename).read_bytes()
                document = tomllib.loads(data.decode("utf-8"))
                if filename == "pyproject.toml" and not isinstance(document.get("project"), dict):
                    raise ValueError("Tabela [project] ausente")
                if filename == "uv.lock" and (not isinstance(document.get("version"), int)
                                               or not isinstance(document.get("package"), list)):
                    raise ValueError("Lock sem version/package")
                documents[filename] = document
                self.manifests[filename] = hashlib.sha256(data).hexdigest()
                self.add(filename, "ok", "TOML legível; a consistência do lock tem uma verificação própria.")
            except (OSError, ValueError, UnicodeError) as exc:
                self.add(filename, "falhou", f"Não foi possível ler o manifesto: {exc}. Restaure o arquivo válido.")
        safe_venv = self.venv_is_local()
        interpreter = self.root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not safe_venv:
            self.add(".venv/dependências", "falhou", "A .venv do alvo é um link/junção. Use um ambiente local ao clone; nenhuma sondagem ou reparo uv é permitido.")
        elif not interpreter.is_file():
            self.add(".venv/dependências", "falhou", "Python da .venv ausente. O reparo disponível é uv sync --locked no alvo.")
        else:
            packages = {}
            for item in documents.get("uv.lock", {}).get("package", []):
                if isinstance(item, dict) and isinstance(item.get("source"), dict) and "registry" in item["source"]:
                    if isinstance(item.get("name"), str) and isinstance(item.get("version"), str):
                        packages.setdefault(item["name"], []).append(item["version"])
            script = (
                "import importlib.metadata as m, json, sys; import questionary; "
                "names=json.loads(sys.argv[1]); "
                "print(json.dumps({'prefix':sys.prefix,'python':list(sys.version_info[:3]),"
                "'versions':{name:m.version(name) for name in names}}))"
            )
            result = self.command([str(interpreter), "-I", "-B", "-c", script, json.dumps(packages)])
            if result.returncode:
                self.failure(".venv/dependências", result, "Repare com uv sync --locked; não instale Questionary globalmente.")
            else:
                try:
                    info = json.loads(self.text(result))
                    mismatches = [name for name, versions in packages.items() if info["versions"].get(name) not in versions]
                    valid = (Path(info["prefix"]).resolve() == (self.root / ".venv").resolve()
                             and tuple(info["python"]) >= (3, 11) and not mismatches)
                    self.add(".venv/dependências", "ok" if valid else "falhou",
                             "Questionary importável; Python, prefixo e versões conferidos com o lock." if valid else
                             "Python/prefixo ou versões instaladas diferem do alvo/lock. Repare com uv sync --locked.")
                except (ValueError, KeyError, TypeError):
                    self.add(".venv/dependências", "inconclusivo", "Python da .venv retornou uma resposta inesperada.")
        if self.tools.get("uv") and len(documents) == 2 and safe_venv:
            # Sondagem sem rede/downloads/alteração da venv ou lock; cache descartável.
            with tempfile.TemporaryDirectory(prefix="agentscloud-diagnostic-cache-") as cache:
                env = project_environment(self.root)
                env["UV_PYTHON_DOWNLOADS"] = "never"
                result = self.command(
                    [self.tools["uv"], "sync", "--locked", "--dry-run", "--offline", "--no-python-downloads",
                     "--cache-dir", cache, "--project", str(self.root), "--directory", str(self.root)],
                    timeout=30, env=env,
                )
            if result.returncode == 0:
                self.add("Consistência do lock", "ok", "uv sync --locked --dry-run --offline passou; a sondagem não instala pacotes.")
            else:
                text = result.message.casefold()
                lock_error = any(term in text for term in ("lockfile needs to be updated", "lockfile is not up-to-date",
                                                           "lockfile is not up to date", "lockfile cannot be updated"))
                self.add("Consistência do lock", "falhou" if lock_error else "inconclusivo",
                         f"{result.category}: {result.message}. Cache temporário vazio/indisponibilidade offline pode impedir a prova; "
                         "isso sozinho não comprova lock inválido.")
        else:
            self.add("Consistência do lock", "pulado", "Requer uv, os dois manifestos legíveis e .venv sem link/junção.")

    def repository(self):
        result = self.git("rev-parse", "--show-toplevel")
        self.git_root = result.returncode == 0 and Path(self.text(result)).resolve() == self.root
        if not self.git_root:
            self.add("Raiz Git", "falhou", "--repo deve indicar a raiz do clone Git. " + result.message)
            self.add("Logs", "pulado", "Clone Git não identificado; nenhum diretório pessoal foi pesquisado.")
            return
        result = self.git("rev-parse", "--absolute-git-dir")
        if result.returncode:
            self.git_root = False
            self.failure("Raiz Git", result, "Não foi possível fixar o diretório Git efetivo.")
            return
        self.git_dir = Path(self.text(result)).resolve()
        result = self.git("rev-parse", "--git-path", "config")
        if result.returncode:
            self.git_root = False
            self.failure("Raiz Git", result, "Não foi possível fixar a configuração local efetiva.")
            return
        self.git_config_path = (self.root / self.text(result)).resolve()
        self.add("Raiz Git", "ok", str(self.root))
        result = self.git("rev-parse", "--verify", "HEAD^{commit}")
        if result.returncode:
            self.failure("HEAD", result, "O repositório precisa de um commit inicial.")
        else:
            self.add("HEAD", "ok", self.text(result))
        result = self.git("symbolic-ref", "--quiet", "--short", "HEAD")
        self.branch = self.text(result) if result.returncode == 0 else None
        self.add("Branch", "ok" if self.branch else "falhou", self.branch or "HEAD destacado; selecione a branch correta manualmente.")
        result = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if result.returncode:
            self.failure("Checkout/índice", result)
        else:
            self.add("Checkout/índice", "falhou" if result.stdout else "ok",
                     "Há alterações locais ou arquivos não rastreados. Preserve/revise-os antes de update/upload." if result.stdout else "Limpos.")
        interrupted = []
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"):
            result = self.git("rev-parse", "--git-path", marker)
            if result.returncode:
                self.failure("Operação Git", result)
                break
            path = Path(self.text(result))
            if not path.is_absolute():
                path = self.root / path
            if path.exists():
                interrupted.append(marker)
        else:
            self.add("Operação Git", "falhou" if interrupted else "ok",
                     "Operação em andamento: " + ", ".join(interrupted) + ". Resolva-a manualmente." if interrupted else "Nenhuma operação interrompida detectada.")
        for key in ("user.name", "user.email"):
            result = self.git("config", "--get", key)
            present = result.returncode == 0 and bool(self.text(result))
            if result.returncode not in (0, 1):
                self.failure(key, result)
            else:
                self.add(key, "ok" if present else "falhou", "Identidade de commit configurada; não é login." if present else
                         "Identidade de commit ausente. Informe seu valor no reparo local; não é login.")
        # Consulta apenas nomes de chaves, nunca lê/imprime o conteúdo do helper.
        result = self.git("config", "--name-only", "--get-regexp", r"^credential(\..*)?\.helper$")
        if result.returncode not in (0, 1):
            self.failure("Credenciais", result)
        else:
            self.add("Credenciais", "ok", "Helper configurado (conteúdo omitido); autenticidade/permissão não verificadas." if result.stdout else
                     "Nenhum helper detectado. SSH ou outro mecanismo pode ser usado; isso não prova falha de login.")
        self.upstream()
        result = self.git("rev-parse", "--git-path", "agentscloud/logs")
        if result.returncode:
            self.failure("Logs", result)
        else:
            path = Path(self.text(result))
            self.log = EventLog(path if path.is_absolute() else self.root / path)
            self.events = [event for event in self.log.recent(50) if self.relevant_event(event)][-10:]
            details = "\n".join(self.describe_event(event) for event in self.events)
            self.add("Logs", "ok", details or
                     "Nenhum evento recente relevante e legível disponível. A causa de falhas antigas não pode ser determinada sem evidência.")

    @staticmethod
    def relevant_event(event):
        operation = event.get("operation", "")
        category = event.get("category", "")
        # Operações normais de consulta não ocultam eventos de preparo/publicação.
        return (operation.startswith(("upload", "push", "bootstrap-sync", "diagnostico."))
                or operation in ("git-push", "bootstrap-git-pull")
                or category not in ("", "ok", "expected", "esperado"))

    @staticmethod
    def describe_event(event):
        category = event.get("category", "")
        advice = {
            "autenticacao": "Confira o login no mecanismo Git usado; user.name/email não fazem login.",
            "conexao": "Confira a conexão/endereço e a evidência da próxima tentativa.",
            "timeout": "O limite de tempo terminou. Confira conexão/processos; após push, consulte o remoto antes de repetir.",
            "permissao_ou_politica": "Confira acesso de escrita e política da branch com o responsável pelo remoto.",
            "divergencia": "Revise o histórico; nenhuma reconciliação automática deve descartar commits.",
            "ferramenta_ausente": "Disponibilize a ferramenta no PATH e execute o diagnóstico novamente.",
            "indeterminado": "Não há evidência suficiente para atribuir uma causa exata.",
            "cancelado": "A operação foi interrompida; confira o estado antes de repeti-la.",
        }.get(category, "")
        outcome = event.get("outcome", category or "registrado")
        if outcome in ("incerto", "interrompido_incerto", "pendente"):
            advice = "Commit preservado; execute upload para consultar o destino e revisar uma eventual retomada."
        fields = [f"{event.get('time', 'horário indisponível')} — {event.get('operation', 'operação')}: {outcome}"]
        for key, label in (("returncode", "retorno"), ("commit", "commit"), ("ref", "ref")):
            if key in event:
                fields.append(f"{label} {event[key]}")
        return sanitize("; ".join(fields) + (". " + advice if advice else ""), 800)

    def venv_is_local(self):
        target = self.root / ".venv"
        try:
            return target.resolve() == target
        except (OSError, RuntimeError):
            return False

    def upstream(self):
        if not self.branch:
            self.add("Upstream", "pulado", "Requer branch ativa.")
            return
        result = self.git("for-each-ref", "--format=%(upstream:short)%00%(upstream:remotename)%00%(upstream:remoteref)",
                          "refs/heads/" + self.branch)
        fields = self.text(result).split("\x00")
        if result.returncode or len(fields) != 3 or not all(fields):
            self.add("Upstream", "falhou", "Branch sem upstream válido. Escolha um rastreamento existente no reparo local.")
            self.add("Leitura remota", "pulado", "Destino não identificado; nenhuma conexão foi tentada.")
            return
        tracking, remote, ref = fields
        self.add("Upstream", "ok", f"{tracking}; remoto {remote}; ref {ref}.")
        result = self.git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if result.returncode:
            self.failure("Ahead/behind em cache", result)
        else:
            self.relation("Ahead/behind em cache", self.text(result), "Refs locais em cache; não comprova o estado atual do servidor.")
        # Mesmo contrato de Repository.push_target: pushRemote prevalece sobre
        # pushDefault; uma override distinta bloqueia a publicação e a sondagem.
        override = None
        for key in (f"branch.{self.branch}.pushRemote", "remote.pushDefault"):
            result = self.git("config", "--get", key)
            if result.returncode not in (0, 1):
                self.failure("Destino de push", result, "Não foi possível validar pushRemote/pushDefault; nenhuma conexão foi tentada.")
                self.add("Leitura remota", "pulado", "Destino de publicação não validado.")
                return
            override = self.text(result) if result.returncode == 0 else None
            if override:
                break
        if override and override != remote:
            self.add("Destino de push", "falhou", "Destino de push difere do upstream (pushRemote/pushDefault). "
                     "Escolha uma configuração coerente antes de publicar; nenhum destino foi sondado.")
            self.add("Leitura remota", "pulado", "Configuração de destino incoerente com a publicação.")
            return
        result = self.git("remote", "get-url", "--push", "--all", "--", remote)
        destinations = self.text(result).splitlines()
        if result.returncode or len(destinations) != 1 or not ref.startswith("refs/heads/"):
            self.add("Destino de push", "falhou", "Destino não verificável ou múltiplo. Revise a configuração; nenhuma publicação será testada.")
            return
        destination = destinations[0]
        self.add("Destino de push", "ok", f"{destination} → {ref}. Nenhum push é usado como teste.")
        if self.offline:
            self.add("Leitura remota", "pulado", "Modo offline: nenhuma consulta de rede.")
            return
        result = self.git("ls-remote", "--exit-code", "--", destination, ref, timeout=NETWORK_TIMEOUT)
        if result.returncode == 2:
            self.add("Leitura remota", "falhou", "Destino respondeu, mas a ref exata não existe. Confirme remoto e branch.")
        elif result.returncode:
            self.failure("Leitura remota", result, "Revise rede, autenticação e política conforme a evidência; "
                         "este diagnóstico não abre login nem altera credenciais.")
        else:
            lines = [line.split() for line in self.text(result).splitlines()]
            tips = [line[0] for line in lines if len(line) == 2 and line[1] == ref]
            if len(tips) != 1:
                self.add("Leitura remota", "inconclusivo", "Resposta não identificou uma ref exata única.")
                return
            tip = tips[0]
            self.add("Leitura remota", "ok", f"Ref consultada: {tip}. Leitura pública não comprova autenticação ou permissão de push.")
            result = self.git("rev-list", "--left-right", "--count", "HEAD..." + tip)
            if result.returncode:
                self.add("Relação remota atual", "inconclusivo", "O objeto remoto pode não existir localmente; consulta sem fetch não resolve essa relação.")
            else:
                self.relation("Relação remota atual", self.text(result), "Estado consultado agora, sujeito a mudanças posteriores.")

    def relation(self, name, counts, note):
        try:
            ahead, behind = map(int, counts.split())
            if ahead < 0 or behind < 0:
                raise ValueError
        except ValueError:
            self.add(name, "inconclusivo", "Contagem Git inesperada.")
            return
        message = f"Adiantado: {ahead}; atrasado: {behind}. "
        if ahead and behind:
            status, message = "falhou", message + "Histórico divergente; reconciliação manual necessária. "
        elif ahead:
            status, message = "ok", message + "Upload pode revisar e oferecer os commits pendentes com confirmação. "
        elif behind:
            status, message = "ok", message + "Execute update para preparação segura. "
        else:
            status = "ok"
        self.add(name, status, message + note)

    def _confirm(self, description, input_fn, emit):
        emit(sanitize(description))
        answer = input_fn("Autoriza somente esta ação? [s/N] ").strip().casefold()
        return answer in ("s", "sim")

    def _unchanged_root(self):
        result = self.git("rev-parse", "--show-toplevel")
        if result.returncode or Path(self.text(result)).resolve() != self.root:
            return False
        result = self.git("rev-parse", "--absolute-git-dir")
        if result.returncode or self.git_dir is None or Path(self.text(result)).resolve() != self.git_dir:
            return False
        result = self.git("rev-parse", "--git-path", "config")
        if result.returncode or (self.root / self.text(result)).resolve() != self.git_config_path:
            return False
        if self.branch:
            result = self.git("symbolic-ref", "--quiet", "--short", "HEAD")
            return result.returncode == 0 and self.text(result) == self.branch
        return True

    def _repair_result(self, result, emit):
        if result.returncode:
            emit(f"Reparo falhou ({result.category}): {result.message}")
            return False
        emit("Comando de reparo concluído; conferindo a condição novamente.")
        return True

    def repairs(self, *, input_fn=input, emit=print):
        """Ofertas independentes; EOF/Ctrl+C interrompem sem autorizar a próxima ação."""
        changed = False
        for tool, package in (("git", "Git.Git"), ("uv", "astral-sh.uv")):
            if self.tools.get(tool):
                continue
            manager = self.lookup("winget") if os.name == "nt" else None
            emit(f"Instale {tool} e disponibilize-o no PATH. Consulte docs/diagnostico.md.")
            if not manager or self.offline:
                continue
            argv = [manager, "install", "--id", package, "--exact", "--source", "winget", "--disable-interactivity"]
            if self._confirm("Instalar ferramenta no computador usando: " + subprocess.list2cmdline(argv)
                             + ". Pode exigir permissões/termos do gerenciador; nada será aceito implicitamente.", input_fn, emit):
                result = self.command(argv, timeout=SYNC_TIMEOUT, repair=True, operation="diagnostico.install." + tool)
                changed = self._repair_result(result, emit) or changed
                self.tools[tool] = self.lookup(tool)
                if not self.tools[tool]:
                    emit(f"{tool} ainda não está disponível neste processo. Reabra o terminal e execute o diagnóstico novamente.")
        failed_env = any(c.name in (".venv/dependências", "Consistência do lock") and c.status in ("falhou", "inconclusivo") for c in self.checks)
        if self.tools.get("uv") and len(self.manifests) == 2 and failed_env and self.venv_is_local():
            argv = [self.tools["uv"], "sync", "--locked", "--project", str(self.root), "--directory", str(self.root)]
            if self.offline:
                argv.append("--offline")
            if self._confirm("Preparar somente a .venv do alvo (pode instalar/remover dependências e baixar Python): "
                             + subprocess.list2cmdline(argv), input_fn, emit):
                try:
                    current = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in self.manifests}
                except OSError:
                    current = {}
                if not self.venv_is_local():
                    emit("A .venv virou um link/junção durante a confirmação. Nenhum sync foi executado.")
                elif current != self.manifests:
                    emit("Manifesto/lock mudou durante a confirmação. Reexecute o diagnóstico antes do reparo.")
                elif Path(sys.prefix).resolve() == (self.root / ".venv").resolve():
                    emit("Este Python usa a .venv alvo. Feche-o e repita pelo diagnostico.cmd ou por um Python externo.")
                else:
                    result = self.command(argv, timeout=SYNC_TIMEOUT, env=project_environment(self.root),
                                          repair=True, operation="diagnostico.sync")
                    changed = self._repair_result(result, emit) or changed
        if self.tools.get("git") and self.git_root:
            for key in ("user.name", "user.email"):
                if not any(c.name == key and c.status == "falhou" for c in self.checks):
                    continue
                value = input_fn(f"Valor para {key} (identidade de commit, não login; Enter para pular): ").strip()
                if not value:
                    continue
                if any(ord(char) < 32 for char in value):
                    emit("Valor contém caracteres de controle; reparo ignorado.")
                    continue
                if self._confirm(f"Gravar {key}={value} somente na configuração Git local {self.git_config_path} (checkout {self.root}).", input_fn, emit):
                    if not self._unchanged_root():
                        emit("Raiz/branch mudou durante a confirmação. Reexecute o diagnóstico.")
                        return changed
                    result = self.git("config", "--local", key, value, repair=True, operation="diagnostico.identity")
                    changed = self._repair_result(result, emit) or changed
            if self.branch and any(c.name == "Upstream" and c.status == "falhou" for c in self.checks):
                result = self.git("for-each-ref", "--format=%(refname)", "refs/remotes/")
                options = [line for line in self.text(result).splitlines() if line.startswith("refs/remotes/") and not line.endswith("/HEAD")]
                if result.returncode or not options:
                    emit("Nenhuma ref de rastreamento disponível. Configure remoto/fetch manualmente; o diagnóstico não faz fetch.")
                else:
                    emit("Upstreams locais disponíveis:\n" + sanitize("\n".join(options)))
                    value = input_fn("Ref completa para rastrear (Enter para pular): ").strip()
                    if value and value not in options:
                        emit("Ref não consta da lista; nenhuma configuração alterada.")
                    elif value and self._confirm(f"Configurar branch {self.branch} para rastrear {value} na configuração local {self.git_config_path} (checkout {self.root}).", input_fn, emit):
                        valid = self.git("show-ref", "--verify", "--quiet", value)
                        if not self._unchanged_root() or valid.returncode:
                            emit("Raiz/branch/ref mudou durante a confirmação. Reexecute o diagnóstico.")
                            return changed
                        result = self.git("branch", "--set-upstream-to=" + value, self.branch,
                                          repair=True, operation="diagnostico.upstream")
                        changed = self._repair_result(result, emit) or changed
        return changed

    def exit_code(self):
        return int(any(c.status in ("falhou", "inconclusivo") for c in self.checks))

    def render(self, emit=print):
        emit(sanitize(f"Diagnóstico AgentsCloud — {self.root}"))
        for check in self.checks:
            emit(f"[{check.status}] {check.name}: {check.detail}")
        emit("Nenhum teste de push foi executado. user.name/email são identidade de commit, não login.")


def main(argv=None, *, default_repo=None):
    parser = argparse.ArgumentParser(description="Diagnóstico stdlib do AgentsCloud; ajuda não executa verificações.")
    parser.add_argument("--repo", type=Path, default=default_repo or Path.cwd(), help="Raiz do clone a diagnosticar")
    parser.add_argument("--offline", action="store_true", help="Não consultar rede; reparo uv usa --offline")
    parser.add_argument("--non-interactive", action="store_true", help="Somente relatar; nunca perguntar ou reparar")
    parser.add_argument("--output", type=Path, help="Exportar JSON sanitizado para um arquivo novo")
    parser.add_argument("--repair", action="store_true", help="Oferecer reparos consentidos (já é o padrão em terminal interativo)")
    args = parser.parse_args(argv)
    doctor = Diagnostics(args.repo, offline=args.offline, progress=print)
    try:
        doctor.collect()
        doctor.render()
        interactive = not args.non_interactive and sys.stdin.isatty() and sys.stdout.isatty()
        if interactive:
            if doctor.repairs():
                doctor.collect()
                doctor.render()
        elif args.repair and not args.non_interactive:
            print("Reparos exigem terminal interativo; nenhuma ação autorizada por entrada redirecionada.")
        if args.output:
            # Exportação é opt-in; nunca sobrescreve um arquivo preexistente.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump({"repo": sanitize(str(doctor.root)), "checks": [asdict(c) for c in doctor.checks], "events": doctor.events},
                          stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            print("Relatório exportado: " + sanitize(str(args.output.resolve())))
        return doctor.exit_code()
    except (EOFError, KeyboardInterrupt):
        print("Diagnóstico cancelado. Nenhuma ação pendente foi autorizada; reparos já concluídos permanecem.")
        return 130
    except OSError as exc:
        print("Diagnóstico não concluído: " + sanitize(exc), file=sys.stderr)
        return 1
