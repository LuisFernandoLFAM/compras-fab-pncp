# Spec da etapa 1: Ingestão

## Objetivo

Trazer da API de consulta do PNCP as contratações e os contratos de um órgão público (caso de uso: Comando da Aeronáutica) para a camada bruta (`raw`) do DuckDB, sem interpretar nem alterar o conteúdo, de forma que a primeira execução faça a carga completa e as seguintes tragam apenas o que mudou.

## Fonte

API de consulta do Portal Nacional de Contratações Públicas, pública e sem cadastro: `https://pncp.gov.br/api/consulta`.

| Uso | Endpoint | Filtros usados |
|---|---|---|
| Carga completa de contratações | `/v1/contratacoes/publicacao` | data inicial e final, modalidade (obrigatória), CNPJ |
| Incremental de contratações | `/v1/contratacoes/atualizacao` | data inicial e final, modalidade (obrigatória), CNPJ |
| Carga completa de contratos | `/v1/contratos` | data inicial e final, CNPJ do órgão |
| Incremental de contratos | `/v1/contratos/atualizacao` | data inicial e final, CNPJ do órgão |

As duas tabelas se ligam pelo campo `numeroControlePncpCompra` do contrato, que aponta para o `numeroControlePNCP` da contratação.

## Decisões

### 1. Modalidades: as 13, sempre

O endpoint de contratações exige uma modalidade por consulta. A ingestão consulta os códigos de 1 a 13 em toda execução, inclusive os que hoje vêm vazios.

**Motivo:** no 1º semestre de 2026 a FAB usou 6 modalidades (pregão eletrônico 842, inexigibilidade 452, dispensa 279, concorrência eletrônica 34, credenciamento 9, concorrência presencial 3). Uma lista fixa com só essas perderia em silêncio qualquer modalidade que passe a ser usada. Filtrar modalidades, se um dia for preciso, é decisão da transformação ou dos marts.

**Custo da decisão:** 7 chamadas a mais por mês consultado, que respondem rápido e sem conteúdo.

Otimização avaliada e não adotada: uma consulta de sondagem por modalidade para o período inteiro evitaria cerca de 280 chamadas vazias na carga completa. Não foi adotada porque a carga completa roda raramente e o incremental faz poucas chamadas.

### 2. Período: de 01/01/2023 até ontem

- Data inicial fixa: 01/01/2023. Antes disso a FAB praticamente não publicava no PNCP (14 registros de pregão e inexigibilidade em 2022, contra 1.028 em 2023).
- Data final padrão: o dia anterior à execução, último dia completo.
- A data final pode ser informada por parâmetro, para reproduzir um resultado antigo.
- A mesma janela vale para contratações e contratos. Contratos de 2023 que venham de compras anteriores ao PNCP ficarão sem par; isso é tratado e documentado na transformação, não é erro de ingestão.

**Motivo:** o projeto deve continuar útil no futuro sem alteração de código. Os contratos costumam vir de compras do ano anterior (dos 771 contratos do 1º semestre de 2026, 507 vêm de compras de 2025), então a janela das contratações precisa começar cedo.

### 3. Formato da camada bruta: o JSON de cada registro, inteiro

Cada contratação ou contrato vira uma linha, com o JSON do registro exatamente como a API entregou numa coluna de texto, mais colunas de controle sobre a coleta. Desaninhar (órgão, unidade, amparo legal, listas de fontes orçamentárias) é trabalho da etapa 2.

**Motivo:** a camada bruta guarda o que a fonte entregou, sem interpretar. Achatar na ingestão seria transformação disfarçada, e campos novos da API se perderiam sem aviso.

### 4. Landing zone: toda resposta da API é salva em arquivo antes do banco

O fluxo é API → arquivos em `data/landing/` → DuckDB. Cada página respondida pela API é salva como recebida, e a camada bruta é carregada a partir desses arquivos.

Estrutura das pastas:

```
data/landing/<endpoint>/cnpj=<cnpj>/[modalidade=<nn>/]janela=<AAAA-MM-DD>_<AAAA-MM-DD>/pagina_<nnn>.json
```

