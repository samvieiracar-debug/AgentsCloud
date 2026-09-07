# Compatibilidade e piloto

Este documento distingue o funcionamento da CLI, a validação dos TOMLs e o
carregamento real dos agentes pelo Codex. As evidências abaixo são um registro
datado da preparação da versão 0.1.0, em **7 de setembro de 2026**. Resultados
posteriores pertencem ao commit e à execução que os produziram.

## Primeira execução remota verificada

A [CI de 7 de setembro de 2026](https://github.com/samvieiracar-debug/AgentsCloud/actions/runs/34084897708)
concluiu com sucesso para o commit `5e959f3a4d6efa19ad9d19e8b96653999ce633af`.
Em cada plataforma, passaram os **43 testes, sem skips**, a instalação pelo lock,
a validação dos agentes/catálogo e a conferência do índice:

| Plataforma do runner | Python | Testes aprovados | Skips |
| --- | --- | --- | --- |
| Windows | 3.11 | 43 | 0 |
| Linux | 3.11 | 43 | 0 |
| macOS | 3.11 | 43 | 0 |

O clone limpo local também foi instalado e validado: 42 testes aprovados e um
skip de symlink por privilégio Windows. Os runners da CI conseguiram executar
esse teste. Esses resultados confirmam os cenários automatizados da CLI; a
homologação do runtime ainda estava pendente nessa execução. O teste posterior
do `documentador` está registrado abaixo; o piloto humano continua pendente.

## Simulação e uso real do documentador (DEV-003)

Em 7 de setembro de 2026, o snapshot local **DEV-003-S02**, baseado
no commit `b767676a93e1180b0a3fddf318c24083e6bfec66`, contém uma
[simulação reproduzível](simulacao.md). São **45 testes na suíte: 44 aprovados e
um skip local Windows**, por falta de privilégio de symlink (WinError 1314).
Essa suíte ampliada ainda não foi publicada nem executada na CI remota.

O laboratório persistente passou em **25/25 verificações**. Criou os agentes
`qa-resumo` e `qa-revisor`, fez dois uploads com commits e pushes para um remoto
bare local, sincronizou o consumidor e instalou cinco TOMLs em um perfil
isolado. Conferiu duplicidade, recusa, idempotência e preservação de conflito.
Somente as respostas e a seleção foram simuladas; Git, arquivos e instalação
foram reais.

Separadamente, o Codex **0.153.0-alpha.5, em Windows**, executou o agente nativo
`documentador` em uma amostra Python. O TOML instalado foi copiado para a pasta
`.codex/agents/` de um workspace de teste. Original, instalado e arquivo usado
pelo runtime tinham o mesmo SHA256:

```text
dd3756d88aafe1bdbf238dcb3e940f3fb69edecbbb4623433b1b72619df42656
```

O teste usou um processo próprio `app-server --stdio`, controlador e filho
efêmeros, sandbox `read-only` e o modelo configurado `gpt-6-astra`. Os metadados
do filho confirmaram `agentRole = "documentador"` e vínculo com seu controlador.
Ele leu módulo, testes e README, executou `python -B -m unittest -v` com **3/3
aprovados** e produziu documentação sobre cálculo de desconto, lista vazia e
`ValueError`. Os arquivos de origem permaneceram idênticos.

**Condição observada:** foi necessário registrar o papel explicitamente na
configuração dessa sessão por `agents.documentador.config_file`, apontando
para o caminho absoluto do TOML, e `agents.documentador.description`. Essas
chaves fazem parte da [referência oficial de configuração](https://learn.chatgpt.com/docs/config-file/config-reference).
Apenas colocar o arquivo no projeto não disponibilizou o papel nas tentativas
iniciais, que emitiram um aviso de projeto não confiável. A causa completa da
descoberta automática não foi isolada; ela continua sem homologação neste
ambiente. O teste com registro explícito não altera essa conclusão.

A autenticação existente foi usada para o acesso ao Codex, sem copiar
credenciais ou instalar agentes no perfil pessoal. Não houve mudança persistente
em `config.toml`. Os demais agentes, outras combinações de runtime/sistema e o
piloto com três participantes continuam pendentes. Os registros anteriores
abaixo são históricos e mantêm os resultados obtidos naquela etapa.

## Evidências registradas antes da primeira CI

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
