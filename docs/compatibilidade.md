# Compatibilidade e piloto

Este documento distingue o funcionamento da CLI, a validação dos TOMLs e o
carregamento real dos agentes pelo Codex. As evidências abaixo são um registro
datado da preparação da versão 0.1.0, em **7 de setembro de 2026**. Resultados
posteriores pertencem ao commit e à execução que os produziram.

## Evidências disponíveis

| Verificação | Evidência registrada na preparação de 0.1.0 | Limite |
| --- | --- | --- |
| CLI em Windows | Python 3.11.15, Git 2.55.0.windows.5 e uv 0.12.3; suíte local e catálogo/índice verificados na implementação | A validação ocorre em repositórios e homes temporários |
| Symlink pessoal no Windows | O teste local de criação foi pulado por WinError 1314; rejeição de symlink remoto exercitada por índice Git temporário | Restrição de privilégio, sem evidência de sucesso do teste pulado |
| Linux e macOS | Matriz de CI implementada com Python 3.11 | Na preparação documental, sem resultado remoto registrado; consultar a execução por commit |
| Dependências | `uv.lock` versionado e `uv sync --locked` previsto no fluxo local/CI | Alterações de dependência exigem novo lock e nova validação |
| Formato TOML nativo | Três campos obrigatórios conferidos: `name`, `description`, `developer_instructions` | Verificação estrutural não comprova reconhecimento ou execução pelo Codex |
| Runtime Codex | CLI 0.153.0-alpha.5 observada na preparação, sem sessão real de homologação | Carregamento, seleção e execução continuam pendentes |
| Responsáveis pelos exemplos | `maintainer = "A definir"` nos três exemplos | A equipe ainda precisa aceitar a atribuição |
| Piloto da equipe | Roteiro e registro abaixo preparados | Três participantes e resultados ainda não registrados |

O contrato de configuração vem da [documentação oficial de agentes](https://learn.chatgpt.com/docs/agent-configuration/subagents).
O destino pessoal segue `~/.codex/agents/`, ou `CODEX_HOME/agents/` quando essa
raiz for configurada, conforme a [documentação de variáveis](https://learn.chatgpt.com/docs/config-file/environment-variables).
Os campos opcionais da configuração são preservados pela cópia; o validador
não substitui a validação de todas as opções pelo runtime.

O [workflow](../.github/workflows/validate.yml) executa testes, validação e índice
nas três plataformas. Confira os resultados e os skips no [GitHub Actions](https://github.com/samvieiracar-debug/AgentsCloud/actions),
sempre vinculados ao SHA do commit. A existência da matriz não significa que ela
já passou em cada plataforma; um resultado verde tampouco homologa o runtime Codex.

## Homologar o carregamento no Codex

1. Registre o sistema operacional, a versão Python/Git, a versão exata de
   `codex --version` e o SHA do AgentsCloud obtido com `git rev-parse HEAD`.
2. Combine o cenário com a equipe e use um perfil de teste separado. Defina
   `CODEX_HOME` para um diretório dedicado na sessão de teste; confirme o caminho
   apresentado pela CLI antes de instalar. Isso evita misturar a homologação com
   agentes pessoais existentes.
3. Execute `uv run agentscloud update`, confira o remoto e aceite a instalação
   somente no destino de teste escolhido. Registre os arquivos instalados e
   eventuais backups ou recusas.
4. Inicie uma sessão Codex usando o mesmo perfil, com as condições de acesso
   necessárias ao ambiente da equipe. Peça, por exemplo:
   **“Use o agente documentador para explicar este pequeno módulo Python.”**
   Use um módulo de teste cujo comportamento seja conhecido.
5. Confira evidência de que o agente nomeado foi reconhecido e executado. Anote
   qual configuração foi usada, a saída, erros e o critério observado. Uma
   resposta textual do assistente ou TOML parseável, isoladamente, não basta
   para afirmar que houve delegação ao agente correto.
6. Execute um cenário representativo de cada agente, compare a entrega às
   instruções e registre as limitações. A equipe define quais combinações de
   sistema/versão estão aprovadas com base nesses resultados.

Se o nome não for reconhecido, verifique o perfil efetivo, a versão do Codex e o
contrato oficial vigente. Registre o erro reproduzível antes de mudar a
configuração. Não preencha a coluna de aceite enquanto o resultado não existir.

## Piloto com três participantes

Escolha três participantes e atribua responsáveis pelos exemplos antes do aceite
do piloto. Cada participante deve executar um fluxo completo de atualização e
instalação, uma contribuição nova em branch/remoto de teste autorizados e um
cenário real de uso do agente no Codex.

Observe também uma recusa de atualização/instalação, uma tentativa com nome já
ocupado e a preservação de trabalho pessoal. Divida esses cenários entre os
participantes para evitar repetições desnecessárias. Quando houver falha de push
ou divergência, registre o procedimento de recuperação e o que foi preservado.

Meça duração e dificuldades observadas, com o mesmo critério para todos. Registre
erros e o parecer do participante; não estime ganho de produtividade como se
fosse resultado medido.

| Participante | Sistema e versões | SHA do projeto | Cenários e duração observada | Evidência de execução Codex | Resultado e pendências |
| --- | --- | --- | --- | --- | --- |
| A definir 1 | Pendente | Pendente | Pendente | Pendente | Pendente |
| A definir 2 | Pendente | Pendente | Pendente | Pendente | Pendente |
| A definir 3 | Pendente | Pendente | Pendente | Pendente | Pendente |

O aceite registra quais plataformas/versões foram verificadas, quem assumiu cada
agente, problemas encontrados e pendências aceitas pela equipe. Publicar os
arquivos ou concluir a CI não preenche esse registro automaticamente.
