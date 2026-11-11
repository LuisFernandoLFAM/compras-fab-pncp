# Spec da etapa 4: Painel

## Objetivo

Mostrar os marts num painel em Streamlit e num relatório HTML com os mesmos gráficos, para o time de licitações de uma empresa que quer vender para a FAB decidir onde e quando disputar e contra quem. A tela não calcula nada: todo número vem pronto de um mart.

## Persona

A mesma da spec dos marts: time de licitações de uma empresa que quer vender para a FAB. Abre o painel para saber o que está aberto agora, o que vai vencer, onde está o dinheiro e quem são os concorrentes, e precisa confiar que o dado está atualizado.

## Fonte

As tabelas do schema `marts`, descritas em [specs/marts.md](marts.md). O painel não lê `raw` nem `refined`.

Números de referência (marts de 10/11/2026, data de referência 09/11/2026): 3.151 compras em 2026 (11,5 bilhões estimados), 197 propostas abertas, 326 contratos a vencer em 3 meses (578,6 milhões), desconto mediano de 21,2% em 2026 e 41 fornecedores fazendo 80% do valor.

## Rascunho do painel

Layout em Z: o olho começa no canto superior esquerdo, cruza o topo, desce na diagonal e percorre a linha seguinte. O que decide se o resto merece confiança (a saúde do dado) e o que pede ação (cartões, depois "Quando agir") vêm primeiro.

### Topo

- **À esquerda:** o título "Compras da FAB no PNCP" e uma linha dizendo para quem é o painel.
- **À direita, saúde do dado:**
  - **Dados extraídos em:** data e hora do fim da última ingestão com sucesso.
  - **Publicação mais recente:** data e hora da publicação mais recente no PNCP entre as compras e os contratos.
  - **Sinal de cor pela idade da extração:** verde até 7 dias, amarelo até 30 dias, vermelho acima de 30. Ao lado, o texto "há N dias".
  - **Data de referência:** "dados até 09/11/2026", porque "proposta aberta" e "contrato a vencer" são relativos a ela.

### Linha de cartões

| Cartão | Número | Rodapé |
| --- | --- | --- |
| Compras no ano | quantidade de compras do ano da data de referência e valor estimado | "ano até a data de referência" |
| Propostas abertas | quantidade | "encerram depois de 09/11/2026" |
| Contratos a vencer em 3 meses | quantidade e valor | "vigência termina até 3 meses depois da data de referência" |
| Desconto mediano | desconto mediano das compras do ano da data de referência | "sobre N compras com desconto; fora credenciamento, estimado zero e homologado nulo ou zero" |
| Concentração | quantos fornecedores fazem 80% do valor contratado | "de N fornecedores" |

### Filtros

- **Ano:** vale para os gráficos que têm ano no grão (unidade, modalidade, sem resultado, dispensas, TI e dados). O padrão é o ano da data de referência. Mostrar um ano por vez evita somar anos na tela.
- **Segmento:** `todos`, `ti` ou `dados`, para "Quando agir". `ti` inclui `dados`, como na spec dos marts.

Filtrar e ordenar linhas não é calcular: os números exibidos continuam sendo os do mart.

### Seção 1: Quando agir

| Elemento | Mart | Conteúdo |
| --- | --- | --- |
| Tabela de propostas abertas | 04 `propostas_abertas` | unidade, UF, modalidade, objeto, valor estimado, encerramento, dias para encerrar e segmento, em ordem de encerramento; filtrada pelo segmento |
| Tabela de contratos a vencer | 05 `contratos_a_vencer` | unidade, objeto, valor, fim da vigência, faixa (até 3, 3 a 6, 6 a 12 meses), incumbente, cliente desde e tempo de casa; filtrada pelo segmento e pela faixa |

Notas de leitura:

- "Proposta aberta" é relativa à data de referência; se a ingestão parar, compras já encerradas continuam aparecendo.
- Contratos com vigência sem fim (21) nunca aparecem como a vencer.
- Incumbente pessoa física aparece como "Pessoa física", sem objeto e sem tempo de casa.
- O segmento é heurístico e inclui capacitação (cursos, pós-graduações, MBAs).

### Seção 2: Onde está o dinheiro

| Elemento | Mart | Conteúdo |
| --- | --- | --- |
| Compras por mês | 01 `compras_mensal` | barras do valor estimado por mês, todos os anos, com a quantidade de compras ao passar o mouse; o mês incompleto em outra cor |
| Sazonalidade | 01 `compras_mensal` | mapa de calor ano por mês com `participacao_compras_no_ano` |
| Compras por unidade | 02 `compras_por_unidade` | barras horizontais das 15 unidades com maior valor estimado no ano escolhido, com UF e quantidade de compras |
| Compras por modalidade | 03 `compras_por_modalidade` | tabela do ano escolhido: compras, valor estimado, ticket médio, faixas de valor, prazo médio das propostas, desconto médio e mediano |
| Contratos por categoria | 03 `contratos_por_categoria` | barras do valor contratado por categoria no ano escolhido |

