# Spec da etapa 2: Transformação

## Objetivo

Transformar a camada bruta (`raw`) na camada refinada (`refined`) do DuckDB: uma linha por contratação e por contrato, na versão vigente, com colunas tipadas e nomes padronizados, vazios normalizados, CPF de pessoa física mascarado, anomalias sinalizadas sem correção e cada contrato ligado à sua compra. A camada refinada é recriada inteira a cada execução, e só depois de uma ingestão que terminou com sucesso para todos os CNPJs.

## Fonte

As tabelas `raw.contratacoes`, `raw.contratos` e `raw.execucoes`, descritas em [specs/ingestao.md](ingestao.md). As decisões abaixo se apoiam na investigação da camada bruta, em [docs/investigacao-transformacao.md](../docs/investigacao-transformacao.md), e na atualização dela depois da inclusão das filiais.

Volume de referência (raw de 10/11/2026, dados até 09/11/2026):

| Tabela | Linhas | Registros | Com mais de uma versão |
| --- | --- | --- | --- |
| `raw.contratacoes` | 13.696 | 13.677 | 19 |
| `raw.contratos` | 6.797 | 6.786 | 11 |

O banco inteiro tem 22 MB.

## Decisões

### 1. Versão vigente: a de maior data de atualização, olhando as duas datas

A versão vigente de cada registro (mesmo `numeroControlePNCP`) é a de maior valor entre `dataAtualizacaoGlobal` e `dataAtualizacao`. Em caso de empate, vale a versão com o `_extraido_em` mais recente. Se ainda houver empate, a transformação falha, porque não há critério para escolher.

**Motivo:** em 133 contratações da investigação (155 na raw de 10/11/2026), a `dataAtualizacaoGlobal` é anterior à `dataAtualizacao`. A regra usada na investigação, só pela `dataAtualizacaoGlobal`, poderia escolher uma versão mais antiga nesses casos quando houver várias versões. Em contratos, a global é sempre maior ou igual, e as duas regras coincidem.

**Custo da decisão:** uma comparação a mais por versão. Hoje a escolha não muda nada: nos 30 registros com duas versões, as duas regras escolhem a mesma, sem empate de data.

### 2. Tabelas: uma por entidade, sem modelo estrela

| Tabela | Uma linha por | Chave |
| --- | --- | --- |
| `refined.contratacoes` | contratação | `numero_controle_pncp` |
| `refined.contratos` | contrato | `numero_controle_pncp` |
| `refined.contratacoes_fontes` | contratação e fonte orçamentária | `numero_controle_pncp`, `ordem` |

Mais duas tabelas de apoio: `refined.anomalias` (decisão 7) e `refined.execucoes` (decisão 10).

`refined.contratacoes_fontes` recebe os elementos da lista `fontesOrcamentarias`, na ordem da lista (`ordem` começa em 1). Compra com a lista vazia não tem linha nessa tabela.

**Motivo:** a lista de fontes vem da API como lista. Hoje ela nunca tem mais de um elemento (1.434 compras com a lista preenchida na versão vigente da raw de 10/11/2026), mas nada na API garante isso. Uma tabela própria aceita mais de um item sem mudar a estrutura, e as colunas simples que a investigação sugeriu quebrariam no primeiro caso com duas fontes.

**Alternativas consideradas:** montar o modelo estrela (fatos e dimensões) já na refined. Foi descartado porque montar as dimensões exige decisões que dependem das perguntas dos marts: qual nome vale quando o nome de uma unidade ou de um fornecedor muda, e se a dimensão guarda histórico. O modelo estrela fica como requisito da etapa 3.

**Custo da decisão:** os marts terão de montar as dimensões a partir das colunas repetidas (unidade, órgão, fornecedor, modalidade) nas tabelas da refined.

### 3. Colunas: tudo o que tem dado, com nomes mecânicos

**Colunas descartadas:** os 7 campos 100% vazios na raw inteira não vão para a refined. Nenhum registro os preenche, então o vazio significa "não informado", sem como distinguir de "não existe".

| Tabela | Campo | O que o vazio indica |
| --- | --- | --- |
| contratações | `orgaoSubRogado` | Nenhuma compra informou sub-rogação para outro órgão. |
| contratações | `unidadeSubRogada` | Nenhuma compra informou sub-rogação para outra unidade. |
| contratos | `identificadorCipi` | Nenhum contrato informou vínculo com projeto de investimento do Cadastro Integrado de Projetos de Investimento (CIPI). |
| contratos | `urlCipi` | Idem, o endereço do projeto no CIPI. |
| contratos | `niFornecedorSubContratado` | Nenhum contrato informou fornecedor subcontratado. |
| contratos | `nomeFornecedorSubContratado` | Idem, o nome do subcontratado. |
| contratos | `tipoPessoaSubContratada` | Idem, o tipo de pessoa do subcontratado. |

Em contratos, `orgaoSubRogado` e `unidadeSubRogada` têm dado (5 e 4 registros) e vão para a refined.

**Nomes:** cada campo do JSON vira uma coluna, com o nome convertido mecanicamente de camelCase para snake_case (`numeroControlePNCP` vira `numero_controle_pncp`). Campos de blocos aninhados ganham o prefixo do bloco:

| Bloco no JSON | Prefixo |
| --- | --- |
| `orgaoEntidade` | `orgao_` |
| `unidadeOrgao` | `unidade_` |
| `amparoLegal` | `amparo_legal_` |
| `categoriaProcesso` | `categoria_processo_` |
| `tipoContrato` | `tipo_contrato_` |
| `orgaoSubRogado` | `orgao_sub_rogado_` |
| `unidadeSubRogada` | `unidade_sub_rogada_` |
| `fontesOrcamentarias[]` | `fonte_` |

A conversão não encurta nomes nem tira redundâncias (`unidadeOrgao.nomeUnidade` vira `unidade_nome_unidade`). As tabelas completas de/para estão em "Estrutura da camada refinada".

**Motivo:** a regra mecânica dispensa decidir nome a nome e permite achar a origem de cada coluna sem consultar a spec. Os prefixos evitam colisão, porque o órgão e a unidade se repetem em vários blocos (`orgaoEntidade.cnpj` e `orgaoSubRogado.cnpj`).

