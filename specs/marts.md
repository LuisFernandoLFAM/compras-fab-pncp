# Spec da etapa 3: Marts

## Objetivo

Transformar a camada refinada (`refined`) em tabelas de indicadores prontas para responder às perguntas de quem quer vender para a FAB: quanto e quando ela compra, onde, por qual modalidade, o que está aberto agora, quais contratos vão vencer e quem os detém, quem são os fornecedores, onde as compras costumam não dar resultado e onde há dispensas com disputa. Um recorte de TI e dados destaca o segmento do objeto.

As tabelas ficam no schema `marts` e são recriadas inteiras a cada execução, só depois de uma transformação que terminou com sucesso.

## Persona

Time de licitações de uma empresa que quer vender para a FAB. Precisa decidir onde vale a pena disputar, preparar-se para as compras que estão abertas ou que vão se repetir e saber contra quem vai concorrer.

## Fonte

As tabelas `refined.contratacoes`, `refined.contratos` e `refined.execucoes`, descritas em [specs/transformacao.md](transformacao.md), e `raw.execucoes`, para a data de referência.

Números de referência (refined de 10/11/2026, data de referência 09/11/2026): 13.677 compras, 6.786 contratos, 30 unidades em 23 municípios de 18 UFs.

## Termos

Os termos abaixo são fechados: todo mart usa exatamente estas definições.

| Termo | Definição | Na refined de 10/11/2026 |
| --- | --- | --- |
| Data de referência | O `dados_ate` da última rodada de ingestão com sucesso: os dados vão até ontem. Se os CNPJs da rodada tiverem datas diferentes, vale a menor. | 09/11/2026 |
| Compra | Uma linha de `refined.contratacoes`. | 13.677 |
| Valor estimado | `valor_total_estimado`: o tamanho da intenção de compra. | |
| Valor homologado | `valor_total_homologado`: o que foi fechado. | |
| Desconto | (estimado - homologado) / estimado, só em compras com estimado maior que zero e homologado maior que zero, fora do credenciamento (modalidade 12). Homologado zero é ausência de valor, não desconto de 100%. | 11.121 compras elegíveis |
| Proposta aberta | Compra com o dia de `data_encerramento_proposta` posterior à data de referência. | 197 |
| Compra provavelmente sem resultado (deserta ou fracassada) | Situação "Divulgada no PNCP" (`situacao_compra_id = 1`), com disputa (`data_abertura_proposta` preenchida), propostas encerradas há mais de 90 dias da data de referência, homologado nulo e nenhum contrato ligado (nenhum contrato com `ligacao_compra = 'compra_encontrada'` apontando para ela). Sempre chamada de "provável", porque o PNCP não tem um campo que diga isso. | 1.296, de 8.418 compras divulgadas com disputa encerradas há mais de 90 dias |
| Dispensa com disputa | Modalidade 8 com `data_abertura_proposta` preenchida. | 3.008 das 3.710 dispensas |
| Mês | O da data de publicação no PNCP (`data_publicacao_pncp`), para compras e contratos. O ano segue a mesma regra. | |
| Contrato a vencer | `data_vigencia_fim` posterior à data de referência e até 12 meses depois dela, inclusive. A vigência sem fim fica de fora, com nota. | 1.372 em 12 meses; 21 sem fim |
| Fornecedor | Identificado por `ni_fornecedor`. O nome exibido é o do contrato mais recente (maior `data_assinatura`, depois maior `data_publicacao_pncp`). Pessoa física é sempre agregada como "Pessoa física", e empresário individual (`fornecedor_empresario_individual`) como "Empresário individual" (decisão 6 da transformação). | 3.483 fornecedores, contando "Pessoa física" e "Empresário individual" como um cada |
| Incumbente | O fornecedor do contrato a vencer. | |
| Tempo de casa | Tempo desde o primeiro contrato (menor `data_assinatura`) desse fornecedor com a mesma unidade (`unidade_codigo_unidade`) até a data de referência. | |
| Segmento | Classificação heurística do objeto: `dados`, `ti` ou `outros` (decisão 4). `dados` é um subconjunto de `ti`. | |