Ao terminar e conferir uma janela, a ingestão grava nela um `_manifesto.json` com o total informado pela API, o total salvo e o número de páginas. Janela com manifesto está completa; janela sem manifesto está incompleta e será baixada de novo.

**Motivo:** separa a falha de rede da falha de gravação, permite recriar o banco sem tocar na API e guarda a prova do que a API respondeu.

**Custo da decisão:** cerca de 40 MB em disco para o período completo (estimativa a partir de 3,7 MB por semestre de pregões e dispensas; será medido). Em troca, recriar a camada bruta deixa de exigir a carga completa pela API.

### 5. Reexecução: carga completa na primeira vez, incremental pela data de atualização depois

- **Primeira execução** (nenhuma execução com sucesso registrada): carga completa pelos endpoints de publicação, mês a mês, de 01/01/2023 até a data final.
- **Execuções seguintes:** incremental pelos endpoints de atualização, do dia seguinte ao fim da última execução com sucesso até a data final.
- **Carga completa forçada:** disponível por parâmetro.
- **Reconstrução:** recarregar a camada bruta a partir da landing zone, sem nenhuma chamada à API, disponível por parâmetro.

**Motivo:** o dado do PNCP é vivo. No 1º semestre de 2026, 19% das contratações e 42% dos contratos da FAB foram atualizados depois de publicados (2% e 12%, respectivamente, mais de 6 meses depois). Baixar só os meses novos congelaria o passado; refazer tudo a cada execução repetiria centenas de chamadas.

**Verificado em 07/11/2026:** os 50 pregões e os 25 contratos da FAB publicados entre 30/10 e 06/11/2026 apareceram também no endpoint de atualização, ou seja, registros novos entram pelo incremental.

**Custo da decisão:** a ser medido e registrado no README. Estimativa: carga completa de 20 a 30 minutos; incremental semanal com menos de um minuto.

### 6. Erros e lentidão da API

Regras fixas:

- Consultas em janelas de no máximo um mês (janelas de seis meses chegaram a 10 segundos por página e uma consulta travou).
- Páginas de 50 registros, o máximo aceito pela API.
- Tempo limite de 60 segundos por chamada.
- Até 3 novas tentativas, apenas para falhas temporárias: tempo esgotado, erro de conexão, HTTP 429 e HTTP 5xx.
- Espera antes de cada nova tentativa:
  - HTTP 429 (limite de requisições): o tempo indicado no cabeçalho `Retry-After`, se a resposta trouxer; se não trouxer, 30, 60 e 120 segundos.
  - Demais falhas temporárias: 2, 4 e 8 segundos.
- Cada nova tentativa gera uma linha de aviso no log com o código (ou o erro), quanto tempo vai esperar e qual tentativa é (por exemplo, "nova tentativa 2 de 3 em 60 s"), para a execução não parecer travada.
- HTTP 204 (sem conteúdo) é vazio legítimo, não erro.
- Pausa de 3 segundos entre chamadas, para não sobrecarregar uma API pública e ficar abaixo do limite de requisições.
- As chamadas se identificam com um User-Agent com o nome e o link do projeto.
- **Erro nunca vira zero.** Qualquer falha que não seja vazio legítimo é tratada como falha.

Falha persistente (depois das novas tentativas) ou qualquer outro código HTTP: a execução **para**, com mensagem dizendo endpoint, modalidade, janela e página. As janelas já concluídas permanecem na landing zone, e a próxima execução retoma a partir das janelas sem manifesto.

**Motivo:** durante a exploração, um script de teste transformou uma consulta que falhou em "zero pregões em 2025", quando eram 2.012. Erro calado é o pior tipo de erro.

Na primeira carga real (07/11/2026), a API respondeu HTTP 429 de forma persistente na janela 2023-07-01_2023-07-31 da modalidade 1, depois de 6 janelas concluídas. As esperas de 2, 4 e 8 segundos, pensadas para instabilidade passageira, não bastaram para o limite de requisições, e a execução parou (como previsto, sem perder as janelas concluídas). Por isso o 429 ganhou esperas próprias, mais longas, e respeita o `Retry-After` quando a API o informa.