**Custo da decisão:** alguns nomes ficam longos ou redundantes. Se um campo descartado passar a ter dado, ele não aparece na refined até a spec ser atualizada; o contrato de dados (decisão 9) avisa quando isso acontecer.

### 4. Tipos: decimal exato para dinheiro, sem fuso nas datas, identificadores como texto

| Conteúdo | Tipo |
| --- | --- |
| Dinheiro | `DECIMAL(18,2)`, exceto `valor_parcela`, que é `DECIMAL(18,4)` |
| Data com hora | `TIMESTAMP` (sem fuso) |
| Data sem hora | `DATE` |
| Identificadores: CNPJ, CPF, processo, números de compra e de contrato, números de controle do PNCP, códigos de unidade e do IBGE | `VARCHAR` |
| Códigos de domínio numéricos (modalidade, situação, amparo legal etc.) e anos | `INTEGER` |
| Sequenciais, número de parcelas e número de retificações | `INTEGER` |
| Booleanos | `BOOLEAN`, mantendo o nulo |
| Demais textos, inclusive códigos em letras (`orgao_esfera_id`, `orgao_poder_id`, `tipo_pessoa`, `codigo_pais_fornecedor`) | `VARCHAR` |

**Dinheiro:** o valor é convertido a partir do texto do número no JSON, sem passar por ponto flutuante. A transformação falha, com mensagem dizendo tabela, chave e campo, se um valor não couber no tipo: mais dígitos na parte inteira do que o tipo aceita (16 em `DECIMAL(18,2)`, ou 14 em `DECIMAL(18,4)`, no `valor_parcela`) ou mais casas decimais do que o tipo aceita (2, ou 4 em `valor_parcela`). Zeros à direita nas casas decimais não contam (`1.230` cabe em `DECIMAL(18,2)`), porque nada é arredondado. Nenhum valor é arredondado em silêncio. Hoje o maior valor tem 11 dígitos na parte inteira, e só `valorParcela` tem 3 ou 4 casas.

**Datas:** os formatos são `AAAA-MM-DDTHH:MM:SS` e `AAAA-MM-DD`, uniformes na raw inteira. Um valor fora do formato faz a transformação falhar.

**Premissa do fuso:** as datas com hora da API não trazem fuso, e a refined as guarda como vieram. A premissa é que estão no horário de Brasília. Isso não foi verificado; se a premissa estiver errada, só análises por hora do dia são afetadas.

**Booleanos:** nulo continua nulo (decisão 5); nunca vira `false`.

**Motivo:** dinheiro em ponto flutuante acumula erros de arredondamento nas somas, e a conferência da decisão 10 compara somas exatas. Identificadores como texto preservam zeros à esquerda (CNPJ, código IBGE) e não convidam a fazer conta com eles.

**Alternativas consideradas:** `DOUBLE` para dinheiro. Foi descartado porque guarda os valores de forma aproximada.

**Custo da decisão:**

- A conversão do dinheiro precisa ler o número como texto, o que exige cuidado na implementação (o leitor de JSON padrão converte números para ponto flutuante).
- O texto de `registro` na raw foi reserializado a partir de ponto flutuante na ingestão: `1234.50` aparece como `1234.5`. Isso preserva o valor exato até 15 dígitos significativos, e hoje o máximo é 15 (11 na parte inteira e 4 casas). Se aparecer um valor com mais de 15 dígitos significativos, a conversão deve passar a ler o literal do número na landing, que guarda a resposta original da API.

### 5. Vazios: texto aparado, vazio vira nulo, nulo nunca é preenchido

- Todo texto tem os espaços das pontas removidos, inclusive identificadores e nomes.
- Texto vazio, ou só com espaços, vira nulo.
- Nenhum nulo é preenchido com valor inventado: nem zero, nem `false`, nem texto padrão, nem data padrão.

**Motivo:** texto vazio e nulo coexistem no mesmo campo (por exemplo, 3.759 textos vazios e 909 nulos em `contratos.informacaoComplementar`) e significam a mesma coisa. Os nulos parciais têm significado, e preenchê-los apagaria esse significado (por exemplo, homologado nulo é compra sem resultado, e homologado zero existe e é outra coisa).

**Espaços nas pontas reclassificados:** os espaços no número do processo, listados como anomalia nos requisitos da spec da ingestão, foram reclassificados como formatação. A transformação os remove, sem registrar anomalia. O mesmo vale para os espaços em `objetoCompra`, `informacaoComplementar` e `nomeRazaoSocialFornecedor`.

**Significado dos nulos parciais** (item 2 da investigação):

| Coluna | Nulo significa |
| --- | --- |
| `contratacoes.valor_total_homologado` | Compra sem resultado homologado: suspensa, revogada, anulada, publicada há pouco tempo ou provavelmente deserta ou fracassada. Homologado zero existe e é diferente de nulo. |
| `contratacoes.data_abertura_proposta`, `data_encerramento_proposta` | Contratação direta sem disputa (instrumento "Ato que autoriza a Contratação Direta"). As duas são nulas sempre juntas, e só nesses casos. |
| `contratacoes.justificativa_presencial` | Compra não presencial. Só é preenchida nas compras presenciais. |
| `contratacoes.link_processo_eletronico` | Não informado. O campo passou a ser preenchido em 2026. |
| `contratacoes.link_sistema_origem` | Compra sem sistema de origem informado: as do Contrata+Brasil e, desde 2024, quase todas as inexigibilidades e dispensas. |
| `contratacoes.informacao_complementar`, `contratos.informacao_complementar` | Sem informação complementar (inclui o texto vazio original). |
| `contratacoes.emenda_parlamentar`, `contratos.emenda_parlamentar` | Não informado. Campo novo no PNCP (agosto de 2026) e opcional mesmo nos registros novos. Não significa `false`. |
| `contratos.tem_remanejamento`, `fruto_adesao` | Não informado. Campos novos no PNCP (maio de 2026), nulos sempre juntos. Não significam `false`. |
| `contratos.data_vigencia_fim` | Vigência sem data de fim (prazo indeterminado, como no fornecimento de energia elétrica). Não é dado faltando. |
| `contratos.valor_acumulado` | Não informado. Só existe em empenhos de 2023 e do início de 2024. |
| `contratos.numero_controle_pncp_ata` | Contrato que não vem de ata de registro de preços. |
| `contratos.codigo_pais_fornecedor` | Não informado, sem relação com o tipo de pessoa. O único valor preenchido é `BRA`. |
| `contratos.orgao_sub_rogado_*`, `unidade_sub_rogada_*` | Contrato sem sub-rogação. |
| `contratos.nome_razao_social_fornecedor` | Nome não informado (texto vazio na origem, 7 contratos de pessoa jurídica). Registrado como anomalia (decisão 7). |
| Linha ausente em `contratacoes_fontes` | Compra sem fonte orçamentária informada (lista vazia). O campo só passou a ser informado em junho de 2026. |