**Compra provavelmente sem resultado e situação da compra:** o termo deixa de fora as compras revogadas, anuladas e suspensas, que têm desfecho conhecido ou estão paradas. Sem essa condição, seriam 1.624 compras, das quais 328 com outra situação (213 revogadas, 102 suspensas e 13 anuladas). Com ela, revogadas, anuladas e provavelmente sem resultado não se sobrepõem no mart 02.

## Decisões

### 1. Marts como tabelas de indicadores prontas

Cada mart é uma tabela já agregada no grão da pergunta que responde, montada por um arquivo SQL próprio em `sql/marts/`, com o grão escrito no topo do arquivo. O painel lê as tabelas sem precisar de junções nem de regras de negócio.

**Motivo:** é o padrão das aulas, e o prazo é curto. As regras (os termos acima) ficam num lugar só, no SQL de cada mart, e o painel não tem como aplicá-las de jeitos diferentes.

**Alternativas consideradas:** o modelo estrela (fatos e dimensões) previsto como requisito na spec da transformação. Foi adiado por prazo e fica como próximo passo.

**Custo da decisão:** uma pergunta nova exige um mart novo ou uma coluna nova, em vez de uma consulta livre sobre fatos e dimensões. Os termos se repetem entre os arquivos SQL (por exemplo, a condição de proposta aberta aparece nos marts 04 e 09).

### 2. Recriação inteira, só depois de uma transformação com sucesso

- **Recriação inteira:** a cada execução, o schema `marts` é recriado do zero a partir da refined, numa única transação. Se algo falhar no meio, os marts anteriores ficam intactos. A exceção é `marts.execucoes`, que acumula o histórico.
- **Pré-condição:** os marts se recusam a rodar se a última execução da transformação (a linha mais recente de `refined.execucoes`) não terminou com sucesso.
- **Data de referência:** gravada em `marts.referencia`, a partir da rodada de ingestão usada pela última transformação (`rodada_ingestao`). Todo mart que depende de data lê dessa tabela, nunca da data do relógio.
- **Ordem:** os arquivos de `sql/marts/` rodam em ordem de nome. O `00_segmento_objeto.sql` roda primeiro, porque os marts 04, 05 e 09 dependem dele, e o `10_kpis.sql` roda por último, porque lê os marts 04, 05 e 06.
- **Comando único:** `python -m pipeline` passa a rodar ingestão, transformação e marts, cada etapa só se a anterior terminar com sucesso.

**Conferências que fazem os marts falharem:**

1. A soma de `compras` em `marts.compras_mensal` é igual ao número de linhas de `refined.contratacoes`, e a soma de `contratos` é igual ao de `refined.contratos`.
2. `marts.segmento_objeto` tem exatamente uma linha por compra e por contrato, com o segmento preenchido.
3. A soma de `valor_contratado` em `marts.fornecedores` é igual à soma de `valor_global` em `refined.contratos`.

**Registro:** cada execução ganha uma linha em `marts.execucoes`, gravada fora da transação, como na transformação.

**Motivo:** a refined é pequena e os marts são agregações; recriar tudo leva segundos e garante que os marts são sempre função da refined atual. Usar a data de referência dos dados, e não a do relógio, faz o mesmo banco gerar os mesmos marts em qualquer dia.

**Custo da decisão:** "proposta aberta" e "contrato a vencer" são relativos à data de referência; se a ingestão parar de rodar, os marts continuam mostrando como abertas compras que já fecharam. A data de referência fica visível em `marts.referencia` para o painel exibir.

### 3. Desconto médio: média simples, com a mediana ao lado

O desconto médio de um grupo é a média simples dos descontos das compras elegíveis (termo "Desconto"). Ao lado vai a mediana e a quantidade de compras elegíveis.

**Motivo:** a média simples é o que "desconto médio" diz e trata cada compra como uma disputa. A mediana vai ao lado porque a média é puxada pelos extremos, como as 18 compras elegíveis com homologado acima do estimado (desconto negativo, anomalia `homologado_acima_estimado`), que não são excluídas porque o termo é fechado. As 174 compras com homologado zero ficam fora pelo próprio termo.

**Alternativas consideradas:** o desconto agregado, 1 - (soma do homologado / soma do estimado). Foi descartado como indicador principal porque é dominado pelas compras grandes: na refined de 10/11/2026, ele dá 40,3%, contra 14,2% da média simples e 23,1% da mediana.

