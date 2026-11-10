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

**Sondagem anual na carga completa (adotada):** antes de descer mês a mês, a carga completa faz uma consulta por CNPJ, modalidade (ou endpoint de contratos) e ano, lendo só o `totalRegistros`. Onde der zero, os meses daquele ano são pulados; onde houver dado, a carga segue mês a mês. O primeiro ano começa na data inicial, e o último termina na data final da execução. Ela é a única consulta com janela maior que um mês, porque lê só o total e não percorre páginas. O incremental não faz sondagem.

**Motivo da sondagem:** ela tinha sido avaliada e não adotada, porque a carga completa rodava raramente e para um CNPJ só, e evitaria cerca de 280 chamadas vazias. Com as filiais (decisão 12), a carga completa passa a rodar para vários CNPJs, e cada CNPJ novo na lista faz a sua. As filiais publicaram em poucas modalidades e em poucos anos, então quase todas as consultas mês a mês viriam vazias.

**Custo da sondagem:** 14 consultas por ano e por CNPJ (13 modalidades e contratos), 56 por CNPJ no período de 2023 a 2026. Estimativa para uma filial que publicou só em 2024 e 2025 em 3 ou 4 modalidades: cerca de 170 chamadas com sondagem, contra cerca de 660 sem ela.

**Falha na sondagem não para a execução:** a sondagem tem só 1 nova tentativa (configurável no `config.toml`), porque existe um caminho de volta. Se ela falhar mesmo assim, o pipeline registra um aviso no log e consulta aquele ano mês a mês, como se a sondagem tivesse encontrado dado. O manifesto da sondagem registra que o ano foi consultado sem sondagem, com o erro. Isso não fere a regra "erro nunca vira zero" da decisão 6: nenhum mês é pulado, só se perde o atalho. As janelas mensais desse ano seguem as regras normais e param a execução em falha persistente.

**Motivo da queda para mês a mês:** na primeira carga das filiais, a sondagem anual do endpoint de contratos falhou com HTTP 500 persistente duas vezes (filial `00394429019715` em 2023 e filial `00394429018581` em 2024), e houve vários 500 passageiros em outras filiais. Cada tentativa levou cerca de 55 segundos antes do 500, o que indica um limite de tempo do servidor para janelas anuais. Parar a carga inteira por causa de um atalho seria desproporcional, e insistir com 3 novas tentativas custaria cerca de 4 minutos por sondagem.

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

O ponto de partida é decidido **por CNPJ** (decisão 12): numa mesma execução, um CNPJ pode fazer a carga completa enquanto os outros seguem no incremental.

- **Primeira execução de um CNPJ** (nenhuma execução com sucesso registrada para ele): carga completa pelos endpoints de publicação, com a sondagem anual da decisão 1 e mês a mês nos anos com dado, de 01/01/2023 até a data final.
- **Execuções seguintes:** incremental pelos endpoints de atualização, do dia seguinte ao `dados_ate` da última execução com sucesso daquele CNPJ até a data final, em janelas de no máximo um mês e com as 13 modalidades para contratações. Valem as mesmas regras de landing zone, manifesto, retomada, erros e conferência da carga completa.
- **Nada a consultar:** se o início do incremental cair depois da data final (por exemplo, dois incrementais no mesmo dia, ou `--ate` anterior ao último `dados_ate`), a execução termina com sucesso, sem chamadas, e mantém o `dados_ate` anterior. O `dados_ate` nunca retrocede.
- **Carga completa forçada:** disponível por parâmetro (`--completa`), para todos os CNPJs.
- **Reconstrução:** recarregar a camada bruta a partir da landing zone, sem nenhuma chamada à API, disponível por parâmetro (`--reconstruir`; ver decisão 11). Não pode ser combinada com `--completa` nem com `--ate`.

**Retomada:** uma janela com manifesto só é aproveitada se foi concluída por uma carga completa ou incremental que falhou depois da última carga completa ou incremental com sucesso do mesmo CNPJ. Depois de um sucesso, a carga completa forçada baixa tudo de novo, porque o dado é vivo. Janelas de publicação e de atualização ficam em pastas separadas (`contratacoes_publicacao/`, `contratacoes_atualizacao/` etc.), então os modos não se misturam. A reconstrução não mexe na landing e por isso não interfere na retomada.