**Custo da decisão:** a refined não distingue texto vazio de nulo na origem. A distinção continua na raw.

### 6. Dados pessoais: CPF mascarado, nome mantido, painel sempre agregado

- **CPF em `ni_fornecedor`:** nos contratos com `tipo_pessoa = 'PF'`, o CPF é mascarado no padrão usado pelo governo nos portais de transparência, que mostra só os 6 dígitos do meio: `***.456.789-**`. Se um contrato de pessoa física tiver em `ni_fornecedor` algo que não sejam 11 dígitos, a transformação falha, porque não há como mascarar com segurança.
- **CPF em texto livre:** nas colunas de texto livre (`objeto_compra`, `objeto_contrato`, `informacao_complementar` e `justificativa_presencial`) de todos os registros, qualquer CPF é mascarado no mesmo padrão. Conta como CPF o formatado (`000.000.000-00`) e a sequência de 11 dígitos com dígito verificador válido que não faça parte de uma sequência maior de dígitos.
- **Nome:** `nome_razao_social_fornecedor` é mantido como veio, inclusive o de pessoa física.

**Motivo:** 25 contratos têm fornecedor pessoa física, com CPF completo e válido em `niFornecedor`, e um deles repete o CPF no texto livre. A máscara protege o CPF e, junto com o nome, ainda distingue um fornecedor do outro. O CPF completo fica só na raw, que está fora do repositório (`*.duckdb` no `.gitignore`).

**Requisito para o painel (etapa 4):** fornecedor pessoa física aparece sempre agregado, nunca individualizado, e o texto livre dos contratos de pessoa física não é exibido.

**Alternativas consideradas:**

- **Hash simples do CPF:** é reversível na prática, porque o CPF tem cerca de 1 bilhão de combinações e dá para calcular o hash de todas.
- **Hash com chave secreta:** resolveria a reversão, mas é desproporcional para 25 contratos e exigiria guardar e proteger a chave.
- **Remoção do CPF:** perderia a distinção entre fornecedores pessoa física com o mesmo nome.

**Custo da decisão:**

- A refined continua tendo dado pessoal (o nome e 6 dígitos do CPF), por isso o requisito do painel.
- A refined não pode ser cruzada com fontes externas pelo CPF.
- A busca por padrões não encontra nomes de pessoas em texto livre. Esse risco continua existindo e é coberto só pela regra do painel.
- Uma sequência de 11 dígitos com dígito verificador válido que não seja CPF também é mascarada.

### 7. Anomalias: registradas numa tabela, nunca corrigidas

Cada ocorrência de uma regra vira uma linha em `refined.anomalias`, com a tabela, a chave do registro, o nome da regra e uma descrição com os valores envolvidos (por exemplo, "publicado em 2025-03-01, assinado em 2025-03-10"). O registro continua na refined, sem nenhuma correção. Anomalia nunca derruba a execução. O log mostra a contagem por regra.

**Regras registradas** (ocorrências na versão vigente da raw de 10/11/2026):

| Regra | Tabela | Condição | Ocorrências | Motivo |
| --- | --- | --- | --- | --- |
| `publicado_antes_assinatura` | contratos | dia de `data_publicacao_pncp` anterior a `data_assinatura` | 533 | A data de assinatura atual é posterior à data de publicação original, provavelmente alterada por retificação depois da publicação. Evidência abaixo. |
| `assinado_antes_compra_com_disputa` | contratos | `data_assinatura` anterior ao dia da publicação da compra ligada, quando a compra tem disputa (`data_abertura_proposta` preenchida) | 10 | Numa compra com disputa, o contrato vem do resultado, que só existe depois de a compra ser publicada. |
| `compra_de_ano_posterior` | contratos | ano da compra em `numero_controle_pncp_compra` maior que o ano de `data_assinatura` | 29 (9 apontam para compras de 2027; 12 apontam para compras que também caem em `ano_compra_futuro`) | O contrato não pode vir de uma compra numerada num ano posterior ao da assinatura. A comparação é com a assinatura, e não com `ano_contrato`, que é numeração. |
| `compra_fab_nao_encontrada` | contratos | `ligacao_compra = 'compra_fab_nao_encontrada'` (decisão 8) | 0 | Contrato que aponta para uma compra da FAB do período que a ingestão não trouxe. |
| `vigencia_fim_antes_inicio` | contratos | `data_vigencia_fim` anterior a `data_vigencia_inicio` | 0 | Datas impossíveis. |
| `vigencia_inicio_antes_assinatura` | contratos | `data_vigencia_inicio` mais de 30 dias antes de `data_assinatura` | 0 | O contrato não produz efeito muito antes de existir; os 30 dias toleram assinatura registrada com atraso. |
| `fornecedor_sem_nome` | contratos | `nome_razao_social_fornecedor` nulo depois da decisão 5 | 7 | Todo contrato tem um fornecedor identificado; o nome faltando é dado incompleto. |
| `ano_compra_futuro` | contratações | `ano_compra` maior que o ano de `data_publicacao_pncp`, com publicação de janeiro a agosto | 23 (11 de 2027) | A compra foi numerada com o ano seguinte longe do período de planejamento do exercício seguinte; provável erro no ano informado por quem cadastrou. Evidência abaixo. |
| `homologado_acima_estimado` | contratações | `valor_total_homologado` maior que `valor_total_estimado`, com estimado maior que zero, fora do credenciamento | 18 | Numa disputa, a proposta acima do orçamento estimado pode ser desclassificada (Lei 14.133/2021, art. 59); homologar acima dele é incomum. |
| `abertura_antes_publicacao` | contratações | dia de `data_abertura_proposta` anterior ao dia de `data_publicacao_pncp` | 4 | As propostas não podem abrir antes de a compra ser publicada. |
| `encerramento_antes_abertura` | contratações | `data_encerramento_proposta` anterior a `data_abertura_proposta` | 0 | Datas impossíveis. |

