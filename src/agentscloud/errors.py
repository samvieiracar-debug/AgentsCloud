class AgentsCloudError(Exception):
    """Erro esperado que pode ser apresentado diretamente no terminal."""


class Cancelled(AgentsCloudError):
    """Interação cancelada pelo usuário."""
