"""Revisão de commits pendentes e publicação de SHA fixado, sem journal obrigatório."""

from .errors import AgentsCloudError
from .processes import sanitize


def _assert_unchanged(repo, upstream, target, head, branch):
    repo.require_clean()
    if repo.head() != head or repo.branch() != branch:
        raise AgentsCloudError("HEAD/branch mudou durante a confirmação. Execute upload novamente.")
    fresh = repo.fetch_upstream()
    if (fresh.remote, fresh.branch_ref) != (upstream.remote, upstream.branch_ref):
        raise AgentsCloudError("Upstream mudou durante a confirmação. Execute upload novamente.")
    if fresh.commit != upstream.commit:
        raise AgentsCloudError("O upstream mudou após a prévia. Execute upload novamente.")
    if repo.push_target(fresh) != target:
        raise AgentsCloudError("Destino de push mudou durante a confirmação. Execute upload novamente.")


def review_pending(repo, ui, base, head, target):
    commits = repo.pending_commits(base, head)
    ui.emit(f"Há {len(commits)} commit(s) local(is) pendente(s). Destino: {target.display}")
    ui.emit("A publicação incluirá TODOS os commits abaixo, independentemente de sua origem:")
    for sha, subject, files in commits:
        ui.emit(f"  {sha} — {sanitize(subject, 65536)}")
        for filename in files:
            ui.emit(f"    {sanitize(filename, 65536)}")
        if not files:
            ui.emit("    (sem alteração de arquivos)")
    ui.emit(f"SHA exato a publicar: {head}")
    return ui.confirm(f"Deseja publicar exatamente estes {len(commits)} commit(s) no destino exibido?")


def publish_exact(repo, ui, upstream, target, head, base, branch):
    """Um envio consentido; só uma repetição adicional, também revisada/consentida."""
    for attempt in range(2):
        _assert_unchanged(repo, upstream, target, head, branch)
        tip = repo.fetch_target(target)
        if repo.is_ancestor(head, tip):
            ui.emit(f"Publicação já confirmada no destino. Commit: {head}. Nenhum novo push foi necessário.")
            repo.log.write("upload", commit=head, ref=target.branch_ref, outcome="ja_publicado")
            return
        if tip != base:
            raise AgentsCloudError("O destino remoto mudou após a prévia. Commit preservado; execute upload novamente.")
        repo.log.write("push-attempt", commit=head, ref=target.branch_ref, outcome="tentativa")
        failure = None
        try:
            repo.push(target, head)
        except AgentsCloudError as exc:
            failure = exc
            ui.emit(f"Resultado do push ainda não confirmado. Commit local {head} preservado.")
            ui.emit(sanitize(exc))
        except KeyboardInterrupt:
            repo.log.write("push", commit=head, ref=target.branch_ref, outcome="interrompido_incerto")
            ui.emit(f"Publicação interrompida; resultado não confirmado. Commit {head} preservado. Execute upload novamente.")
            raise
        # Mesmo retorno zero precisa ser reconciliado no destino efetivo.
        try:
            current = repo.fetch_target(target)
        except AgentsCloudError as exc:
            repo.log.write("push", commit=head, ref=target.branch_ref, outcome="incerto")
            raise AgentsCloudError(
                f"Resultado incerto: não foi possível consultar o destino após o push. Commit {head} preservado.\n"
                f"{sanitize(exc)}\nExecute upload novamente para verificar antes de publicar outra contribuição."
            ) from exc
        if repo.is_ancestor(head, current):
            ui.emit(f"Publicação confirmada no destino. Commit: {head}")
            repo.log.write("push", commit=head, ref=target.branch_ref, outcome="publicado")
            return
        repo.log.write("push", commit=head, ref=target.branch_ref, outcome="pendente")
        if not repo.is_ancestor(current, head):
            raise AgentsCloudError(f"O remoto divergiu; commit local {head} preservado. Reconcilie manualmente, sem force push.")
        if failure is None:
            raise AgentsCloudError(f"O destino não contém {head} apesar do retorno do push. Resultado não confirmado; execute upload novamente.")
        if attempt == 1:
            raise AgentsCloudError(f"Publicação pendente. Commit local {head} preservado após duas tentativas. Corrija a causa e execute upload novamente.")
        _assert_unchanged(repo, upstream, target, head, branch)
        ui.emit("O destino ainda não contém o SHA. É possível fazer uma única nova tentativa nesta execução.")
        if not review_pending(repo, ui, current, head, target):
            raise AgentsCloudError(f"Nova tentativa recusada. Publicação pendente; commit local {head} preservado.")
        base = current


def handle_pending(repo, ui, upstream, target, head, tip):
    """Retorna True quando esta execução pertence a pendências, sem iniciar scan."""
    if head == tip:
        return False
    if repo.is_ancestor(head, tip):
        raise AgentsCloudError("O destino remoto avançou. Execute update antes de iniciar uma contribuição.")
    if not repo.is_ancestor(tip, head):
        raise AgentsCloudError("Histórico divergente do destino remoto. Reconcilie manualmente; nenhum push foi feito.")
    branch = repo.branch()
    if not review_pending(repo, ui, tip, head, target):
        ui.emit("Publicação de pendências recusada. Commits e remoto preservados.")
        return True
    publish_exact(repo, ui, upstream, target, head, tip, branch)
    # Nunca criar outro agente/commit após resolver ou recusar pendências.
    return True