**Evidência sobre `publicado_antes_assinatura`** (versão vigente da raw de 10/11/2026):

- Os 533 contratos têm `numero_retificacao` maior que zero (100%), com mediana de 2 retificações e máximo de 18. Nos 6.786 contratos, a taxa de retificação é de 37,4%; nos demais 6.253, de 32,1%.
- Dias entre a publicação e a assinatura: mínimo 1, primeiro quartil 12, mediana 33, terceiro quartil 71, percentil 90 de 133 e máximo 400.

| Dias entre publicação e assinatura | Contratos |
| --- | --- |
| 1 a 7 | 84 |
| 8 a 30 | 173 |
| 31 a 90 | 178 |
| 91 a 365 | 93 |
| Mais de 365 | 5 |

- Nenhum contrato sem retificação tem a publicação antes da assinatura. Isso confirma, na raw inteira, o padrão visto na amostra da exploração (74 casos, todos retificados, mediana de 26 dias): a data de assinatura atual veio de uma retificação, e a data de publicação é a da publicação original. A regra continua registrada para sinalizar a inconsistência entre as duas datas, não uma irregularidade.

**Evidência sobre `ano_compra_futuro`** (125 compras com o ano seguinte na versão vigente da raw de 10/11/2026, antes do corte por mês). A hipótese inicial era erro de digitação do ano, e não planejamento para o exercício seguinte, que se concentraria no fim do ano. A distribuição confirma o planejamento para a maioria dos casos:

| Mês de publicação | Compras | % das 125 | % das publicações do mês |
| --- | --- | --- | --- |
| Janeiro a agosto | 23 | 18,4 | 0,3 |
| Setembro | 13 | 10,4 | 0,75 |
| Outubro | 15 | 12,0 | 0,9 |
| Novembro | 20 | 16,0 | 1,6 |
| Dezembro | 54 | 43,2 | 6,9 |

| Modalidade | Compras | % da modalidade |
| --- | --- | --- |
| Inexigibilidade | 41 | 1,3 |
| Pregão eletrônico | 39 | 0,6 |
| Dispensa | 34 | 0,9 |
| Credenciamento | 9 | 8,0 |
| Concorrência eletrônica | 2 | 0,8 |

- Novembro e dezembro concentram 74 das 125 compras (59%). Nos anos completos (2024 e 2025), são 64 de 88 (73%). Dezembro de 2026 ainda não aconteceu.
- Em dezembro, 6,9% das compras publicadas têm o ano seguinte; nos outros meses, no máximo 1,6%.
- A diferença é sempre de exatamente um ano.
- Nenhuma modalidade concentra os casos, exceto o credenciamento em proporção (8%, mas só 9 compras).
- Leitura: a maior parte é compatível com planejamento para o exercício seguinte. Segundo o manual de licitações e contratos do TCU (item 4.3.10), o Plano de Contratações Anual subsidia o orçamento das contratações planejadas para o exercício seguinte, e no registro de preços a dotação orçamentária só é indicada na formalização do contrato. No Compras.gov.br, o ano da compra é informado por quem cadastra.
- Corte: a regra registra só as 23 compras publicadas de janeiro a agosto, longe do período de planejamento. As 102 publicadas de setembro a dezembro entram em "Prática normal, não registradas". Setembro é o primeiro mês em que a proporção sobe de forma consistente (0,75%, contra 0,3% de janeiro a agosto).

**Prática normal, não registradas:**

| Situação | Ocorrências | Motivo |
| --- | --- | --- |
| `ano_compra` anterior ao ano de publicação | 664 | O processo começa num ano e a compra é publicada no seguinte. |
| `ano_compra` posterior ao ano de publicação, com publicação de setembro a dezembro | 102 | Planejamento para o exercício seguinte: o Plano de Contratações Anual subsidia o orçamento das contratações do exercício seguinte, e no registro de preços a dotação só é indicada na formalização do contrato (manual de licitações e contratos do TCU, item 4.3.10). |
| `ano_contrato` diferente do ano da assinatura | 472 (465 com um ano a menos) | `ano_contrato` faz parte da numeração do contrato, não é data. |
| Homologado acima do estimado no credenciamento | 28 | No credenciamento, o valor depende da demanda, e o estimado não é teto de disputa. |
| Homologado positivo com estimado zero | 76 | Consequência do estimado zero, tratado abaixo. |
| Compra revogada ou anulada com homologado positivo | 72 | A revogação ou a anulação pode vir depois da homologação; o homologado guarda o resultado anterior. |
| Contrato com `valor_global` zero | 158 | Concentrado em contratos de inexigibilidade e de cessão, comodato e arrendamento, compatível com contratos sem valor definido na assinatura. |
| `valor_global` menor que `valor_inicial` | 3 | Supressão por termo aditivo. |
| `valor_parcela` vezes `numero_parcelas` diferente de `valor_global` em mais de 1% | 91 | Parcelas desiguais e termos aditivos. |
| Assinatura antes de 2023 | 30 | O período da ingestão é pela data de publicação; contrato antigo publicado depois entra. |
| Vigência de mais de 10 anos | 10 | A Lei 14.133/2021 admite prazos maiores em alguns contratos (art. 110) e prazo indeterminado em outros (art. 109). |
| Contrato retificado (`numero_retificacao` maior que zero) | 2.540 | A retificação é o caminho normal de correção no PNCP. |
| Espaços nas pontas dos textos | milhares | Formatação, removida pela decisão 5. |
| Contrato sem compra encontrada | 164 | Tratado pela coluna `ligacao_compra` (decisão 8). |