Notas de leitura:

- Valor estimado zero (578 compras) conta como compra, mas fica fora do ticket médio e do desconto.
- Homologado nulo fica fora da soma do homologado e do desconto; homologado zero fica fora do desconto.
- O mês da data de referência está incompleto e não deve ser comparado com os outros.
- O prazo médio do credenciamento é longo (anos), porque o credenciamento fica aberto enquanto vigora.
- Desconto: média simples e mediana; a mediana é menos afetada pelos extremos, como as 18 compras com homologado acima do estimado.

### Seção 3: Contra quem

| Elemento | Mart | Conteúdo |
| --- | --- | --- |
| Pareto de fornecedores | 06 `fornecedores` | barras do valor contratado dos 30 maiores fornecedores e a linha da participação acumulada, com uma linha de referência em 80% |
| Resumo | 06 `fornecedores_resumo` | frase "N de M fornecedores fazem 80% do valor contratado" |

Notas de leitura:

- O valor contratado soma `valor_global` de todos os contratos do período, inclusive os 164 sem compra encontrada.
- Todos os contratos de pessoa física formam uma única linha, "Pessoa física".
- O nome exibido é o do contrato mais recente do fornecedor.

### Seção 4: Onde há espaço

| Elemento | Mart | Conteúdo |
| --- | --- | --- |
| Compras provavelmente sem resultado | 07 `compras_sem_resultado` | barras horizontais das combinações de unidade e modalidade com maior taxa no ano escolhido, só as com pelo menos 10 compras elegíveis, com a quantidade de elegíveis ao lado |
| Dispensas com disputa | 08 `dispensas_com_disputa` | barras das unidades com mais dispensas com disputa no ano escolhido, com a participação e o desconto mediano |

Notas de leitura:

- "Provavelmente sem resultado" é inferido: o PNCP não informa se a compra foi deserta ou fracassada. Ficam de fora as revogadas, anuladas e suspensas.
- A taxa só considera compras divulgadas, com disputa e propostas encerradas há mais de 90 dias.
- O corte de 10 compras elegíveis evita taxas de 100% sobre uma compra só.
- "Nenhum contrato ligado" olha só contratos com compra encontrada.

### Seção 5: TI e dados

| Elemento | Mart | Conteúdo |
| --- | --- | --- |
| TI e dados por unidade | 09 `ti_e_dados` | barras do valor estimado das compras e do valor contratado por unidade, no ano e segmento escolhidos |
| Principais fornecedores | 09 `ti_e_dados_fornecedores` | tabela dos 10 maiores de cada segmento |

Notas de leitura:

- O segmento é uma classificação heurística por palavras-chave no objeto; haverá falsos positivos e negativos.
- `ti` inclui `dados`.
- O segmento inclui capacitação em TI e dados, que mostra demanda de formação, e não só fornecimento de tecnologia.

### Rodapé

A fonte (API de consulta do PNCP), a cobertura (matriz e 7 filiais do Comando da Aeronáutica; a lista de filiais pode estar incompleta, e as filiais só publicaram compras em 2024 e 2025) e o link para as specs.

## Decisões

### 1. Três arquivos e um módulo de gráficos

| Arquivo | Papel |
| --- | --- |
| `painel.py` | Só faz SELECT nos marts. Cada consulta é uma função que devolve um DataFrame. |
| `graficos.py` | Monta as figuras Plotly a partir dos DataFrames, sem calcular nenhum número. |
| `app.py` | Desenha a tela em Streamlit com as consultas de `painel.py` e as figuras de `graficos.py`. |
| `relatorio.py` | Gera `relatorio.html` com as mesmas consultas e as mesmas figuras. |

**Motivo:** é o padrão da aula 4, com um módulo a mais para as figuras. Sem ele, o painel e o relatório teriam cada um a sua cópia de cada gráfico, e os dois iam divergir. `painel.py` continua só com SELECT.

**Alternativas consideradas:** montar as figuras em `painel.py`. Foi descartado para manter `painel.py` restrito a consultas, como na aula.

**Custo da decisão:** um arquivo a mais do que o padrão.

### 2. A tela não calcula nada; o mart 10_kpis entrega os números dos cartões

Todo número exibido vem pronto de um mart. Os cartões e a saúde do dado usam números que nenhum mart entregava em uma linha (compras do ano, desconto mediano do ano, contratos a vencer em 3 meses, data da extração e publicação mais recente), por isso foi criado o mart `10_kpis`, com uma linha, descrito em [specs/marts.md](marts.md).