**Custo da decisão:** quem comparar com outra fonte que use o desconto agregado verá números diferentes.

### 4. Segmento do objeto: classificação heurística por palavras-chave

Cada compra e cada contrato recebe um segmento: `dados`, `ti` ou `outros`. `dados` é um subconjunto de `ti`: a tabela guarda o segmento mais específico, e todo indicador de `ti` inclui as linhas de `dados`.

**Texto classificado:** `objeto_compra` nas compras e `objeto_contrato` nos contratos, sem acento e em minúsculas. Os termos casam como palavras inteiras (limite de palavra nas duas pontas).

**Regras, na ordem:**

1. **Exclusões:** os trechos "dados bancarios", "voz e dados", "folha de dados" e "banco de dados de precos" são retirados do texto antes de procurar os termos de dados. O último vem da referência à tabela de preços de obras (SINAPI) em objetos de manutenção predial, que a primeira amostra classificou como `dados`. Eles não impedem a classificação como `ti` por outro termo.
2. **`dados`:** o texto tem um termo específico de dados. A palavra "dados" sozinha nunca classifica.
3. **`ti`:** o texto tem um termo de TI ou, nos contratos, `categoria_processo_id = 3` ("Informática (TIC)").
4. **`outros`:** nenhuma das anteriores.

| Segmento | Termos |
| --- | --- |
| `dados` | business intelligence, inteligencia de negocio(s), power bi, powerbi, qlik, tableau, banco(s) de dados, sgbd, analytics, ciencia de dados, cientista de dados, engenharia de dados, engenheiro de dados, data warehouse, datawarehouse, data lake, datalake, etl, big data, mineracao de dados, data science, governanca de dados |
| `ti` | tecnologia da informacao, tecnologia de informacao, ti, tic, informatica, software(s), sistema(s) de informacao, sistema(s) informatizado(s), fabrica de software, desenvolvimento de sistema(s), microcomputador(es), computador(es), notebook(s), desktop(s), servidor(es) de rede, storage, firewall, seguranca da informacao, ciberseguranca, seguranca cibernetica, antivirus, computacao em nuvem, cloud, data center, datacenter, rede de computadores, cabeamento estruturado, rede logica, aplicativo(s) |

**Capacitação:** o segmento inclui capacitação em TI e dados (cursos, pós-graduações, MBAs), que mostra demanda de formação, e não só fornecimento de tecnologia. Esses objetos não são excluídos.

**Auditoria:** `marts.segmento_objeto` guarda, para cada compra e cada contrato, o segmento e o termo que casou (ou `categoria_processo: Informática (TIC)`), para conferir por que cada registro foi classificado.

**Motivo:** a categoria oficial não basta. Na amostra da exploração, a categoria "Informática (TIC)" classificou só 18 de 151 contratos de software; o restante estava em "Serviços" ou "Compras". As palavras-chave pegam o objeto como foi descrito, e a regra da palavra "dados" evita os falsos positivos mais comuns ("dados bancários", "voz e dados", "folha de dados" e textos que só mencionam dados de passagem).

**Alternativas consideradas:** só a categoria `categoria_processo` "Informática (TIC)". Foi descartada pela cobertura baixa na amostra, e porque as compras não têm essa categoria. Uma classificação com modelo de linguagem foi descartada pelo prazo e por ser difícil de auditar.

**Custo da decisão:**

- É uma classificação heurística: haverá falsos positivos (por exemplo, "ti" como sigla de outra coisa, ou "aplicativo" fora de TI) e falsos negativos (objetos de TI descritos sem nenhum dos termos).
- A lista de termos precisa de revisão com uma amostra dos resultados; a primeira revisão é parte da definição de pronto.
- O segmento de um contrato não herda o da compra ligada: cada um é classificado pelo próprio objeto.

### 5. Pessoa física e empresário individual nos marts

Nos marts, o fornecedor pessoa física aparece sempre como "Pessoa física", e o empresário individual (`fornecedor_empresario_individual` verdadeiro na refined) como "Empresário individual", numa linha própria, separada da de pessoa física. Nos dois casos, sem `ni_fornecedor` e sem nome.

