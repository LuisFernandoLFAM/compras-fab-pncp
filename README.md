# Compras da FAB no PNCP

Pipeline de dados sobre as contratações e contratos do Comando da Aeronáutica publicados no Portal Nacional de Contratações Públicas.

## Sobre o projeto

O pipeline baixa as contratações e os contratos de um órgão público da [API de consulta do PNCP](https://pncp.gov.br/api/consulta), pública e sem cadastro, e os guarda num banco DuckDB (`compras_fab.duckdb`).

O caso de uso é o Comando da Aeronáutica: a matriz e 7 filiais, com a mesma raiz de CNPJ. A lista de CNPJs fica no `config.toml`, e trocá-la faz o pipeline servir para qualquer órgão que publique no PNCP.

As filiais publicaram compras sob o próprio CNPJ em 2024 e 2025, por isso entram na carga junto com a matriz. A lista de filiais pode estar incompleta, porque foi montada a partir dos contratos da matriz ([decisão 12 da spec](specs/ingestao.md#12-matriz-e-filiais-uma-lista-de-cnpjs-cada-um-com-o-próprio-ponto-de-partida)).

Os dados passam por camadas:

1. **Landing zone** (`data/landing/`): cada resposta da API salva em arquivo, exatamente como chegou.
2. **Camada bruta** (schema `raw`): um registro por linha, com o JSON original e colunas de controle da coleta. Guarda todas as versões de cada registro, sem apagar nem alterar.
3. **Camada refinada** (schema `refined`): uma linha por contratação e por contrato, na versão vigente, com colunas tipadas, vazios normalizados, CPF de pessoa física mascarado, anomalias sinalizadas e cada contrato ligado à sua compra.
4. **Marts e painel**: etapas seguintes.

Por enquanto, estão implementadas as etapas 1 (landing zone e camada `raw`) e 2 (camada `refined`).

## Tabelas

Grão de cada tabela da camada `raw`:

| Tabela | Uma linha por |
| --- | --- |
| `raw.contratacoes` | versão de cada contratação. O mesmo registro pode aparecer mais de uma vez, uma por versão; o `_hash` identifica a versão. |
| `raw.contratos` | versão de cada contrato, com a mesma regra. |
| `raw.execucoes` | execução do pipeline para cada CNPJ. |

A escolha da versão vigente de cada registro é feita na camada `refined`.

### Camada refinada

A camada `refined` é recriada inteira a partir da `raw` a cada execução, numa única transação, e só depois de uma rodada de ingestão que terminou com sucesso para todos os CNPJs. Se algo falhar no meio, a refined anterior fica intacta ([spec da etapa 2](specs/transformacao.md)).

| Tabela | Uma linha por | Chave |
| --- | --- | --- |
| `refined.contratacoes` | contratação, na versão vigente | `numero_controle_pncp` |
| `refined.contratacoes_fontes` | contratação e fonte orçamentária | `numero_controle_pncp`, `ordem` |
| `refined.contratos` | contrato, na versão vigente, com a coluna `ligacao_compra` | `numero_controle_pncp` |
| `refined.anomalias` | ocorrência de uma regra de anomalia | (tabela, chave, regra) |
| `refined.execucoes` | execução da transformação; acumula o histórico, não é recriada | `execucao_id` |

- **Versão vigente:** a de maior data de atualização, olhando `dataAtualizacaoGlobal` e `dataAtualizacao`.
- **Tipos:** dinheiro em decimal exato, lido do texto do JSON sem passar por ponto flutuante; um valor que não cabe no tipo faz a transformação falhar, sem arredondar.
- **Vazios:** texto aparado; texto vazio vira nulo; nenhum nulo é preenchido.
- **CPF:** o CPF de fornecedor pessoa física e os CPFs em texto livre são mascarados no padrão dos portais de transparência (`***.456.789-**`).
- **Ligação com a compra:** cada contrato é classificado em compra encontrada, compra da FAB anterior ao período, compra de filial fora da lista, compra de outro órgão ou compra da FAB não encontrada. Nenhum contrato é descartado.

**Anomalias:** 11 regras de dado inconsistente (por exemplo, contrato publicado antes da assinatura, homologado acima do estimado, vigência que termina antes de começar) viram linhas em `refined.anomalias`, com uma descrição dos valores envolvidos. O registro continua na refined sem correção, e anomalia nunca derruba a execução. Situações que são prática administrativa normal ficam fora da tabela; a lista e os motivos estão na decisão 7 da spec.

**Contrato de dados:** a cada execução, os campos do JSON são comparados com os esperados pela spec.

| Situação | Resultado |
| --- | --- |
| Campo novo | Aviso no log |
| Campo descartado que passa a ter dado | Aviso no log |
| Campo descartado ausente nos registros da última rodada | Aviso no log |
| Campo esperado ausente nos registros da última rodada | A transformação falha, e a refined anterior fica intacta |

Os avisos são contados na coluna `avisos` de `refined.execucoes`.

## Como rodar

Pré-requisito: [uv](https://docs.astral.sh/uv/), que instala o Python e as dependências do projeto.

Para começar do zero:

```bash
git clone https://github.com/LuisFernandoLFAM/compras-fab-pncp.git
cd compras-fab-pncp
```

Depois:

```bash
uv run python -m pipeline                             # ingestão e, se ela terminar com sucesso, transformação
uv run python -m pipeline --ate 2026-10-31            # aceita os mesmos parâmetros da ingestão
uv run python -m pipeline.transformacao               # só a transformação, sobre a raw atual
uv run python -m pipeline.ingestao                    # só a ingestão: completa na 1ª vez, incremental depois
uv run python -m pipeline.ingestao --completa         # força a carga completa
uv run python -m pipeline.ingestao --ate 2026-10-31   # define a data final
uv run python -m pipeline.ingestao --reconstruir      # recria o banco a partir da landing, sem API
```

A primeira execução de cada CNPJ faz a carga completa, de 01/01/2023 até ontem. As seguintes trazem só o que foi publicado ou atualizado desde a última execução com sucesso. Se uma execução falhar, basta rodar de novo: ela retoma das janelas que ficaram incompletas.

A transformação recusa rodar se a última rodada de ingestão não terminou com sucesso para todos os CNPJs do `config.toml`.

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
| Carga completa das 7 filiais (09 e 10/11/2026) | 1.003 | cerca de 2h39min (soma de 9 execuções, incluindo 2 que falharam e foram retomadas) | 654 linhas (649 contratações e 5 contratos) |
| Incremental da matriz num dia útil (09/11/2026) | 14 | 59 s | 61 linhas |
| Transformação da raw inteira (10/11/2026) | 0 | 2,5 s | 13.677 contratações, 1.434 fontes, 6.786 contratos e 624 anomalias |

A primeira medição da carga completa deu 9h38min, porque o computador suspendeu três vezes durante a execução; descontadas as suspensões, foram cerca de 81 minutos de trabalho. A análise está em [docs/analise-carga-completa.md](docs/analise-carga-completa.md).

**O que cada decisão economiza:**

- **Landing zone:** recriar o banco custa 0 chamadas e 21 segundos, em vez de outra carga completa de cerca de 85 minutos. O banco é descartável.
- **Incremental:** atualizar um dia custa 14 chamadas, em vez de 1.027.
- **Sondagem anual:** a carga completa das filiais custou 1.003 chamadas, contra cerca de 4.600 estimadas sem a sondagem. Antes de descer mês a mês, uma consulta por ano diz se há registros; os anos sem nenhum são pulados.
- **Pausa de 3 s entre chamadas:** não encurta a carga completa, porque o limite da API, de cerca de 20 chamadas por minuto, é o que define a duração. Mas reduz as respostas HTTP 429 de 74 para no máximo cerca de 10.

**Otimização avaliada, primeiro não adotada e depois adotada:** sondar o período antes de percorrer os meses evitaria cerca de 280 chamadas vazias na carga completa da matriz. No início não compensava, porque a carga completa rodava raramente e para um CNPJ só. Passou a ser adotada, em forma de sondagem anual, quando a carga completa passou a rodar para vários CNPJs: as filiais publicaram em poucas modalidades e em poucos anos, e quase todas as consultas mês a mês viriam vazias.

## Onde a IA errou (e como percebi)

**"Zero pregões em 2025".** Na exploração, um script de teste transformou uma consulta que falhou em "zero pregões em 2025", quando eram 2.012. Percebi porque o zero destoava dos outros anos. Isso virou a regra "erro nunca vira zero" da decisão 6: qualquer falha que não seja vazio legítimo interrompe a execução.

**Esperas curtas para o HTTP 429.** A spec previa esperas de 2, 4 e 8 segundos para falhas temporárias, e a primeira carga real parou num HTTP 429 persistente. A spec foi corrigida antes do código, com esperas próprias para o 429 (o `Retry-After` da API ou 30, 60 e 120 segundos).

**Hash sem ordenar as chaves.** No plano da fase 1, o hash seria calculado sobre o JSON sem ordenar as chaves, o que criaria versões falsas se a API mudasse a ordem dos campos. Percebi na revisão do plano, antes de virar código. O hash passou a ser calculado sobre uma forma canônica do JSON, com as chaves ordenadas, e ganhou um teste.

**Data da última carga.** No resumo da fase 2, a IA afirmou que a última carga ia até 07/11, mas o banco registrava 06/11. Se fosse verdade, o incremental pularia um dia inteiro. Percebi conferindo o banco antes de rodar. Era só um erro no texto; o código estava certo.

**Só o CNPJ da matriz.** O recorte inicial filtrava só o CNPJ da matriz, sem verificar se a FAB publicava por outros CNPJs. Percebi ao investigar a ligação entre contratos e compras: 180 contratos apontavam para compras de filiais que a carga não tinha baixado (cerca de 12% das compras de 2024). Corrigi antes da transformação, para as etapas seguintes não serem validadas sobre dado incompleto.

**Sondagem com janelas anuais.** A sondagem foi desenhada com janelas anuais, mas o endpoint de contratos da API desiste de consultas anuais pesadas com HTTP 500 depois de cerca de 55 s. Percebi quando a carga parou duas vezes no mesmo ponto. Corrigi para que uma sondagem que falha caia para a consulta mês a mês, sem pular nenhum mês.

## Documentação

- [specs/ingestao.md](specs/ingestao.md): spec da etapa 1, com as decisões e os motivos.
- [specs/transformacao.md](specs/transformacao.md): spec da etapa 2, com as decisões, as regras de anomalia e os motivos.
- [docs/analise-carga-completa.md](docs/analise-carga-completa.md): análise do tempo da primeira carga completa e das respostas HTTP 429.