**Valor estimado zero não é erro:** 578 compras (548 na investigação) têm `valor_total_estimado` zero. A compra continua contando como oportunidade, mas fica fora dos cálculos de valor e de economia. A hipótese de orçamento sigiloso foi testada e não se confirmou na maioria dos casos: quase todas as compras revogadas e anuladas têm estimado zero, os pregões divulgados com estimado zero quase nunca têm resultado nem contrato, e nenhuma das compras cita sigilo. O padrão é mais compatível com valor zerado na revogação ou anulação, com compras sem resultado e, nas inexigibilidades e credenciamentos, com valor que não se conhece de antemão.

**Motivo:** anomalia é informação sobre a qualidade do dado publicado, não defeito do pipeline. Corrigir apagaria o que a fonte publicou, e derrubar a execução impediria atualizar a refined por causa de um erro de terceiros. A lista separa o que indica dado inconsistente do que é prática administrativa normal, para a tabela não virar ruído.

**Custo da decisão:** as regras e os limites (30 dias, credenciamento fora da regra do homologado) são escolhas que podem precisar de revisão quando os marts usarem a tabela.

### 8. Ligação de cada contrato com a compra

`refined.contratos` tem a coluna `ligacao_compra`, que classifica a relação entre o contrato e a compra de `numero_controle_pncp_compra`:

| Valor | Condição | Contratos (raw de 10/11/2026) |
| --- | --- | --- |
| `compra_encontrada` | A compra está em `refined.contratacoes`. | 6.622 |
| `compra_fab_anterior_ao_periodo` | A compra não está na refined, o CNPJ da referência está na lista do `config.toml` e o ano da compra é anterior ao ano da data inicial. | 140 |
| `compra_filial_fora_da_lista` | O CNPJ da referência tem a raiz (8 primeiros dígitos) da matriz, mas não está na lista. | 0 |
| `compra_outro_orgao` | O CNPJ da referência tem outra raiz. | 24 |
| `compra_fab_nao_encontrada` | A compra não está na refined, o CNPJ da referência está na lista e o ano da compra é igual ou posterior ao ano da data inicial. | 0 |

O CNPJ e o ano saem do próprio `numero_controle_pncp_compra` (formato `<cnpj>-1-<sequencial>/<ano>`). Nenhum contrato é descartado. Uma referência fora desse formato faz a transformação falhar.

**Compra da FAB não encontrada:** o contrato recebe `compra_fab_nao_encontrada`, ganha uma anomalia com a regra de mesmo nome (decisão 7), e o log mostra um aviso com a quantidade. A execução não para.

**Motivo:** contrato sem compra não é erro de ingestão por si só, mas os cinco casos têm leituras diferentes:

- compra anterior ao período: limite conhecido do recorte;
- compra de filial fora da lista: indica que a lista de filiais está incompleta (decisão 12 da ingestão);
- compra de outro órgão: contrato da FAB sobre compra alheia (adesão ou compra compartilhada);
- compra da FAB não encontrada: indica uma lacuna na cobertura da ingestão, ou uma compra numerada no ano da data inicial mas publicada antes dela. Isso merece atenção, mas não justifica parar a transformação: a refined continua correta para os demais contratos, e a lacuna fica visível na anomalia e no aviso.

Descartar esses contratos tiraria da análise 164 contratos que existem.

**Custo da decisão:** a classificação depende da lista de CNPJs e da data inicial do `config.toml`. Uma lacuna da ingestão não interrompe nada; ela só aparece se alguém olhar o aviso ou a tabela de anomalias.

### 9. Contrato de dados: aviso para o que é novo, falha para o que some

Os campos conhecidos são os da tabela de/para mais os 7 campos descartados (decisão 3); um campo fora desse conjunto é novo. Dentro dele, só os campos da tabela de/para são obrigatórios: a ausência de um deles faz a transformação falhar, e a de um descartado gera só um aviso.

| Situação | Onde se olha | Resultado |
| --- | --- | --- |
| Campo novo, fora dos campos conhecidos | Todos os registros da raw | Aviso no log, com o caminho do campo e quantos registros o têm. |
| Campo descartado (decisão 3) que passa a ter dado | Todos os registros da raw | Aviso no log, com o campo e quantos registros o preenchem. |
| Campo da tabela de/para que some | Registros extraídos pela última rodada de ingestão | A transformação falha, com o campo e quantos registros não o têm. |
| Campo descartado que some | Registros extraídos pela última rodada de ingestão | Aviso no log, com o campo e quantos registros não o têm. Os descartados não vão para a refined, então a ausência não pode virar nulo silencioso. |

**Campo que some:** é a chave ausente no JSON, não a chave presente com valor nulo. Na raw de 10/11/2026, todas as chaves de primeiro nível aparecem em todos os registros, com nulo explícito quando não há valor. As chaves dos blocos obrigatórios (`orgaoEntidade`, `unidadeOrgao`, `amparoLegal`, `categoriaProcesso`, `tipoContrato`) são conferidas em todos os registros; as dos blocos opcionais (`orgaoSubRogado` e `unidadeSubRogada` em contratos) e dos elementos de `fontesOrcamentarias`, só quando o bloco ou o elemento existe. Se a última rodada não trouxe nenhum registro, a conferência não se aplica, e o log diz isso.

**Motivo:** um campo novo não quebra nada, porque a raw o guarda e a refined o ignora; o aviso serve para decidir se ele deve entrar. Um campo que some viraria nulo em silêncio na refined, e nulo tem significado (decisão 5). A conferência olha só a última rodada porque os registros antigos mantêm o formato antigo; uma mudança na API aparece nos registros novos.

**Custo da decisão:** os avisos se repetem a cada execução até a spec ser atualizada. Uma mudança na API pode parar a transformação; nesse caso, a refined anterior continua intacta (decisão 10).

### 10. Reexecução: refined recriada inteira, só depois de ingestão com sucesso

