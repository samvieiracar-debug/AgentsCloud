"""Operações Git explícitas, sem shell e sem assumir origin/main."""

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .catalog import Bundle, make_bundle, updated_readme
from .errors import AgentsCloudError


@dataclass(frozen=True)
class Upstream:
    remote: str
    branch_ref: str
    commit: str


class Repository:
    def __init__(self, path: Path):
        self.path = path.resolve()
        actual = self.run("rev-parse", "--show-toplevel").decode().strip()
        if Path(actual).resolve() != self.path:
            raise AgentsCloudError(f"Informe a raiz do repositório: {actual}")

    def run(self, *args: str) -> bytes:
        try:
            result = subprocess.run(["git", "-C", str(self.path), *args],
                                    capture_output=True, check=False)
        except FileNotFoundError as exc:
            raise AgentsCloudError("Git não encontrado. Instale Git e disponibilize-o no PATH.") from exc
        if result.returncode:
            message = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
            raise AgentsCloudError(f"git {args[0]} falhou: {message}")
        return result.stdout

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
        result = subprocess.run(["git", "-C", str(self.path), "merge-base", "--is-ancestor", older, newer],
                                capture_output=True, check=False)
        if result.returncode not in (0, 1):
            raise AgentsCloudError("Não foi possível comparar as versões Git.")
        return result.returncode == 0

    def fast_forward(self, upstream: Upstream, expected_head: str) -> None:
        self.require_clean()
        if self.head() != expected_head:
            raise AgentsCloudError("HEAD mudou durante a confirmação; execute update novamente.")
        self.run("merge", "--ff-only", upstream.commit)

    def commit_agent(self, paths: list[str], name: str) -> None:
        self.run("add", "--", *paths)
        staged = {p.decode("utf-8") for p in self.run("diff", "--cached", "--name-only", "-z").split(b"\0") if p}
        if not staged.issubset(set(paths)):
            raise AgentsCloudError("Outros arquivos entraram no índice durante a operação; commit cancelado, contribuição preservada.")
        self.run("commit", "--only", "-m", f"Adiciona agente {name}", "--", *paths)

    def push(self, upstream: Upstream) -> None:
        self.run("push", "--", upstream.remote, f"HEAD:{upstream.branch_ref}")