- **Ranking de fornecedores (06 e 09):** todos os contratos de pessoa física formam uma única linha, e todos os de empresário individual, outra.
- **Contratos a vencer (05):** o contrato aparece, com o incumbente "Pessoa física" ou "Empresário individual", sem objeto e sem tempo de casa.

**Motivo:** cumpre o requisito da decisão 6 da transformação (fornecedor pessoa física e empresário individual sempre agregados e texto livre dos contratos deles nunca exibido) já nos marts, que são o que o painel lê. O tempo de casa e o objeto, junto com a unidade e o valor, ajudariam a identificar a pessoa. O empresário individual é pessoa jurídica no PNCP, mas o nome dele é o de uma pessoa, seguido do CPF; a linha separada mostra quanto a FAB contrata de microempreendedores sem misturá-los com pessoas físicas.

**Custo da decisão:** o time de licitações não vê quem é o incumbente pessoa física ou empresário individual nem há quanto tempo ele atende a unidade. São 25 contratos de pessoa física e 164 de empresário individual, de 93 fornecedores.

## Marts

Schema `marts` no arquivo `compras_fab.duckdb`. Valores em `DECIMAL`, descontos e participações como fração (0,25 = 25%), prazos em dias.

**`marts.referencia`** (uma linha)

| Coluna | Conteúdo |
| --- | --- |
| `data_referencia` | data de referência |
| `rodada_ingestao` | `rodada_id` da ingestão de onde veio a data |
| `execucao_transformacao` | `execucao_id` da transformação usada |

**`marts.segmento_objeto`** (uma linha por compra e por contrato; arquivo `00_segmento_objeto.sql`)

| Coluna | Conteúdo |
| --- | --- |
| `tabela` | `contratacoes` ou `contratos` |
| `chave` | `numero_controle_pncp` |
| `segmento` | `dados`, `ti` ou `outros` |
| `termo` | termo que casou; nulo em `outros` |

### 01_compras_mensal

Perguntas: quanto a FAB compra por mês e por ano? Em que meses ela compra mais?

**`marts.compras_mensal`**, uma linha por ano e mês.

| Coluna | Conteúdo |
| --- | --- |
| `ano`, `mes` | mês de publicação |
| `mes_completo` | falso para o mês da data de referência, quando ele ainda não terminou |
| `compras` | quantidade de compras publicadas no mês |
| `valor_estimado`, `valor_homologado` | somas; o homologado soma só os não nulos |
| `compras_estimado_zero`, `compras_sem_homologado` | quantas compras do mês ficam fora de cada soma |
| `contratos`, `valor_contratado` | contratos publicados no mês e soma de `valor_global` |
| `participacao_compras_no_ano`, `participacao_valor_no_ano` | fração do ano que cai no mês (sazonalidade) |

### 02_compras_por_unidade

Perguntas: quais unidades compram mais, onde ficam e com que frequência suas compras são revogadas, anuladas ou ficam provavelmente sem resultado?

**`marts.compras_por_unidade`**, uma linha por unidade e ano.

| Coluna | Conteúdo |
| --- | --- |
| `unidade_codigo`, `ano` | chave |
| `unidade_nome`, `uf`, `municipio`, `orgao_cnpj` | da compra mais recente da unidade |
| `compras`, `valor_estimado`, `valor_homologado` | quantidade e somas |
| `revogadas`, `anuladas` | por `situacao_compra_id` (2 e 3) |
| `provaveis_sem_resultado` | termo "Compra provavelmente sem resultado" |
| `taxa_revogadas`, `taxa_anuladas`, `taxa_provaveis_sem_resultado` | sobre `compras`; as três categorias não se sobrepõem |

### 03_compras_por_modalidade

Perguntas: por qual modalidade a FAB compra, de que tamanho são as compras, quanto tempo há para preparar a proposta e qual desconto costuma sair? Nos contratos, em que categoria?

**`marts.compras_por_modalidade`**, uma linha por modalidade e ano.

