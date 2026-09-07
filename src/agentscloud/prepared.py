"""Contrato interno dos atalhos: o ambiente pertence a uma versão fixa do clone."""

from dataclasses import dataclass

from .errors import AgentsCloudError
from .git import Repository, Upstream


@dataclass(frozen=True)
class PreparedCheckout:
    head: str
    branch: str
    remote: str
    branch_ref: str
    upstream_commit: str | None = None

    def check_local(self, repo: Repository) -> None:
        repo.require_clean()
        branch = repo.run("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
        remote = repo.run("config", "--get", f"branch.{branch}.remote").decode().strip()
        branch_ref = repo.run("config", "--get", f"branch.{branch}.merge").decode().strip()
        if (repo.head(), branch, remote, branch_ref) != (self.head, self.branch, self.remote, self.branch_ref):
            raise AgentsCloudError(
                "HEAD/branch/upstream mudou após a preparação. Execute o atalho novamente; "
                "nenhum novo merge será aplicado com o ambiente já carregado."
            )

    def check_upstream(self, repo: Repository, upstream: Upstream) -> None:
        self.check_local(repo)
        if (upstream.commit, upstream.remote, upstream.branch_ref) != (self.upstream_commit or self.head, self.remote, self.branch_ref):
            raise AgentsCloudError(
                "O upstream mudou após a preparação. Execute o atalho novamente "
                "para atualizar código e dependências juntos."
            )