A carga completa seguinte terminou com sucesso, com a pausa original de 0,5 segundo: 1.027 chamadas e 81 minutos de tempo ativo (descontadas as suspensões do computador). A API respondeu 429 74 vezes, e as esperas desses 429 consumiram cerca de metade do tempo ativo. O padrão das chamadas indica um limite de cerca de 20 chamadas por minuto, com rajadas de cerca de 7. Por isso a pausa passou para 3 segundos. Análise completa em [docs/analise-carga-completa.md](../docs/analise-carga-completa.md).

**Custo da decisão:** a pausa de 3 segundos não reduz o tempo da carga completa (estimativa: cerca de 85 minutos ativos, contra 81 com a pausa de 0,5 segundo), porque o limite da API já é o que define a duração. Em troca, as respostas 429 caem de 74 para no máximo cerca de 10, a execução fica mais previsível e o risco de um 429 persistente parar a carga diminui.

### 7. Conferência

Para cada janela (endpoint, modalidade e mês):

- **Contagem:** a soma dos registros salvos tem que ser igual ao total informado pela API na primeira página.
- **Duplicatas:** o número de registros tem que ser igual ao número de chaves (`numeroControlePNCP`) distintas.

Se alguma conferência falhar, a janela é baixada de novo uma vez (a diferença costuma vir de publicações feitas enquanto as páginas eram percorridas). Se falhar de novo, a execução para.

### 8. Versões: a camada bruta guarda todas, sem apagar nem alterar

Quando o incremental traz uma versão nova de um registro já existente, ela é **acrescentada** como nova linha. A escolha da versão mais recente é feita na transformação.

**Idempotência:** cada linha tem um hash SHA-256 do JSON do registro. Uma versão com hash já existente não é gravada de novo. Rodar o mesmo incremental duas vezes grava zero linhas na segunda.

**Motivo:** a camada bruta nunca altera dado, e o histórico de versões permite analisar mudanças (por exemplo, quando e quantas vezes o valor de um contrato mudou).

### 9. Configuração num lugar só

CNPJ do órgão, data inicial, endereços dos endpoints, modalidades, tempo limite, novas tentativas e pausa ficam em `config.toml`, na raiz do projeto, lido com `tomllib` (biblioteca padrão do Python). O código não tem esses valores escritos em outro lugar.

**Motivo:** trocar o CNPJ faz o pipeline servir para qualquer órgão do PNCP. A FAB é o caso de uso, não uma limitação.

### 10. Código testável sem a API

A parte que **busca** (faz a chamada HTTP) fica separada da parte que **processa** (decide o que fazer com a resposta). Devem ser funções puras, testáveis com respostas falsas:

- dividir o período em janelas mensais;
- montar os parâmetros de cada consulta;
- decidir se um código HTTP é sucesso, vazio, falha temporária ou falha definitiva;
- transformar uma resposta em linhas da camada bruta;
- calcular o hash de um registro;
- conferir contagem e duplicatas de uma janela;
- calcular a janela do incremental a partir da última execução com sucesso.

Os testes unitários usam respostas falsas em `test/fixtures/` e nunca chamam a API nem abrem o banco do projeto. Um teste de integração separado (marcado como `integracao` e fora da execução padrão) confere que registros recém-publicados aparecem no endpoint de atualização.

## Estrutura da camada bruta

Schema `raw` no arquivo `compras_fab.duckdb`.

**`raw.contratacoes`** e **`raw.contratos`** (mesmas colunas):

| Coluna | Conteúdo |
|---|---|
| `registro` | JSON do registro, exatamente como veio da API |
| `_hash` | SHA-256 do JSON do registro |
| `_endpoint` | endpoint consultado |
| `_modalidade` | código da modalidade consultada (vazio para contratos) |
| `_janela_inicio`, `_janela_fim` | período consultado |
| `_pagina` | página da resposta |
| `_arquivo_origem` | caminho do arquivo na landing zone |
| `_extraido_em` | data e hora da chamada à API |
| `_execucao_id` | execução que gravou a linha |