| Coluna | Conteúdo |
| --- | --- |
| `modalidade_id`, `ano` | chave |
| `modalidade_nome` | |
| `compras`, `valor_estimado`, `valor_homologado` | quantidade e somas |
| `ticket_medio` | valor estimado / compras com estimado maior que zero |
| `faixa_estimado_zero`, `faixa_ate_50_mil`, `faixa_50_mil_a_500_mil`, `faixa_500_mil_a_5_milhoes`, `faixa_acima_5_milhoes` | quantidade de compras por faixa do valor estimado |
| `prazo_medio_propostas_dias` | média de dias entre a publicação e o encerramento das propostas, nas compras com disputa |
| `desconto_medio`, `desconto_mediano`, `compras_com_desconto` | decisão 3 |

**`marts.contratos_por_categoria`**, uma linha por categoria do processo e ano.

| Coluna | Conteúdo |
| --- | --- |
| `categoria_processo_id`, `ano` | chave |
| `categoria_processo_nome` | |
| `contratos`, `valor_contratado`, `ticket_medio` | `valor_global` |
| as mesmas cinco faixas, sobre `valor_global` | |

**Faixas de valor:** limites redondos (50 mil, 500 mil, 5 milhões), e não os limites legais de dispensa, porque esses são atualizados todo ano por decreto. O limite inferior é exclusivo e o superior é inclusivo.

### 04_propostas_abertas

Pergunta: o que está aberto agora e até quando dá para enviar proposta?

**`marts.propostas_abertas`**, uma linha por compra com proposta aberta.

| Coluna | Conteúdo |
| --- | --- |
| `numero_controle_pncp` | chave |
| `unidade_codigo`, `unidade_nome`, `uf`, `municipio` | |
| `modalidade_nome`, `objeto_compra`, `valor_estimado` | |
| `data_publicacao_pncp`, `data_encerramento_proposta`, `dias_para_encerrar` | dias contados a partir da data de referência |
| `link_sistema_origem` | onde a proposta é enviada, quando informado |
| `segmento` | decisão 4 |

### 05_contratos_a_vencer

Perguntas: quais contratos vencem em 3, 6 e 12 meses, quem os detém e há quanto tempo atende a unidade?

**`marts.contratos_a_vencer`**, uma linha por contrato a vencer.

| Coluna | Conteúdo |
| --- | --- |
| `numero_controle_pncp` | chave |
| `unidade_codigo`, `unidade_nome`, `uf`, `municipio` | |
| `objeto_contrato` | nulo para pessoa física e empresário individual (decisão 5) |
| `valor_global`, `data_vigencia_fim`, `dias_para_vencer` | |
| `faixa_vencimento` | `ate_3_meses`, `3_a_6_meses` ou `6_a_12_meses` (faixas que não se sobrepõem; "em 6 meses" soma as duas primeiras) |
| `fornecedor_id`, `fornecedor_nome`, `tipo_pessoa` | incumbente; "Pessoa física" ou "Empresário individual", sem identificador (decisão 5) |
| `cliente_desde`, `tempo_de_casa_anos`, `contratos_do_fornecedor_na_unidade` | termo "Tempo de casa"; nulos para pessoa física e empresário individual |
| `segmento` | decisão 4 |

### 06_fornecedores

Perguntas: quem são os maiores fornecedores da FAB e quão concentrado é o mercado?

**`marts.fornecedores`**, uma linha por fornecedor (todos os contratos de pessoa física numa linha só, e todos os de empresário individual em outra).

| Coluna | Conteúdo |
| --- | --- |
| `posicao` | no ranking por valor contratado |
| `fornecedor_id`, `fornecedor_nome`, `tipo_pessoa` | `fornecedor_id` nulo para "Pessoa física" e "Empresário individual" |
| `contratos`, `valor_contratado` | soma de `valor_global`, em todos os contratos, qualquer que seja a `ligacao_compra` |
| `participacao`, `participacao_acumulada` | Pareto |
| `ate_80_por_cento` | verdadeiro para os fornecedores que, em ordem, compõem os primeiros 80% do valor (inclui o que cruza os 80%) |

**`marts.fornecedores_resumo`** (uma linha): `fornecedores`, `fornecedores_80_por_cento` e `valor_contratado`. Na refined de 10/11/2026, 41 dos 3.483 fornecedores fazem 80% do valor contratado.