**Motivo:** o dado do PNCP é vivo. No 1º semestre de 2026, 19% das contratações e 42% dos contratos da FAB foram atualizados depois de publicados (2% e 12%, respectivamente, mais de 6 meses depois). Baixar só os meses novos congelaria o passado; refazer tudo a cada execução repetiria centenas de chamadas.

**Verificado em 07/11/2026:** os 50 pregões e os 25 contratos da FAB publicados entre 30/10 e 06/11/2026 apareceram também no endpoint de atualização, ou seja, registros novos entram pelo incremental.

**Custo da decisão:** a ser medido e registrado no README. Estimativa: carga completa de 20 a 30 minutos; incremental semanal com menos de um minuto.

### 6. Erros e lentidão da API

Regras fixas:

- Consultas em janelas de no máximo um mês (janelas de seis meses chegaram a 10 segundos por página e uma consulta travou). A única exceção é a sondagem anual da decisão 1, que lê só a primeira página e tem regra própria de falha.
- Páginas de 50 registros, o máximo aceito pela API.
- Tempo limite de 60 segundos por chamada.
- Até 3 novas tentativas (1 na sondagem anual), apenas para falhas temporárias: tempo esgotado, erro de conexão, HTTP 429 e HTTP 5xx.
- Espera antes de cada nova tentativa:
  - HTTP 429 (limite de requisições): o tempo indicado no cabeçalho `Retry-After`, se a resposta trouxer; se não trouxer, 30, 60 e 120 segundos.
  - Demais falhas temporárias: 2, 4 e 8 segundos.
- Cada nova tentativa gera uma linha de aviso no log com o código (ou o erro), quanto tempo vai esperar e qual tentativa é (por exemplo, "nova tentativa 2 de 3 em 60 s"), para a execução não parecer travada.
- HTTP 204 (sem conteúdo) é vazio legítimo, não erro.
- Pausa de 3 segundos entre chamadas, para não sobrecarregar uma API pública e ficar abaixo do limite de requisições.
- As chamadas se identificam com um User-Agent com o nome e o link do projeto.
- **Erro nunca vira zero.** Qualquer falha que não seja vazio legítimo é tratada como falha.

Falha persistente (depois das novas tentativas) ou qualquer outro código HTTP numa janela mensal: a execução **para**, com mensagem dizendo endpoint, modalidade, janela e página. As janelas já concluídas permanecem na landing zone, e a próxima execução retoma a partir das janelas sem manifesto. A exceção é a sondagem anual: a falha dela não para a execução, e o ano é consultado mês a mês (decisão 1).

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

A lista de CNPJs do órgão (matriz e filiais, decisão 12), data inicial, endereços dos endpoints, modalidades, tempo limite, novas tentativas e pausa ficam em `config.toml`, na raiz do projeto, lido com `tomllib` (biblioteca padrão do Python). O código não tem esses valores escritos em outro lugar.

**Motivo:** trocar a lista de CNPJs faz o pipeline servir para qualquer órgão do PNCP. A FAB é o caso de uso, não uma limitação.

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

### 11. Banco descartável: espelho das execuções e reconstrução

A landing zone é a fonte da verdade, e o `compras_fab.duckdb` é derivado dela. Apagar o banco e rodar `--reconstruir` deixa tudo pronto para o próximo incremental, sem refazer a carga completa.

**Espelho das execuções:** cada execução é espelhada em `data/landing/_execucoes.jsonl`, com uma linha ao começar (`status = falha`, "execução em andamento ou interrompida") e outra ao terminar. Vale a última linha de cada `execucao_id`. No início de cada execução, as execuções do banco que faltarem no espelho são acrescentadas a ele (isso cobre as execuções anteriores a esta regra).

**Reconstrução** (`--reconstruir`), sem nenhuma chamada à API:

1. Recria `raw.execucoes` a partir do espelho.
2. Recria `raw.contratacoes` e `raw.contratos` a partir das janelas com manifesto dos CNPJs configurados, dos endpoints de publicação e de atualização. As janelas são carregadas na ordem em que foram extraídas (`concluido_em` do manifesto): quando a mesma versão aparece em mais de um arquivo, fica a primeira observação, como no fluxo original. Janelas sem manifesto são ignoradas, com aviso no log.
3. Mantém o `_execucao_id` original de cada linha (a execução que extraiu o registro, lida do manifesto), de modo que a camada bruta reconstruída fica igual à original.
4. Faz tudo numa transação: se a reconstrução falhar no meio, o banco anterior fica intacto.
5. Registra a própria execução com `modo = reconstrucao` e, para cada CNPJ, `dados_ate` igual ao da última execução com sucesso daquele CNPJ, para não deslocar o próximo incremental. CNPJ sem histórico fica com o `dados_ate` vazio.

**Motivo:** o banco pode ser corrompido, apagado ou recriado com outra estrutura sem custo de API. Sem o espelho, perder o banco apagaria também `raw.execucoes`, e a execução seguinte refaria a carga completa (cerca de 85 minutos ativos).

**Limitações:**

- A carga completa forçada sobrescreve as pastas de publicação. Versões que só existiam nesses arquivos não podem ser reconstruídas depois (continuam no banco enquanto ele existir).
- Perder a pasta `data/landing/` perde também o espelho: aí só resta a carga completa pela API.

### 12. Matriz e filiais: uma lista de CNPJs, cada um com o próprio ponto de partida

O `config.toml` traz uma lista de CNPJs: a matriz e as filiais conhecidas. A ingestão consulta cada CNPJ separadamente, com os mesmos endpoints, modalidades, período e regras das decisões anteriores.

- **Ponto de partida por CNPJ:** CNPJ sem carga completa com sucesso faz a carga completa (com a sondagem anual da decisão 1); os demais seguem no incremental. Incluir uma filial na lista faz a carga completa só dela.
- **Data por CNPJ:** cada CNPJ guarda a própria data da última execução com sucesso (`dados_ate`). A falha de um CNPJ não avança a data dos outros, e a retomada dele aproveita só as janelas dele.
- **Incremental em todos os CNPJs, sempre,** inclusive filiais que não publicam há meses, porque compras antigas continuam recebendo atualizações (80% das contratações da FAB foram alteradas depois de publicadas).

**Motivo:** a investigação da camada bruta para a etapa 2 (item 8 de `docs/investigacao-transformacao.md`) mostrou que 7 filiais da FAB publicaram compras sob o próprio CNPJ: 449 contratações em 2024 e 179 em 2025, nas modalidades 6, 8 e 9. Isso equivale a 11,8% e 4,3% do total da FAB nesses anos, e a ingestão, que consultava só a matriz, deixava tudo isso de fora. 180 contratos da matriz apontam para compras dessas filiais e ficavam sem par.

**Custo da decisão:**

- Carga completa das 7 filiais, com a sondagem: cerca de 1.200 chamadas, perto de uma hora com o limite de cerca de 20 chamadas por minuto. Sem a sondagem seriam cerca de 4.600.
- Incremental: 14 chamadas por CNPJ e por mês consultado, ou seja, 112 chamadas para os 8 CNPJs (antes, 14). Um incremental semanal passa de menos de um minuto para cerca de 6 minutos.

**Limitação:** a lista de filiais pode estar incompleta. Ela veio só das referências dos contratos da matriz (`numeroControlePncpCompra` com a raiz `00394429` e outro final), então uma filial que nunca teve contrato registrado sob a matriz não aparece. Não foi possível listar as filiais de uma raiz pela API: a API de consulta só aceita o CNPJ completo, e as tentativas pela API principal do PNCP falharam por instabilidade.

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
| `_execucao_id` | execução que extraiu o registro da API |

Todas as colunas são texto, seguindo o princípio da camada bruta.

**`raw.execucoes`** (uma linha por execução de cada CNPJ):