Todas as colunas são texto, seguindo o princípio da camada bruta.

**`raw.execucoes`** (uma linha por execução):

| Coluna | Conteúdo |
|---|---|
| `execucao_id` | identificador da execução |
| `modo` | `completa`, `incremental` ou `reconstrucao` |
| `inicio`, `fim` | data e hora de início e fim |
| `status` | `sucesso` ou `falha` |
| `dados_ate` | data final dos dados consultados |
| `chamadas_api` | número de chamadas feitas |
| `linhas_novas` | linhas gravadas na camada bruta |
| `linhas_ja_existentes` | versões descartadas por já existirem |
| `mb_landing` | tamanho da landing zone ao final |
| `mensagem_erro` | vazio em caso de sucesso |

A data de partida do próximo incremental é o `dados_ate` da última execução com `status = sucesso`. Execução que falha não avança essa data.

## Como rodar

```
uv run python -m pipeline.ingestao                    # completa na 1ª vez, incremental depois
uv run python -m pipeline.ingestao --completa         # força a carga completa
uv run python -m pipeline.ingestao --ate 2026-10-31   # define a data final
uv run python -m pipeline.ingestao --reconstruir      # recria a raw a partir da landing, sem API
```

Recomendação: desative a suspensão do computador durante a carga completa. Na primeira carga, o computador suspendeu três vezes; o pipeline retomou sozinho graças às novas tentativas, mas o tempo total passou de 9 horas, das quais só 81 minutos foram de execução.

## Definição de pronto

- [ ] A carga completa roda do zero, num clone limpo do repositório, e termina com `status = sucesso`.
- [ ] Todas as janelas têm manifesto, e as contagens conferem com a API.
- [ ] Interromper a carga no meio e rodar de novo retoma das janelas incompletas.
- [ ] Um incremental logo após a carga completa termina com sucesso.
- [ ] Dois incrementais seguidos: o segundo grava zero linhas novas.
- [ ] A reconstrução gera a mesma quantidade de linhas, sem nenhuma chamada à API.
- [ ] Os testes unitários das funções da decisão 10 passam sem internet.
- [ ] O README tem a seção "Custo e eficiência" com os números medidos (tempo, chamadas, MB) da carga completa, do incremental e da reconstrução.

## Requisitos registrados para as próximas etapas

**Transformação (etapa 2):**

- Desaninhar o JSON e escolher a versão mais recente de cada registro.
- Mascarar o CPF de fornecedores pessoa física. Na exploração, 4 dos 771 contratos do 1º semestre de 2026 tinham fornecedor pessoa física (agricultura familiar) com CPF completo. O CPF permanece apenas na camada bruta, que fica fora do repositório.
- Avisar quando surgir um campo novo ou sumir um campo antigo no JSON.
- Investigar e manter (não corrigir) as anomalias vistas na exploração: 74 contratos publicados antes da data de assinatura, um contrato apontando para compra de 2027, número de processo com espaços nas pontas, compras com valor estimado zero.

**Painel (etapa 4):**

- Indicador de saúde no topo, com duas datas: "dados extraídos em" (fim da última execução com sucesso) e "publicação mais recente" (do próprio dado).
- Sinal de cor pela idade da extração (limites a definir na etapa 4).
- Notas de leitura junto dos indicadores, dizendo o que ficou de fora do cálculo.
- Camadas seguintes só são atualizadas quando a ingestão termina com sucesso; o painel nunca mostra dado pela metade.

**Qualidade (etapa 4):**

- Alerta quando não houver nenhuma publicação do órgão há mais de um número de dias a definir.

## Fora de escopo

- Itens das contratações e resultados por item (fornecedor vencedor e valor homologado por item).
- Atas de registro de preço e plano de contratações anual.
- Contratações com propostas abertas (endpoint existente, útil para uma versão futura voltada a fornecedores).
- Agendamento automático das execuções.