- **Recriação inteira:** a cada execução, as tabelas da refined são recriadas do zero a partir da raw, numa única transação. Se algo falhar no meio, a refined anterior fica intacta. A exceção é `refined.execucoes`, que acumula o histórico.
- **Pré-condição:** a transformação se recusa a rodar se a última rodada de ingestão (o `rodada_id` mais recente em `raw.execucoes`) não terminou com `status = sucesso` para todos os CNPJs do `config.toml`. Uma rodada que parou no meio deixa CNPJs sem linha, e isso também conta como falha. A reconstrução (`--reconstruir`) é uma rodada como as outras.
- **Comando único:** `python -m pipeline` roda a ingestão e, só se ela terminar com sucesso, a transformação. Aceita os mesmos parâmetros da ingestão.

**Conferências que fazem a transformação falhar:**

1. **Linhas:** `refined.contratacoes` e `refined.contratos` têm tantas linhas quanto registros distintos (`numeroControlePNCP`) na tabela da raw correspondente; `refined.contratacoes_fontes` tem tantas linhas quanto elementos de `fontesOrcamentarias` nas versões vigentes.
2. **Chave única** em cada tabela.
3. **Somas:** para cada coluna de dinheiro, a soma na refined é igual à soma calculada direto do texto do JSON das versões vigentes, como decimal exato.
4. **Ligação:** `ligacao_compra` preenchida em todos os contratos.

**Registro:** cada execução ganha uma linha em `refined.execucoes`, gravada fora da transação principal: uma linha ao começar, com `status = falha`, que é atualizada ao terminar. Assim uma execução que falha fica registrada mesmo com a transação desfeita.

**Motivo:** a transformação é barata, e recriar tudo garante que a refined é sempre função da raw atual, sem estado acumulado para corrigir. A pré-condição impede misturar dados de CNPJs atualizados com os de CNPJs que ficaram para trás, e o painel nunca mostra dado pela metade.

**Alternativas consideradas:** processar só os registros com versão nova desde a última transformação. Foi descartado pela complexidade (controlar o que já foi processado, remover anomalias e ligações que mudaram, refazer a ligação dos contratos quando chega uma compra nova), desproporcional ao volume atual: 13.696 linhas de contratações e 6.797 de contratos, num banco de 22 MB. Uma passada de teste que escolhe a versão vigente e converte os tipos principais das duas tabelas levou 1,3 segundo.

**Custo da decisão:** o tempo da transformação cresce com a raw inteira, não com o volume de cada incremental. Com o volume atual, segundos. `refined.execucoes` não tem espelho na landing: apagar o banco perde esse histórico, mas não a refined, que é recriada a partir da raw.

## Estrutura da camada refinada

Schema `refined` no arquivo `compras_fab.duckdb`. Nas três tabelas principais, as colunas `_hash`, `_extraido_em` e `_execucao_id` vêm da linha da raw escolhida como versão vigente e permitem voltar a ela.

**`refined.contratacoes`** (uma linha por contratação)

| Campo no JSON | Coluna | Tipo |
| --- | --- | --- |
| `numeroControlePNCP` | `numero_controle_pncp` | `VARCHAR` (chave) |
| `numeroCompra` | `numero_compra` | `VARCHAR` |
| `anoCompra` | `ano_compra` | `INTEGER` |
| `sequencialCompra` | `sequencial_compra` | `INTEGER` |
| `processo` | `processo` | `VARCHAR` |
| `objetoCompra` | `objeto_compra` | `VARCHAR` (CPF mascarado) |
| `informacaoComplementar` | `informacao_complementar` | `VARCHAR` (CPF mascarado) |
| `justificativaPresencial` | `justificativa_presencial` | `VARCHAR` (CPF mascarado) |
| `modalidadeId` | `modalidade_id` | `INTEGER` |
| `modalidadeNome` | `modalidade_nome` | `VARCHAR` |
| `modoDisputaId` | `modo_disputa_id` | `INTEGER` |
| `modoDisputaNome` | `modo_disputa_nome` | `VARCHAR` |
| `tipoInstrumentoConvocatorioCodigo` | `tipo_instrumento_convocatorio_codigo` | `INTEGER` |
| `tipoInstrumentoConvocatorioNome` | `tipo_instrumento_convocatorio_nome` | `VARCHAR` |
| `situacaoCompraId` | `situacao_compra_id` | `INTEGER` |
| `situacaoCompraNome` | `situacao_compra_nome` | `VARCHAR` |
| `srp` | `srp` | `BOOLEAN` |
| `emendaParlamentar` | `emenda_parlamentar` | `BOOLEAN` |
| `amparoLegal.codigo` | `amparo_legal_codigo` | `INTEGER` |
| `amparoLegal.nome` | `amparo_legal_nome` | `VARCHAR` |
| `amparoLegal.descricao` | `amparo_legal_descricao` | `VARCHAR` |
| `valorTotalEstimado` | `valor_total_estimado` | `DECIMAL(18,2)` |
| `valorTotalHomologado` | `valor_total_homologado` | `DECIMAL(18,2)` |
| `dataInclusao` | `data_inclusao` | `TIMESTAMP` |
| `dataPublicacaoPncp` | `data_publicacao_pncp` | `TIMESTAMP` |
| `dataAtualizacao` | `data_atualizacao` | `TIMESTAMP` |
| `dataAtualizacaoGlobal` | `data_atualizacao_global` | `TIMESTAMP` |
| `dataAberturaProposta` | `data_abertura_proposta` | `TIMESTAMP` |
| `dataEncerramentoProposta` | `data_encerramento_proposta` | `TIMESTAMP` |
| `linkSistemaOrigem` | `link_sistema_origem` | `VARCHAR` |
| `linkProcessoEletronico` | `link_processo_eletronico` | `VARCHAR` |
| `usuarioNome` | `usuario_nome` | `VARCHAR` |
| `orgaoEntidade.cnpj` | `orgao_cnpj` | `VARCHAR` |
| `orgaoEntidade.razaoSocial` | `orgao_razao_social` | `VARCHAR` |
| `orgaoEntidade.esferaId` | `orgao_esfera_id` | `VARCHAR` |
| `orgaoEntidade.poderId` | `orgao_poder_id` | `VARCHAR` |
| `unidadeOrgao.codigoUnidade` | `unidade_codigo_unidade` | `VARCHAR` |
| `unidadeOrgao.nomeUnidade` | `unidade_nome_unidade` | `VARCHAR` |
| `unidadeOrgao.codigoIbge` | `unidade_codigo_ibge` | `VARCHAR` |
| `unidadeOrgao.municipioNome` | `unidade_municipio_nome` | `VARCHAR` |
| `unidadeOrgao.ufSigla` | `unidade_uf_sigla` | `VARCHAR` |
| `unidadeOrgao.ufNome` | `unidade_uf_nome` | `VARCHAR` |
| (raw) `_hash`, `_extraido_em`, `_execucao_id` | `_hash`, `_extraido_em`, `_execucao_id` | `VARCHAR`, `TIMESTAMP`, `VARCHAR` |