| Coluna | Conteúdo |
|---|---|
| `execucao_id` | identificador da execução de um CNPJ: `<rodada_id>-<cnpj>` |
| `modo` | `completa`, `incremental` ou `reconstrucao` |
| `inicio`, `fim` | data e hora de início e fim |
| `status` | `sucesso` ou `falha` |
| `dados_ate` | data final dos dados consultados (na reconstrução e no incremental sem nada a consultar, repete o da última execução com sucesso) |
| `chamadas_api` | número de chamadas feitas |
| `linhas_novas` | linhas gravadas na camada bruta |
| `linhas_ja_existentes` | versões descartadas por já existirem |
| `mb_landing` | tamanho da landing zone ao final |
| `mensagem_erro` | vazio em caso de sucesso |
| `cnpj` | CNPJ consultado (ou reconstruído) nessa execução |
| `rodada_id` | agrupa as execuções dos CNPJs feitas numa mesma chamada do comando |

Numa rodada, os CNPJs rodam na ordem do `config.toml`. A falha persistente de um CNPJ para a rodada: os CNPJs seguintes não rodam, não ganham linha e mantêm a data anterior. Na reconstrução, cada CNPJ configurado ganha uma linha, todas da mesma rodada.

**Execuções anteriores à lista de CNPJs:** o banco e o espelho dessas execuções não têm `cnpj` nem `rodada_id`. Na migração, o `cnpj` de cada uma é descoberto pelos manifestos que ela gravou na landing (o caminho da janela tem `cnpj=...`). Execução sem manifesto (por exemplo, com 0 chamadas) fica com a matriz `00394429000100`, com aviso no log. O `rodada_id` fica igual ao próprio `execucao_id`.

A data de partida do próximo incremental de cada CNPJ é o dia seguinte ao `dados_ate` da última execução daquele CNPJ com `status = sucesso` e `dados_ate` preenchido. Execução que falha não avança essa data.

`raw.execucoes` é espelhada em `data/landing/_execucoes.jsonl` (decisão 11).

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
- [ ] Dois incrementais seguidos: o segundo grava zero linhas novas. (No mesmo dia, o segundo não tem período a consultar; a idempotência pelo hash é coberta pelos testes unitários e pela reconstrução.)
- [ ] A reconstrução gera a mesma quantidade de linhas, sem nenhuma chamada à API.
- [ ] Apagar o `compras_fab.duckdb` e rodar `--reconstruir` deixa o próximo incremental partindo do `dados_ate` correto, sem refazer a carga completa.
- [ ] Uma filial nova na lista faz a carga completa só dela, enquanto os outros CNPJs seguem no incremental.
- [ ] A falha de um CNPJ não avança o `dados_ate` dos outros.
- [ ] A carga completa pula os anos em que a sondagem deu zero, e uma falha na sondagem faz o ano ser consultado mês a mês, sem pular nenhum mês.
- [ ] Os testes unitários das funções da decisão 10 passam sem internet.
- [ ] O README tem a seção "Custo e eficiência" com os números medidos (tempo, chamadas, MB) da carga completa, do incremental e da reconstrução.

## Requisitos registrados para as próximas etapas

**Transformação (etapa 2):**

- Desaninhar o JSON e escolher a versão mais recente de cada registro.
- A camada bruta mistura matriz e filiais nas mesmas tabelas; o CNPJ de quem publicou está em `orgaoEntidade.cnpj`.
- Mascarar o CPF de fornecedores pessoa física. Na exploração, 4 dos 771 contratos do 1º semestre de 2026 tinham fornecedor pessoa física (agricultura familiar) com CPF completo. O CPF permanece apenas na camada bruta, que fica fora do repositório.
- Avisar quando surgir um campo novo ou sumir um campo antigo no JSON.
- Investigar e manter (não corrigir) as anomalias vistas na exploração: 74 contratos publicados antes da data de assinatura, um contrato apontando para compra de 2027, compras com valor estimado zero.
- Os espaços nas pontas do número de processo, antes listados como anomalia, foram reclassificados como formatação e são removidos na transformação ([decisão 5 de specs/transformacao.md](transformacao.md#5-vazios-texto-aparado-vazio-vira-nulo-nulo-nunca-é-preenchido)).

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