### 07_compras_sem_resultado

Pergunta: onde as compras com disputa costumam terminar sem resultado?

**`marts.compras_sem_resultado`**, uma linha por unidade, modalidade e ano.

| Coluna | Conteúdo |
| --- | --- |
| `unidade_codigo`, `modalidade_id`, `ano` | chave |
| `unidade_nome`, `modalidade_nome` | |
| `compras_elegiveis` | divulgadas no PNCP, com disputa e propostas encerradas há mais de 90 dias |
| `provaveis_sem_resultado`, `taxa_provaveis_sem_resultado` | termo "Compra provavelmente sem resultado" |
| `valor_estimado_provaveis_sem_resultado` | |

### 08_dispensas_com_disputa

Pergunta: quais unidades fazem dispensas com disputa, em que volume e com que desconto?

**`marts.dispensas_com_disputa`**, uma linha por unidade e ano.

| Coluna | Conteúdo |
| --- | --- |
| `unidade_codigo`, `ano` | chave |
| `unidade_nome`, `uf` | |
| `dispensas`, `dispensas_com_disputa`, `participacao_com_disputa` | todas as dispensas da unidade no ano e as com disputa |
| `valor_estimado`, `valor_homologado` | das dispensas com disputa |
| `desconto_medio`, `desconto_mediano`, `compras_com_desconto` | decisão 3 |

### 09_ti_e_dados

Perguntas: quanto a FAB compra de TI e de dados, onde, o que está aberto e quem fornece?

**`marts.ti_e_dados`**, uma linha por segmento (`ti` ou `dados`), ano e unidade. As linhas de `ti` incluem as de `dados`.

| Coluna | Conteúdo |
| --- | --- |
| `segmento`, `ano`, `unidade_codigo` | chave |
| `unidade_nome`, `uf` | |
| `compras`, `valor_estimado`, `valor_homologado` | compras do segmento |
| `propostas_abertas`, `valor_estimado_propostas_abertas` | |
| `contratos`, `valor_contratado` | contratos do segmento |

**`marts.ti_e_dados_fornecedores`**, os 10 maiores fornecedores de cada segmento por valor contratado.

| Coluna | Conteúdo |
| --- | --- |
| `segmento`, `posicao` | chave |
| `fornecedor_id`, `fornecedor_nome`, `tipo_pessoa` | como no mart 06 |
| `contratos`, `valor_contratado`, `participacao_no_segmento` | |

### 10_kpis

Perguntas: quanto a FAB comprou no ano, o que pede ação agora, qual desconto costuma sair, quão concentrado é o mercado e de quando é o dado? Criado para os cartões e a saúde do dado do painel ([specs/painel.md](painel.md)), que não calcula nenhum número na tela.

**`marts.kpis`**, uma linha.

| Coluna | Conteúdo | Na refined de 10/11/2026 |
| --- | --- | --- |
| `data_referencia`, `ano_referencia` | data de referência e o ano dela | 09/11/2026, 2026 |
| `extraido_em` | fim da última ingestão com sucesso: o maior `fim` em `raw.execucoes` da rodada de `marts.referencia` | 10/11/2026 20:54 |
| `publicacao_mais_recente` | maior `data_publicacao_pncp` entre compras e contratos | 09/11/2026 17:29 |
| `compras_ano`, `valor_estimado_ano` | compras publicadas no ano da data de referência e a soma do valor estimado | 3.151; 11,5 bilhões |
| `propostas_abertas`, `valor_estimado_propostas_abertas` | linhas e valor estimado do mart 04 | 197 |
| `contratos_a_vencer_3_meses`, `valor_a_vencer_3_meses` | contratos do mart 05 na faixa `ate_3_meses` e a soma de `valor_global` | 326; 578,6 milhões |
| `desconto_mediano_ano`, `compras_com_desconto_ano` | mediana do termo "Desconto" nas compras publicadas no ano da data de referência e quantas compras entram nela | 21,2%; 2.319 |
| `fornecedores`, `fornecedores_80_por_cento` | do mart 06 (`fornecedores_resumo`) | 3.483; 41 |

O ano da data de referência está incompleto (vai até a data de referência); o painel diz isso no rodapé do cartão.