`orgao_cnpj` distingue a matriz das filiais. `fontesOrcamentarias` vai para `refined.contratacoes_fontes`.

**`refined.contratacoes_fontes`** (uma linha por contratação e fonte orçamentária)

| Campo no JSON | Coluna | Tipo |
| --- | --- | --- |
| `numeroControlePNCP` (da contratação) | `numero_controle_pncp` | `VARCHAR` (chave, com `ordem`) |
| posição do elemento na lista, a partir de 1 | `ordem` | `INTEGER` (chave, com `numero_controle_pncp`) |
| `fontesOrcamentarias[].codigo` | `fonte_codigo` | `INTEGER` |
| `fontesOrcamentarias[].nome` | `fonte_nome` | `VARCHAR` |
| `fontesOrcamentarias[].descricao` | `fonte_descricao` | `VARCHAR` |
| `fontesOrcamentarias[].dataInclusao` | `fonte_data_inclusao` | `TIMESTAMP` |
| (raw) `_hash`, `_extraido_em`, `_execucao_id` | `_hash`, `_extraido_em`, `_execucao_id` | `VARCHAR`, `TIMESTAMP`, `VARCHAR` |

**`refined.contratos`** (uma linha por contrato)

| Campo no JSON | Coluna | Tipo |
| --- | --- | --- |
| `numeroControlePNCP` | `numero_controle_pncp` | `VARCHAR` (chave) |
| `numeroContratoEmpenho` | `numero_contrato_empenho` | `VARCHAR` |
| `anoContrato` | `ano_contrato` | `INTEGER` |
| `sequencialContrato` | `sequencial_contrato` | `INTEGER` |
| `processo` | `processo` | `VARCHAR` |
| `numeroControlePncpCompra` | `numero_controle_pncp_compra` | `VARCHAR` |
| `numeroControlePncpAta` | `numero_controle_pncp_ata` | `VARCHAR` |
| `objetoContrato` | `objeto_contrato` | `VARCHAR` (CPF mascarado) |
| `informacaoComplementar` | `informacao_complementar` | `VARCHAR` (CPF mascarado) |
| `tipoContrato.id` | `tipo_contrato_id` | `INTEGER` |
| `tipoContrato.nome` | `tipo_contrato_nome` | `VARCHAR` |
| `categoriaProcesso.id` | `categoria_processo_id` | `INTEGER` |
| `categoriaProcesso.nome` | `categoria_processo_nome` | `VARCHAR` |
| `receita` | `receita` | `BOOLEAN` |
| `emendaParlamentar` | `emenda_parlamentar` | `BOOLEAN` |
| `frutoAdesao` | `fruto_adesao` | `BOOLEAN` |
| `temRemanejamento` | `tem_remanejamento` | `BOOLEAN` |
| `tipoPessoa` | `tipo_pessoa` | `VARCHAR` |
| `niFornecedor` | `ni_fornecedor` | `VARCHAR` (CPF mascarado quando `tipo_pessoa = 'PF'`) |
| `nomeRazaoSocialFornecedor` | `nome_razao_social_fornecedor` | `VARCHAR` |
| `codigoPaisFornecedor` | `codigo_pais_fornecedor` | `VARCHAR` |
| `valorInicial` | `valor_inicial` | `DECIMAL(18,2)` |
| `valorGlobal` | `valor_global` | `DECIMAL(18,2)` |
| `valorParcela` | `valor_parcela` | `DECIMAL(18,4)` |
| `valorAcumulado` | `valor_acumulado` | `DECIMAL(18,2)` |
| `numeroParcelas` | `numero_parcelas` | `INTEGER` |
| `numeroRetificacao` | `numero_retificacao` | `INTEGER` |
| `dataAssinatura` | `data_assinatura` | `DATE` |
| `dataVigenciaInicio` | `data_vigencia_inicio` | `DATE` |
| `dataVigenciaFim` | `data_vigencia_fim` | `DATE` |
| `dataPublicacaoPncp` | `data_publicacao_pncp` | `TIMESTAMP` |
| `dataAtualizacao` | `data_atualizacao` | `TIMESTAMP` |
| `dataAtualizacaoGlobal` | `data_atualizacao_global` | `TIMESTAMP` |
| `usuarioNome` | `usuario_nome` | `VARCHAR` |
| `orgaoEntidade.cnpj` | `orgao_cnpj` | `VARCHAR` |
| `orgaoEntidade.razaoSocial` | `orgao_razao_social` | `VARCHAR` |
| `orgaoEntidade.esferaId` | `orgao_esfera_id` | `VARCHAR` |
| `orgaoEntidade.poderId` | `orgao_poder_id` | `VARCHAR` |
| `unidadeOrgao.codigoUnidade` | `unidade_codigo_unidade` | `VARCHAR` |
| `unidadeOrgao.nomeUnidade` | `unidade_nome_unidade` | `VARCHAR` |
| `unidadeOrgao.codigoIbge` | `unidade_codigo_ibge` | `VARCHAR` |
| `unidadeOrgao.municipioNome` | `unidade_municipio_nome` | `VARCHAR` |
| `unidadeOrgao.ufSigla` | `unidade_uf_sigla` | `VARCHAR` |
| `unidadeOrgao.ufNome` | `unidade_uf_nome` | `VARCHAR` |
| `orgaoSubRogado.cnpj` | `orgao_sub_rogado_cnpj` | `VARCHAR` |
| `orgaoSubRogado.razaoSocial` | `orgao_sub_rogado_razao_social` | `VARCHAR` |
| `orgaoSubRogado.esferaId` | `orgao_sub_rogado_esfera_id` | `VARCHAR` |
| `orgaoSubRogado.poderId` | `orgao_sub_rogado_poder_id` | `VARCHAR` |
| `unidadeSubRogada.codigoUnidade` | `unidade_sub_rogada_codigo_unidade` | `VARCHAR` |
| `unidadeSubRogada.nomeUnidade` | `unidade_sub_rogada_nome_unidade` | `VARCHAR` |
| `unidadeSubRogada.codigoIbge` | `unidade_sub_rogada_codigo_ibge` | `VARCHAR` |
| `unidadeSubRogada.municipioNome` | `unidade_sub_rogada_municipio_nome` | `VARCHAR` |
| `unidadeSubRogada.ufSigla` | `unidade_sub_rogada_uf_sigla` | `VARCHAR` |
| `unidadeSubRogada.ufNome` | `unidade_sub_rogada_uf_nome` | `VARCHAR` |
| (calculada, decisão 8) | `ligacao_compra` | `VARCHAR` |
| (raw) `_hash`, `_extraido_em`, `_execucao_id` | `_hash`, `_extraido_em`, `_execucao_id` | `VARCHAR`, `TIMESTAMP`, `VARCHAR` |

