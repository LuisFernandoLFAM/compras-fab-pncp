# Compras da FAB no PNCP

Pipeline de dados sobre as contratações e contratos do Comando da Aeronáutica publicados no Portal Nacional de Contratações Públicas.

## Sobre o projeto

O pipeline baixa as contratações e os contratos de um órgão público da [API de consulta do PNCP](https://pncp.gov.br/api/consulta), pública e sem cadastro, e os guarda num banco DuckDB (`compras_fab.duckdb`).

O caso de uso é o Comando da Aeronáutica, mas o órgão é definido pelo CNPJ no `config.toml`. Trocar o CNPJ faz o pipeline servir para qualquer órgão que publique no PNCP.

Os dados passam por camadas:

1. **Landing zone** (`data/landing/`): cada resposta da API salva em arquivo, exatamente como chegou.
2. **Camada bruta** (schema `raw`): um registro por linha, com o JSON original e colunas de controle da coleta. Guarda todas as versões de cada registro, sem apagar nem alterar.
3. **Transformação, marts e painel**: etapas seguintes.

Por enquanto, só a etapa 1 está implementada: a landing zone e a camada `raw`.

## Tabelas

Grão de cada tabela da camada `raw`:

| Tabela | Uma linha por |
| --- | --- |
| `raw.contratacoes` | versão de cada contratação. O mesmo registro pode aparecer mais de uma vez, uma por versão; o `_hash` identifica a versão. |
| `raw.contratos` | versão de cada contrato, com a mesma regra. |
| `raw.execucoes` | execução do pipeline. |

A escolha da versão mais recente de cada registro fica para a etapa de transformação.

## Como rodar

Pré-requisito: [uv](https://docs.astral.sh/uv/), que instala o Python e as dependências do projeto.

Para começar do zero:

```bash
git clone https://github.com/LuisFernandoLFAM/compras-fab-pncp.git
cd compras-fab-pncp
```

Depois:

```bash
uv run python -m pipeline.ingestao                    # completa na 1ª vez, incremental depois
uv run python -m pipeline.ingestao --completa         # força a carga completa
uv run python -m pipeline.ingestao --ate 2026-10-31   # define a data final
uv run python -m pipeline.ingestao --reconstruir      # recria o banco a partir da landing, sem API
```

A primeira execução faz a carga completa, de 01/01/2023 até ontem. As seguintes trazem só o que foi publicado ou atualizado desde a última execução com sucesso. Se uma execução falhar, basta rodar de novo: ela retoma das janelas que ficaram incompletas.

Testes:

```bash
uv run pytest                  # testes unitários, sem internet
uv run pytest -m integracao    # teste de integração, chama a API real
```

Recomendação: desative a suspensão do computador durante a carga completa. Na primeira carga, o computador suspendeu três vezes. O pipeline se recuperou sozinho graças às novas tentativas, mas o tempo total passou de 9 horas.

## Custo e eficiência

Números medidos com o Comando da Aeronáutica:

| Execução | Chamadas à API | Tempo | Resultado |
| --- | --- | --- | --- |
| Carga completa (07 e 08/11/2026) | 1.027 | cerca de 81 min ativos | 19.778 linhas, 34,75 MB na landing |
| Incremental (08/11/2026, 1 dia) | 14 | 41 s | 0 linhas (07/11/2026 foi sábado, sem atualizações) |
| Reconstrução a partir da landing (08/11/2026) | 0 | 21 s | banco idêntico ao original |

A primeira medição da carga completa deu 9h38min, porque o computador suspendeu três vezes durante a execução; descontadas as suspensões, foram cerca de 81 minutos de trabalho. A análise está em [docs/analise-carga-completa.md](docs/analise-carga-completa.md).

**O que cada decisão economiza:**

- **Landing zone:** recriar o banco custa 0 chamadas e 21 segundos, em vez de outra carga completa de cerca de 85 minutos. O banco é descartável.
- **Incremental:** atualizar um dia custa 14 chamadas, em vez de 1.027.
- **Pausa de 3 s entre chamadas:** não encurta a carga completa, porque o limite da API, de cerca de 20 chamadas por minuto, é o que define a duração. Mas reduz as respostas HTTP 429 de 74 para no máximo cerca de 10.

**Otimização avaliada e não adotada:** consultar cada modalidade uma vez para o período inteiro antes de percorrer os meses evitaria cerca de 280 chamadas vazias na carga completa. Não compensa, porque a carga completa roda raramente e o incremental já faz poucas chamadas.

## Onde a IA errou (e como percebi)

**"Zero pregões em 2025".** Na exploração, um script de teste transformou uma consulta que falhou em "zero pregões em 2025", quando eram 2.012. Percebi porque o zero destoava dos outros anos. Isso virou a regra "erro nunca vira zero" da decisão 6: qualquer falha que não seja vazio legítimo para a execução.

**Esperas curtas para o HTTP 429.** A spec previa esperas de 2, 4 e 8 segundos para falhas temporárias, e a primeira carga real parou num HTTP 429 persistente. A spec foi corrigida antes do código, com esperas próprias para o 429 (o `Retry-After` da API ou 30, 60 e 120 segundos).

**Hash sem ordenar as chaves.** No plano da fase 1, o hash seria calculado sobre o JSON sem ordenar as chaves, o que criaria versões falsas se a API mudasse a ordem dos campos. Percebi na revisão do plano, antes de virar código. O hash passou a ser calculado sobre uma forma canônica do JSON, com as chaves ordenadas, e ganhou um teste.

**Data da última carga.** No resumo da fase 2, a IA afirmou que a última carga ia até 07/11, mas o banco registrava 06/11. Se fosse verdade, o incremental pularia um dia inteiro. Percebi conferindo o banco antes de rodar. Era só um erro no texto; o código estava certo.

## Documentação

- [specs/ingestao.md](specs/ingestao.md): spec da etapa 1, com as decisões e os motivos.
- [docs/analise-carga-completa.md](docs/analise-carga-completa.md): análise do tempo da primeira carga completa e das respostas HTTP 429.