**`marts.execucoes`** (uma linha por execução dos marts; não é recriada)

| Coluna | Conteúdo |
| --- | --- |
| `execucao_id` | identificador da execução |
| `execucao_transformacao` | `execucao_id` da transformação usada |
| `data_referencia` | data de referência |
| `inicio`, `fim` | data e hora de início e fim |
| `status` | `sucesso` ou `falha` |
| `tabelas`, `linhas` | tabelas criadas e total de linhas |
| `mensagem_erro` | vazio em caso de sucesso |

## Notas de leitura

O painel deve exibir junto de cada indicador o que ele deixa de fora:

- **Cobertura das filiais:** os dados cobrem a matriz e as 7 filiais do `config.toml`. A lista de filiais foi montada a partir dos contratos da matriz e pode estar incompleta (decisão 12 da ingestão). As filiais publicaram compras só em 2024 (467) e 2025 (182).
- **Valor estimado zero:** 578 compras têm estimado zero. Elas contam como compra, mas ficam fora do ticket médio, do desconto e da faixa de valor (têm a própria faixa).
- **Homologado nulo ou zero:** compra sem resultado homologado fica fora da soma do homologado e do desconto, e homologado nulo não é zero. Homologado zero entra na soma (não muda o total), mas fica fora do desconto.
- **`ligacao_compra`:** "nenhum contrato ligado" olha só os contratos com `compra_encontrada`. Os 164 contratos sem compra encontrada entram nos marts de contratos e de fornecedores, mas não ligam nenhuma compra.
- **Mês corrente:** o mês da data de referência está incompleto (`mes_completo` falso) e não deve ser comparado com os outros.
- **Anomalias:** os marts não excluem registros com anomalia. Por exemplo, as 18 compras de `homologado_acima_estimado` entram no desconto com valor negativo. A tabela `refined.anomalias` permite filtrá-las.
- **Vigência sem fim:** 21 contratos não têm data de fim e nunca aparecem como contrato a vencer.
- **Provável, não certo:** "compra provavelmente sem resultado" é inferida; o PNCP não informa se a compra foi deserta ou fracassada.
- **Segmento:** heurístico (decisão 4).

## Como rodar

```bash
uv run python -m pipeline                    # ingestão, transformação e marts, cada etapa só se a anterior der certo
uv run python -m pipeline.marts              # só os marts, sobre a refined atual
```

Os marts sozinhos seguem a mesma pré-condição: recusam rodar se a última transformação não terminou com sucesso.

## Definição de pronto

- [ ] `python -m pipeline` roda ingestão, transformação e marts, e cada etapa não roda se a anterior falhar.
- [ ] Os marts recusam rodar quando a última transformação falhou.
- [ ] Cada mart tem um arquivo em `sql/marts/`, com o grão escrito no topo.
- [ ] As três conferências da decisão 2 passam sobre a refined real.
- [ ] Uma falha no meio deixa os marts anteriores intactos e fica registrada em `marts.execucoes`.
- [ ] Rodar duas vezes sobre a mesma refined gera tabelas idênticas.
- [ ] Nenhum mart expõe `ni_fornecedor`, nem nome ou objeto de contrato de pessoa física ou de empresário individual.
- [ ] A contagem por segmento e uma amostra de objetos de `dados` e de `ti` foram revisadas, e a lista de termos foi ajustada se preciso.
- [ ] Os testes cobrem cada mart com dados falsos, num DuckDB em memória, sem internet e sem abrir o banco do projeto.
- [ ] O README descreve a camada de marts, as perguntas que cada mart responde, os próximos passos e o tempo medido.

## Próximos passos

- **Modelo estrela** (fatos e dimensões), adiado na decisão 1.
- **Recorrência de compras por unidade:** que objetos cada unidade compra todo ano, para antecipar a próxima compra.
- **Atas e adesões:** atas de registro de preço e compras feitas por adesão, fora do escopo da ingestão.
- **Painel** (etapa 4), com as notas de leitura acima.

## Fora de escopo

- Os itens dos próximos passos.
- Corrigir ou excluir registros com anomalia.
- Classificar outros segmentos além de TI e dados.
- Indicadores por fornecedor pessoa física ou empresário individual individualizado.