**`refined.anomalias`** (uma linha por ocorrência de uma regra da decisão 7)

| Coluna | Conteúdo |
| --- | --- |
| `tabela` | `contratacoes` ou `contratos` |
| `chave` | `numero_controle_pncp` do registro |
| `regra` | nome da regra |
| `descricao` | valores envolvidos, em texto |

**`refined.execucoes`** (uma linha por execução da transformação; não é recriada)

| Coluna | Conteúdo |
| --- | --- |
| `execucao_id` | identificador da execução |
| `rodada_ingestao` | `rodada_id` da rodada de ingestão usada |
| `inicio`, `fim` | data e hora de início e fim |
| `status` | `sucesso` ou `falha` |
| `linhas_contratacoes`, `linhas_contratos`, `linhas_fontes`, `linhas_anomalias` | linhas gravadas em cada tabela |
| `avisos` | número de avisos no log (compra da FAB não encontrada, decisão 8, e contrato de dados, decisão 9) |
| `mensagem_erro` | vazio em caso de sucesso |

## Como rodar

```bash
uv run python -m pipeline                    # ingestão e, se ela terminar com sucesso, transformação
uv run python -m pipeline --ate 2026-10-31   # aceita os mesmos parâmetros da ingestão
uv run python -m pipeline.transformacao      # só a transformação, sobre a raw atual
```

A transformação sozinha segue a mesma pré-condição: recusa rodar se a última rodada de ingestão não terminou com sucesso para todos os CNPJs.

## Definição de pronto

- [ ] `python -m pipeline` roda a ingestão e a transformação, e a transformação não roda se a ingestão falhar.
- [ ] A transformação recusa rodar quando a última rodada de ingestão falhou ou não cobriu todos os CNPJs do `config.toml`.
- [ ] As quatro conferências da decisão 10 passam sobre a raw real.
- [ ] Uma falha no meio da transformação deixa a refined anterior intacta e fica registrada em `refined.execucoes`.
- [ ] Rodar a transformação duas vezes sobre a mesma raw gera tabelas idênticas.
- [ ] Nenhum CPF completo aparece na refined: os 25 contratos de pessoa física têm `ni_fornecedor` mascarado, e o CPF do texto livre também.
- [ ] Um valor com mais casas decimais que o tipo, ou que não caiba nele, faz a transformação falhar, sem arredondar.
- [ ] Nenhum nulo da raw vira zero, `false` ou texto padrão, e nenhum texto vazio chega à refined.
- [ ] `refined.anomalias` tem as regras registradas da decisão 7, e o log mostra a contagem por regra.
- [ ] Todo contrato tem `ligacao_compra` preenchida, e nenhum contrato é descartado.
- [ ] Um contrato que aponta para uma compra da FAB do período ausente da refined recebe `compra_fab_nao_encontrada`, gera anomalia e aviso no log, e a execução termina com sucesso.
- [ ] Um campo novo no JSON gera aviso, e um campo esperado ausente nos registros da última rodada faz a transformação falhar.
- [ ] Os testes unitários cobrem a versão vigente, a conversão de tipos, a normalização dos vazios, o mascaramento, as regras de anomalia, a ligação e o contrato de dados, sem internet e sem abrir o banco do projeto.
- [ ] O README descreve a camada refinada e o tempo medido da transformação.

## Requisitos registrados para as próximas etapas

**Marts (etapa 3):**

- Montar o modelo estrela, decidindo qual nome vale quando o nome de uma unidade ou de um fornecedor muda e se as dimensões guardam histórico.
- Compra com valor estimado zero conta como oportunidade, mas fica fora dos cálculos de valor e de economia.
- Homologado nulo não é zero: compra sem resultado fica fora da economia.
- Filtrar ou separar os contratos por `ligacao_compra` nas métricas que dependem da compra.
- A anomalia `publicado_antes_assinatura` não deve ser lida como irregularidade: ela aparece só em contratos retificados, em que a data de assinatura foi alterada depois da publicação original.
- Matriz e filiais se distinguem por `orgao_cnpj`.
- A refined guarda só a versão vigente; análises de mudança ao longo do tempo leem as versões da raw.

**Painel (etapa 4):**

- Fornecedor pessoa física sempre agregado, e texto livre dos contratos de pessoa física nunca exibido (decisão 6).
- Notas de leitura dizendo o que ficou de fora de cada cálculo: compras com estimado zero, compras sem homologado, contratos sem compra encontrada.
- As horas são exibidas como vieram, com a premissa do horário de Brasília (decisão 4).

**Qualidade (etapa 4):**

- Acompanhar a contagem por regra de `refined.anomalias` entre execuções.

## Fora de escopo

- Corrigir anomalias ou preencher dados faltantes.
- Histórico de versões na refined (só a versão vigente).
- Processamento incremental da transformação (decisão 10).
- Identificar nomes de pessoas em texto livre.
- Verificar o fuso horário das datas da API.
- Listar todas as filiais de uma raiz de CNPJ.
- Itens das contratações, atas de registro de preço e plano de contratações anual, já fora de escopo na ingestão.