**Exceção:** a idade da extração ("há N dias") e a cor do sinal dependem do dia em que o painel é aberto, então são calculadas na tela, a partir de `extraido_em` do mart 10. Os limites (7 e 30 dias) ficam numa constante de `painel.py`.

**Motivo:** um número calculado na tela pode divergir do mesmo número em outro lugar; vindo do mart, ele tem uma definição só, a da spec dos marts. A idade da extração não pode vir pronta, porque mudaria sem o mart ser recriado.

**Custo da decisão:** um cartão novo exige mexer no mart 10, e não só na tela.

### 3. Conexão somente leitura, aberta e fechada dentro de ler()

`painel.py` tem uma função `ler(sql, parametros)` que abre o banco em modo somente leitura, executa a consulta, fecha a conexão e devolve um DataFrame. Nenhuma conexão fica aberta entre as consultas.

**Motivo:** o painel nunca altera o banco, e uma conexão aberta seguraria o arquivo do DuckDB e impediria o pipeline de gravar.

**Custo da decisão:** abrir uma conexão por consulta; com o cache da decisão 4, isso acontece só ao carregar ou recarregar.

### 4. Cache com botão "Recarregar dados"

Em `app.py`, a leitura dos marts fica em funções com `st.cache_data`. Um botão "Recarregar dados" limpa o cache e lê de novo.

**Motivo:** os marts só mudam quando o pipeline roda; sem cache, cada clique num filtro abriria o banco de novo. O botão deixa o usuário buscar os dados novos depois de rodar o pipeline, sem reiniciar o Streamlit.

**Custo da decisão:** depois de rodar o pipeline, o painel aberto mostra os dados antigos até alguém clicar no botão. A saúde do dado no topo mostra de quando são os dados exibidos.

### 5. Relatório HTML autocontido

`relatorio.py` grava `relatorio.html` na raiz do projeto, com as mesmas seções, cartões, gráficos, tabelas e notas de leitura do painel, para o ano da data de referência e sem filtro de segmento. O JavaScript do Plotly vai embutido uma vez no arquivo; nada é carregado da internet.

**Motivo:** o relatório pode ser enviado por e-mail ou aberto sem rede e sem Python.

**Custo da decisão:** o arquivo fica com alguns megabytes, por causa do Plotly embutido; o relatório é uma foto do dia, sem os filtros do painel.

**Versionamento:** `relatorio.html` fica fora do git (`.gitignore`), porque é derivado do banco, que também fica fora.

### 6. Pessoa física e texto livre

O painel só mostra colunas dos marts, que já cumprem a decisão 6 da transformação e a decisão 5 dos marts: fornecedor pessoa física sempre agregado como "Pessoa física", sem identificador, e nenhum objeto de contrato de pessoa física. O painel não exibe `ni_fornecedor` em nenhum lugar, nem de pessoa jurídica.

**Motivo:** a regra fica garantida nos marts, e o painel não tem como desfazê-la por engano.

**Custo da decisão:** o identificador do fornecedor pessoa jurídica (CNPJ) não aparece na tela, só o nome.

## Como rodar

```bash
uv run streamlit run app.py   # abre o painel no navegador
uv run python relatorio.py    # gera relatorio.html na raiz do projeto
```

O painel e o relatório leem os marts como estão; para dados novos, rode antes `uv run python -m pipeline`. Enquanto o pipeline grava no banco, o painel não consegue abri-lo.

## Definição de pronto

- [ ] `painel.py` só tem consultas SELECT aos marts, e `ler()` abre e fecha uma conexão somente leitura a cada chamada.
- [ ] Nenhum número é calculado em `app.py`, `graficos.py` ou `relatorio.py`, exceto a idade da extração (decisão 2).
- [ ] O topo mostra a extração, a publicação mais recente, o sinal de cor e a data de referência.
- [ ] Os cinco cartões e as cinco seções aparecem na ordem do rascunho, cada gráfico com as suas notas de leitura.
- [ ] O botão "Recarregar dados" lê os marts de novo.
- [ ] `relatorio.html` abre sem internet e tem as mesmas seções e gráficos do painel.
- [ ] Nenhum identificador de fornecedor nem objeto de contrato de pessoa física aparece no painel ou no relatório.
- [ ] Os testes cobrem as funções de `painel.py` e `graficos.py` com um banco temporário, sem abrir o banco do projeto.
- [ ] O README explica como abrir o painel e gerar o relatório.

## Fora de escopo

- Publicar o painel na internet.
- Login ou controle de acesso.
- Alertas por e-mail de propostas abertas ou contratos a vencer.
- Filtros por unidade, UF ou fornecedor além dos descritos.
- Os próximos passos da spec dos marts (modelo estrela, recorrência de compras, atas e adesões).
