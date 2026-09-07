"""Operações Git explícitas, sem shell e sem assumir origin/main."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import re

from .catalog import Bundle, make_bundle, updated_readme
from .errors import AgentsCloudError
from .processes import EventLog, LOCAL_TIMEOUT, NETWORK_TIMEOUT, INTERACTIVE_NETWORK_TIMEOUT, PUSH_TIMEOUT, run_command, sanitize


@dataclass(frozen=True)
class Upstream:
    remote: str
    branch_ref: str
    commit: str


@dataclass(frozen=True)
class PushTarget:
    remote: str
    branch_ref: str
    url: str

    @property
    def display(self):
        return f"{self.remote}, {self.branch_ref} ({sanitize(self.url)})"


class GitCommandError(AgentsCloudError):
    def __init__(self, operation, result):
        self.result = result
        guidance = {
            "autenticacao": "Confira a autenticação Git/GCM; nome/email de commit não são login. Execute diagnostico.py.",
            "permissao_ou_politica": "Confira acesso e políticas da branch; esse erro não comprova token inválido. Execute diagnostico.py.",
            "conexao": "Confira conexão, URL e TLS com diagnostico.py.",
            "timeout": "O limite de tempo terminou. Confira rede/login com diagnostico.py antes de tentar novamente.",
        }.get(result.category, "Execute diagnostico.py para conferir a configuração e os logs.")
        super().__init__(f"git {operation} falhou [{result.category}]: {result.message}\n{guidance}")


class Repository:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.log = None
        actual = self.run("rev-parse", "--show-toplevel").decode().strip()
        if Path(actual).resolve() != self.path:
            raise AgentsCloudError(f"Informe a raiz do repositório: {sanitize(actual)}")
        log_path = Path(self.run("rev-parse", "--git-path", "agentscloud/logs").decode().strip())
        self.log = EventLog(log_path if log_path.is_absolute() else self.path / log_path)

    def run(self, *args: str, timeout=None, interactive=None, input_bytes=None) -> bytes:
        position = 0
        while args[position] == "-c":
            position += 2
        operation = args[position]
        if interactive is None:
            interactive = operation in ("fetch", "pull", "push")
        if timeout is None:
            if operation in ("fetch", "ls-remote", "pull", "push"):
                timeout = INTERACTIVE_NETWORK_TIMEOUT if interactive else NETWORK_TIMEOUT
            else:
                timeout = LOCAL_TIMEOUT
        result = run_command([shutil.which("git") or "git", "-C", str(self.path), *args],
                             cwd=self.path, timeout=timeout, interactive=interactive,
                             operation="git-" + operation, log=self.log, input_bytes=input_bytes)
        if result.returncode:
            raise GitCommandError(operation, result)
        return result.stdout

    def branch(self):
        return self.run("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()

    def optional_config(self, key):
        result = run_command([shutil.which("git") or "git", "-C", str(self.path), "config", "--get", key],
                             cwd=self.path, operation="git-config", log=self.log, expected_codes=(0, 1))
        if result.returncode not in (0, 1):
            raise GitCommandError("config", result)
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def head(self) -> str:
        try:
            return self.run("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        except AgentsCloudError as exc:
            raise AgentsCloudError("O repositório ainda não tem commit inicial. Prepare e publique a base primeiro.") from exc

    def require_clean(self) -> None:
        if self.run("status", "--porcelain=v1", "--untracked-files=all"):
            raise AgentsCloudError("Checkout/índice não está limpo. Salve ou resolva suas alterações antes de continuar.")

    def fetch_upstream(self) -> Upstream:
        self.head()
        self.require_clean()
        try:
            branch = self.run("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
            remote = self.run("config", "--get", f"branch.{branch}.remote").decode().strip()
            branch_ref = self.run("config", "--get", f"branch.{branch}.merge").decode().strip()
        except AgentsCloudError as exc:
            raise AgentsCloudError("Branch sem upstream configurado (ou HEAD destacado). Configure o rastreamento da branch da equipe.") from exc
        if not remote or remote == "." or not branch_ref.startswith("refs/heads/"):
            raise AgentsCloudError("Upstream deve apontar para uma branch em um remoto Git configurado.")
        self.run("remote", "get-url", "--", remote)
        self.run("fetch", "--no-tags", "--", remote, branch_ref)
        commit = self.run("rev-parse", "--verify", "FETCH_HEAD^{commit}").decode().strip()
        return Upstream(remote, branch_ref, commit)

    def remote_bundle(self, upstream: Upstream) -> Bundle:
        entries = self.run("ls-tree", "-r", "-z", upstream.commit, "--", "Agents", "catalog.toml", "README.md")
        files: dict[str, bytes] = {}
        metadata: dict[str, bytes] = {}
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            header, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            path = raw_path.decode("utf-8", errors="strict")
            if path == "Agents":
                raise AgentsCloudError("Agents/ remoto deve ser um diretório regular, não um link.")
            if path.startswith("Agents/") and "/" in path[len("Agents/"):]:
                raise AgentsCloudError("Agents/ remoto deve ser plano, sem subpastas.")
            relevant = path in ("catalog.toml", "README.md") or path.lower().endswith(".toml")
            if not relevant:
                continue
            if kind != "blob" or mode not in ("100644", "100755"):
                raise AgentsCloudError(f"Arquivo remoto não é regular (links não são aceitos): {path}")
            content = self.run("cat-file", "blob", oid)
            if path.startswith("Agents/"):
                files[path[len("Agents/"):]] = content
            else:
                metadata[path] = content
        if "catalog.toml" not in metadata or "README.md" not in metadata:
            raise AgentsCloudError("Remoto deve conter catalog.toml e README.md.")
        bundle = make_bundle(files, metadata["catalog.toml"])
        if updated_readme(metadata["README.md"], bundle) != metadata["README.md"]:
            raise AgentsCloudError("Índice README remoto está desatualizado. Corrija com agentscloud index no remoto.")
        return bundle

    def is_ancestor(self, older: str, newer: str) -> bool:
        result = run_command([shutil.which("git") or "git", "-C", str(self.path),
                              "merge-base", "--is-ancestor", older, newer],
                             cwd=self.path, operation="git-ancestry", log=self.log, expected_codes=(0, 1))
        if result.returncode not in (0, 1):
            raise GitCommandError("merge-base", result)
        return result.returncode == 0

    def fast_forward(self, upstream: Upstream, expected_head: str) -> None:
        self.require_clean()
        if self.head() != expected_head:
            raise AgentsCloudError("HEAD mudou durante a confirmação; execute update novamente.")
        self.run("merge", "--ff-only", upstream.commit)

    def commit_agent(self, paths: list[str], name: str) -> str:
        self.run("add", "--", *paths)
        staged = {p.decode("utf-8") for p in self.run("diff", "--cached", "--name-only", "-z").split(b"\0") if p}
        if not staged.issubset(set(paths)):
            raise AgentsCloudError("Outros arquivos entraram no índice durante a operação; commit cancelado, contribuição preservada.")
        self.run("commit", "--only", "-m", f"Adiciona agente {name}", "--", *paths)
        # Candidato, nunca prova de autorização: o chamador valida pai e árvore.
        return self.head()

    def verify_contribution(self, commit: str, parent: str, contents: dict[str, bytes]) -> None:
        error = ("O commit/HEAD não corresponde à contribuição aprovada. "
                 "Commits e arquivos preservados; execute upload para revisar as pendências.")
        if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40,64}", commit):
            raise AgentsCloudError(error)
        if self.head() != commit:
            raise AgentsCloudError(error)
        lineage = self.run("rev-list", "--parents", "-n", "1", commit).decode().split()
        if lineage != [commit, parent]:
            raise AgentsCloudError(error)
        paths = set(p.decode("utf-8") for p in self.run(
            "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", parent, commit).split(b"\0") if p)
        if paths != set(contents):
            raise AgentsCloudError(error)

        def entries(revision):
            result = {}
            for entry in self.run("ls-tree", "-z", revision, "--", *contents).split(b"\0"):
                if entry:
                    header, path = entry.split(b"\t", 1)
                    mode, kind, oid = header.decode("ascii").split()
                    result[path.decode("utf-8")] = (mode, kind, oid)
            return result

        previous, created = entries(parent), entries(commit)
        for path, content in contents.items():
            # Aplica as regras Git de texto/filtros ao conteúdo aprovado, não ao
            # arquivo mutável do checkout. Também confere tipo/modo e todo o escopo.
            oid = self.run("hash-object", "--path", path, "--stdin", input_bytes=content).decode().strip()
            mode = previous[path][0] if path in previous else "100644"
            if mode not in ("100644", "100755") or created.get(path) != (mode, "blob", oid):
                raise AgentsCloudError(error)
        self.require_clean()
        if self.head() != commit:
            raise AgentsCloudError(error)

    def push_target(self, upstream: Upstream) -> PushTarget:
        branch = self.branch()
        override = self.optional_config(f"branch.{branch}.pushRemote") or self.optional_config("remote.pushDefault")
        if override and override != upstream.remote:
            raise AgentsCloudError("Destino de push difere do upstream (pushRemote/pushDefault). "
                                   "Escolha uma configuração coerente antes de publicar.")
        urls = self.run("remote", "get-url", "--push", "--all", "--", upstream.remote).decode().splitlines()
        if len(urls) != 1 or not urls[0].strip():
            raise AgentsCloudError("Publicação exige um único destino de push verificável; há múltiplas URLs ou destino vazio.")
        return PushTarget(upstream.remote, upstream.branch_ref, urls[0].strip())

    def fetch_target(self, target: PushTarget) -> str:
        # A consulta usa a URL de escrita; uma URL de fetch distinta não comprova publicação.
        self.run("fetch", "--no-tags", "--no-recurse-submodules", "--", target.url, target.branch_ref)
        return self.run("rev-parse", "--verify", "FETCH_HEAD^{commit}").decode().strip()

    def pending_commits(self, base: str, head: str):
        shas = self.run("rev-list", "--reverse", f"{base}..{head}").decode().splitlines()
        items = []
        for sha in shas:
            subject = self.run("show", "-s", "--format=%s", sha).decode("utf-8", errors="replace").strip()
            paths = self.run("diff-tree", "--root", "-m", "--no-commit-id", "--name-only", "-r", "-z", sha)
            files = sorted(set(p.decode("utf-8", errors="replace") for p in paths.split(b"\0") if p))
            items.append((sha, subject, files))
        return items

    def push(self, target: PushTarget, commit: str) -> None:
        # URL e refspec únicos ignoram remote.*.push/mirror; nenhuma tag/submódulo incidental.
        self.run("-c", "push.followTags=false", "-c", "push.recurseSubmodules=no",
                 "push", "--porcelain", "--no-follow-tags", "--recurse-submodules=no",
                 "--", target.url, f"{commit}:{target.branch_ref}",
                 timeout=PUSH_TIMEOUT, interactive=True)
