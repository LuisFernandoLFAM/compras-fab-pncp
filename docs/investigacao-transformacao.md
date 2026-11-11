# Investigação da camada raw para a etapa 2 (transformação)

Investigação somente de leitura sobre a camada `raw` inteira, feita em 08 e 09/11/2026 para embasar a spec da transformação.

- **Base:** 13.004 contratações e 6.774 contratos, extraídos pela carga completa de 07 e 08/11/2026 e pelo incremental de 08/11/2026 (dados até 07/11/2026).
- **Versão vigente:** a de maior `dataAtualizacaoGlobal`, com o `_extraido_em` mais recente como desempate.
- **Dados pessoais:** este relatório não contém nenhum CPF nem nome de pessoa física; só contagens.

## Conclusão

1. **Cada registro tem uma única versão.** A carga completa trouxe o estado de cada registro em 07/11/2026, e o primeiro incremental não trouxe mudanças. A regra de versão vigente ainda não foi exercitada com dados reais. Mesmo assim, 80% das contratações e 62% dos contratos foram alterados depois de publicados: o histórico anterior à coleta não existe na raw.
2. **Sete campos são 100% vazios** (dois em contratações, cinco em contratos) e não precisam ir para a refined.
3. **A maioria dos nulos parciais tem significado e não deve virar zero nem `false`:**
   - datas de proposta nulas indicam contratação direta sem disputa (coincidência exata);
   - valor homologado nulo indica compra sem resultado: suspensa, revogada, recente ou provavelmente deserta ou fracassada;
   - `emendaParlamentar`, `temRemanejamento` e `frutoAdesao` são campos novos no PNCP (maio e agosto de 2026); nulo significa "não informado";
   - `dataVigenciaFim` nula aparece em contratos de fornecimento de energia elétrica, de prazo indeterminado.
4. **Texto vazio e nulo coexistem** no mesmo campo (por exemplo, 3.759 textos vazios e 909 nulos em `contratos.informacaoComplementar`). A transformação precisa normalizar os dois para nulo.
5. **Dinheiro:** até 4 casas decimais (só `valorParcela`; os demais têm até 2) e valor máximo de R$ 11,1 bilhões. Os números devem ser lidos do texto do JSON como decimal exato, não como ponto flutuante.
6. **Datas:** dois formatos uniformes, sem fuso horário: data e hora (`AAAA-MM-DDTHH:MM:SS`) e só data (`AAAA-MM-DD`).
7. **Dados pessoais:** 25 contratos com fornecedor pessoa física têm CPF completo e válido em `niFornecedor` e o nome da pessoa em `nomeRazaoSocialFornecedor`. Um contrato traz também o CPF no texto livre. O mascaramento precisa cobrir os três lugares.
8. **Ligação contrato e compra:** 94,9% dos contratos encontram a compra na raw. O restante se divide entre compras da FAB anteriores a 2023 (140), compras de 7 filiais da FAB (180) e compras de 5 outros órgãos (24). Nenhuma compra da FAB de 2023 em diante ficou sem par.
9. **Filiais:** as 7 filiais publicaram 449 contratações em 2024 e 179 em 2025 nas modalidades 6, 8 e 9, e nenhuma em 2023 ou 2026. Isso equivale a 11,8% e 4,3% do total da FAB nessas modalidades, e fica fora da carga, que consulta só o CNPJ da matriz. Não foi possível listar todas as filiais pela API.
10. **Valor estimado zero (548 compras):** 299 são compras revogadas ou anuladas; quase todas as revogadas e anuladas têm estimado zero. As outras 246 não têm resultado na maioria. A raw não tem indicador de orçamento sigiloso, e o padrão encontrado é mais compatível com compras sem resultado do que com sigilo.
11. **Anomalias:** a mais frequente é contrato publicado antes da assinatura (533). Há também 9 contratos apontando para compras de 2027, 39 compras com homologado maior que o estimado (26 de credenciamento) e textos com espaços nas pontas em milhares de registros.
12. **Fontes orçamentárias:** 1.416 compras têm a lista preenchida, sempre com um único elemento. O campo só passou a ser informado em junho e julho de 2026.

## 1. Perfil dos campos

Tipos como aparecem no JSON: "decimal" é número com ponto decimal, "objeto" é um JSON aninhado. Nos campos dentro de listas (`[]`) e dentro de objetos opcionais, os percentuais são sobre as ocorrências do elemento, não sobre o total de registros. "% vazio" conta texto só com espaços e lista vazia.

**Campos 100% vazios na raw inteira:**
- contratações: `orgaoSubRogado`, `unidadeSubRogada`;
- contratos: `identificadorCipi`, `urlCipi`, `niFornecedorSubContratado`, `nomeFornecedorSubContratado`, `tipoPessoaSubContratada`.

**raw.contratacoes** (13.004 registros)

| Campo | Tipos encontrados | % nulo | % vazio | 100% vazio |
| --- | --- | --- | --- | --- |
| `amparoLegal.codigo` | inteiro (13.004) | 0 | 0 |  |
| `amparoLegal.descricao` | texto (13.004) | 0 | 0 |  |
| `amparoLegal.nome` | texto (13.004) | 0 | 0 |  |
| `anoCompra` | inteiro (13.004) | 0 | 0 |  |
| `dataAberturaProposta` | texto (9.174), nulo (3.830) | 29,45 | 0 |  |
| `dataAtualizacao` | texto (13.004) | 0 | 0 |  |
| `dataAtualizacaoGlobal` | texto (13.004) | 0 | 0 |  |
| `dataEncerramentoProposta` | texto (9.174), nulo (3.830) | 29,45 | 0 |  |
| `dataInclusao` | texto (13.004) | 0 | 0 |  |
| `dataPublicacaoPncp` | texto (13.004) | 0 | 0 |  |
| `emendaParlamentar` | nulo (12.699), booleano (305) | 97,65 | 0 |  |
| `fontesOrcamentarias` | lista (13.004) | 0 | 89,11 |  |
| `fontesOrcamentarias[].codigo` | inteiro (1.416) | 0 | 0 |  |
| `fontesOrcamentarias[].dataInclusao` | texto (1.416) | 0 | 0 |  |
| `fontesOrcamentarias[].descricao` | texto (1.416) | 0 | 0 |  |
| `fontesOrcamentarias[].nome` | texto (1.416) | 0 | 0 |  |
| `informacaoComplementar` | texto (9.491), nulo (3.513) | 27,01 | 0,40 |  |
| `justificativaPresencial` | nulo (12.991), texto (13) | 99,90 | 0 |  |
| `linkProcessoEletronico` | nulo (11.135), texto (1.869) | 85,63 | 0 |  |
| `linkSistemaOrigem` | texto (7.978), nulo (5.026) | 38,65 | 0 |  |
| `modalidadeId` | inteiro (13.004) | 0 | 0 |  |
| `modalidadeNome` | texto (13.004) | 0 | 0 |  |
| `modoDisputaId` | inteiro (13.004) | 0 | 0 |  |
| `modoDisputaNome` | texto (13.004) | 0 | 0 |  |
| `numeroCompra` | texto (13.004) | 0 | 0 |  |
| `numeroControlePNCP` | texto (13.004) | 0 | 0 |  |
| `objetoCompra` | texto (13.004) | 0 | 0 |  |
| `orgaoEntidade.cnpj` | texto (13.004) | 0 | 0 |  |
| `orgaoEntidade.esferaId` | texto (13.004) | 0 | 0 |  |
| `orgaoEntidade.poderId` | texto (13.004) | 0 | 0 |  |
| `orgaoEntidade.razaoSocial` | texto (13.004) | 0 | 0 |  |
| `orgaoSubRogado` | nulo (13.004) | 100 | 0 | sim |
| `processo` | texto (13.004) | 0 | 0 |  |
| `sequencialCompra` | inteiro (13.004) | 0 | 0 |  |
| `situacaoCompraId` | inteiro (13.004) | 0 | 0 |  |
| `situacaoCompraNome` | texto (13.004) | 0 | 0 |  |
| `srp` | booleano (13.004) | 0 | 0 |  |
| `tipoInstrumentoConvocatorioCodigo` | inteiro (13.004) | 0 | 0 |  |
| `tipoInstrumentoConvocatorioNome` | texto (13.004) | 0 | 0 |  |
| `unidadeOrgao.codigoIbge` | texto (13.004) | 0 | 0 |  |
| `unidadeOrgao.codigoUnidade` | texto (13.004) | 0 | 0 |  |
| `unidadeOrgao.municipioNome` | texto (13.004) | 0 | 0 |  |
| `unidadeOrgao.nomeUnidade` | texto (13.004) | 0 | 0 |  |
| `unidadeOrgao.ufNome` | texto (13.004) | 0 | 0 |  |
| `unidadeOrgao.ufSigla` | texto (13.004) | 0 | 0 |  |
| `unidadeSubRogada` | nulo (13.004) | 100 | 0 | sim |
| `usuarioNome` | texto (13.004) | 0 | 0 |  |
| `valorTotalEstimado` | decimal (13.004) | 0 | 0 |  |
| `valorTotalHomologado` | decimal (10.926), nulo (2.078) | 15,98 | 0 |  |

**raw.contratos** (6.774 registros)

| Campo | Tipos encontrados | % nulo | % vazio | 100% vazio |
| --- | --- | --- | --- | --- |
| `anoContrato` | inteiro (6.774) | 0 | 0 |  |
| `categoriaProcesso.id` | inteiro (6.774) | 0 | 0 |  |
| `categoriaProcesso.nome` | texto (6.774) | 0 | 0 |  |
| `codigoPaisFornecedor` | nulo (4.433), texto (2.341) | 65,44 | 0 |  |
| `dataAssinatura` | texto (6.774) | 0 | 0 |  |
| `dataAtualizacao` | texto (6.774) | 0 | 0 |  |
| `dataAtualizacaoGlobal` | texto (6.774) | 0 | 0 |  |
| `dataPublicacaoPncp` | texto (6.774) | 0 | 0 |  |
| `dataVigenciaFim` | texto (6.753), nulo (21) | 0,31 | 0 |  |
| `dataVigenciaInicio` | texto (6.774) | 0 | 0 |  |
| `emendaParlamentar` | nulo (6.626), booleano (148) | 97,82 | 0 |  |
| `frutoAdesao` | nulo (5.118), booleano (1.656) | 75,55 | 0 |  |
| `identificadorCipi` | nulo (6.774) | 100 | 0 | sim |
| `informacaoComplementar` | texto (5.865), nulo (909) | 13,42 | 55,49 |  |
| `niFornecedor` | texto (6.774) | 0 | 0 |  |
| `niFornecedorSubContratado` | nulo (6.774) | 100 | 0 | sim |
| `nomeFornecedorSubContratado` | nulo (6.774) | 100 | 0 | sim |
| `nomeRazaoSocialFornecedor` | texto (6.774) | 0 | 0,10 |  |
| `numeroContratoEmpenho` | texto (6.774) | 0 | 0 |  |
| `numeroControlePNCP` | texto (6.774) | 0 | 0 |  |
| `numeroControlePncpAta` | nulo (6.455), texto (319) | 95,29 | 0 |  |
| `numeroControlePncpCompra` | texto (6.774) | 0 | 0 |  |
| `numeroParcelas` | inteiro (6.774) | 0 | 0 |  |
| `numeroRetificacao` | inteiro (6.774) | 0 | 0 |  |
| `objetoContrato` | texto (6.774) | 0 | 0 |  |
| `orgaoEntidade.cnpj` | texto (6.774) | 0 | 0 |  |
| `orgaoEntidade.esferaId` | texto (6.774) | 0 | 0 |  |
| `orgaoEntidade.poderId` | texto (6.774) | 0 | 0 |  |
| `orgaoEntidade.razaoSocial` | texto (6.774) | 0 | 0 |  |
| `orgaoSubRogado` | nulo (6.769), objeto (5) | 99,93 | 0 |  |
| `orgaoSubRogado.cnpj` | texto (5) | 0 | 0 |  |
| `orgaoSubRogado.esferaId` | texto (5) | 0 | 0 |  |
| `orgaoSubRogado.poderId` | texto (5) | 0 | 0 |  |
| `orgaoSubRogado.razaoSocial` | texto (5) | 0 | 0 |  |
| `processo` | texto (6.774) | 0 | 0 |  |
| `receita` | booleano (6.774) | 0 | 0 |  |
| `sequencialContrato` | inteiro (6.774) | 0 | 0 |  |
| `temRemanejamento` | nulo (5.118), booleano (1.656) | 75,55 | 0 |  |
| `tipoContrato.id` | inteiro (6.774) | 0 | 0 |  |
| `tipoContrato.nome` | texto (6.774) | 0 | 0 |  |
| `tipoPessoa` | texto (6.774) | 0 | 0 |  |
| `tipoPessoaSubContratada` | nulo (6.774) | 100 | 0 | sim |
| `unidadeOrgao.codigoIbge` | texto (6.774) | 0 | 0 |  |
| `unidadeOrgao.codigoUnidade` | texto (6.774) | 0 | 0 |  |
| `unidadeOrgao.municipioNome` | texto (6.774) | 0 | 0 |  |
| `unidadeOrgao.nomeUnidade` | texto (6.774) | 0 | 0 |  |
| `unidadeOrgao.ufNome` | texto (6.774) | 0 | 0 |  |
| `unidadeOrgao.ufSigla` | texto (6.774) | 0 | 0 |  |
| `unidadeSubRogada` | nulo (6.770), objeto (4) | 99,94 | 0 |  |
| `unidadeSubRogada.codigoIbge` | texto (4) | 0 | 0 |  |
| `unidadeSubRogada.codigoUnidade` | texto (4) | 0 | 0 |  |
| `unidadeSubRogada.municipioNome` | texto (4) | 0 | 0 |  |
| `unidadeSubRogada.nomeUnidade` | texto (4) | 0 | 0 |  |
| `unidadeSubRogada.ufNome` | texto (4) | 0 | 0 |  |
| `unidadeSubRogada.ufSigla` | texto (4) | 0 | 0 |  |
| `urlCipi` | nulo (6.774) | 100 | 0 | sim |
| `usuarioNome` | texto (6.774) | 0 | 0 |  |
| `valorAcumulado` | nulo (4.743), decimal (2.031) | 70,02 | 0 |  |
| `valorGlobal` | decimal (6.774) | 0 | 0 |  |
| `valorInicial` | decimal (6.774) | 0 | 0 |  |
| `valorParcela` | decimal (6.774) | 0 | 0 |  |

Os campos `temRemanejamento` e `frutoAdesao` só existem em contratos; `emendaParlamentar` existe nas duas tabelas.

## 2. Significado dos nulos parciais

### Hipóteses pedidas

**`valorTotalHomologado` nulo (2.078 compras): confirmada em parte.** Nulo significa compra sem resultado homologado, por quatro motivos:

| Grupo | Compras | Nulo |
| --- | --- | --- |
| Suspensa | 129 | 96,1% |
| Revogada | 271 | 80,4% |
| Anulada | 32 | 46,9% |
| Com disputa (todas as situações), publicada há menos de 3 meses | 777 | 64,0% |
| Com disputa (todas as situações), publicada há 3 meses ou mais | 8.397 | 18,8% |
| Contratação direta sem disputa (inexigibilidade e dispensa sem disputa) | 3.830 | 0,1% |

- Das 1.721 compras divulgadas sem homologado, só 2 têm contrato ligado. Das 1.160 publicadas há mais de 6 meses (645 dispensas, 467 pregões), também só 2. Isso indica compras desertas ou fracassadas, embora a raw não tenha um campo que diga isso.
- Homologado igual a zero existe (237 compras) e é diferente de nulo.

**`dataAberturaProposta` e `dataEncerramentoProposta` nulas (3.830): confirmada, com coincidência exata.**
- As duas são nulas sempre juntas.
- São nulas em 100% das compras com instrumento "Ato que autoriza a Contratação Direta" (3.142 inexigibilidades e 688 dispensas, modo de disputa "Não se aplica") e em nenhuma outra.
- O credenciamento também tem modo "Não se aplica", mas tem as datas preenchidas, porque usa edital de chamamento público.

**`dataVigenciaFim` nula (21 contratos): confirmada.**
- Os 21 são do tipo "Contrato (termo inicial)" na categoria "Serviços".
- 14 têm objeto de fornecimento de energia elétrica, serviço que admite prazo indeterminado. Nulo aqui significa vigência sem data de fim, não dado faltando.

**`temRemanejamento`, `frutoAdesao` e `emendaParlamentar` nulos: confirmada. São campos novos, e o corte é pela data de atualização do registro, não pela de publicação.**

| Campo | Primeira atualização com valor | Registros com valor | Valores |
| --- | --- | --- | --- |
| `contratos.temRemanejamento` | 13/05/2026 | 1.656 | 1.647 `false`, 9 `true` |
| `contratos.frutoAdesao` | 13/05/2026 | 1.656 | 1.652 `false`, 4 `true` |
| `contratos.emendaParlamentar` | 03/08/2026 | 148 | 148 `false` |
| `contratacoes.emendaParlamentar` | 03/08/2026 | 305 | 304 `false`, 1 `true` |

- Todo registro com valor teve a própria `dataAtualizacao` depois da data de corte. Contratos publicados desde junho de 2026 têm `temRemanejamento` e `frutoAdesao` preenchidos em 100% dos casos.
- `temRemanejamento` e `frutoAdesao` são nulos sempre juntos.
- `emendaParlamentar` continua nulo em boa parte dos registros atualizados depois de 03/08/2026, então parece opcional mesmo nos registros novos.
- Consequência: nulo significa "não informado", e não `false`.

### Outros nulos parciais

| Campo | Padrão encontrado |
| --- | --- |
| `contratacoes.justificativaPresencial` | Preenchido exatamente nas 13 compras presenciais (10 concorrências e 3 pregões). |
| `contratacoes.fontesOrcamentarias` (lista vazia) | Vazia até maio de 2026; preenchida em cerca de 92% das compras publicadas desde julho de 2026. Ver item 11. |
| `contratacoes.linkProcessoEletronico` | Ausente até janeiro de 2026; aparece aos poucos desde fevereiro e fica em cerca de 87% desde julho de 2026. |
| `contratacoes.linkSistemaOrigem` | Sempre preenchido em pregões e concorrências eletrônicas. Ausente nas compras do sistema Contrata+Brasil (170 de 170) e, desde 2024, em quase todas as inexigibilidades e dispensas. |
| `contratacoes.informacaoComplementar` | Nulo cresce com o tempo: 3% em 2023, 54% em 2026. Sem padrão por modalidade. |
| `contratos.valorAcumulado` | Só existe em empenhos de 2023 e início de 2024 (2.031 registros); nulo em todos os demais tipos e em todos os empenhos de 2025 e 2026. |
| `contratos.informacaoComplementar` | Preenchido quase só em empenhos (96,5% dos empenhos), vazio em 98,5% dos contratos. Mistura nulo (909) e texto vazio (3.759). |
| `contratos.numeroControlePncpAta` | Preenchido em 319 contratos, os que vêm de ata de registro de preços. Os 4 com `frutoAdesao = true` têm ata. |
| `contratos.codigoPaisFornecedor` | Só tem os valores `BRA` ou nulo. Nulo sobe de cerca de 60% em 2023 para cerca de 90% no fim de 2026, sem relação com tipo de pessoa ou categoria. Não carrega informação útil. |
| `contratos.orgaoSubRogado`, `unidadeSubRogada` | Preenchidos em 5 e 4 contratos. Em 4 deles o órgão sub-rogado é a própria FAB, só com outra unidade; em 1 é uma filial (`00394429018824`). |

## 3. Dinheiro

Casas decimais contadas no texto do JSON. A API sempre escreve o número com ponto decimal, mesmo quando é inteiro (`100.0`), por isso a menor contagem é 1 casa.

| Campo | Registros | Máximo de casas | Maior valor (R$) |
| --- | --- | --- | --- |
| `contratacoes.valorTotalEstimado` | 13.004 | 2 | 11.146.030.972,07 |
| `contratacoes.valorTotalHomologado` | 10.926 | 2 | 6.879.788.075,90 |
| `contratos.valorInicial` | 6.774 | 2 | 2.131.076.259,40 |
| `contratos.valorGlobal` | 6.774 | 2 | 2.131.076.259,40 |
| `contratos.valorParcela` | 6.774 | 4 (44 com 3 casas, 323 com 4) | 2.131.076.259,40 |
| `contratos.valorAcumulado` | 2.031 | 2 | 1.353.856,01 |

- Nenhum valor negativo e nenhum em notação científica.
- O maior valor tem 11 dígitos na parte inteira. Um decimal com 18 dígitos e 4 casas cobre todos os campos com folga.

## 4. Datas

| Formato | Campos |
| --- | --- |
| `AAAA-MM-DDTHH:MM:SS` | contratações: `dataInclusao`, `dataPublicacaoPncp`, `dataAtualizacao`, `dataAtualizacaoGlobal`, `dataAberturaProposta`, `dataEncerramentoProposta`, `fontesOrcamentarias[].dataInclusao`; contratos: `dataPublicacaoPncp`, `dataAtualizacao`, `dataAtualizacaoGlobal` |
| `AAAA-MM-DD` | contratos: `dataAssinatura`, `dataVigenciaInicio`, `dataVigenciaFim` |

- Cada campo tem um único formato em todos os registros. Os únicos valores fora deles são nulos.
- Nenhuma data e hora traz fuso horário. O mais provável é o horário de Brasília, mas isso não foi verificado; a spec da transformação precisa definir o fuso.

## 5. Dados pessoais

**Tipo de pessoa do fornecedor e tamanho do `niFornecedor`:**

| `tipoPessoa` | Contratos | `niFornecedor` |
| --- | --- | --- |
| PJ (pessoa jurídica) | 6.743 | 14 dígitos (CNPJ) |
| PF (pessoa física) | 25 | 11 dígitos (CPF); os 25 têm dígito verificador válido |
| PE (pessoa estrangeira) | 6 | 9 caracteres, não só dígitos |

- Os 25 contratos com pessoa física se dividem em 12 de compras, 7 de serviços, 5 de serviços de saúde e 1 de cessão. Por ano: 1 em 2023, 3 em 2024, 12 em 2025 e 9 em 2026.
- Nesses 25 contratos, `nomeRazaoSocialFornecedor` é o nome da pessoa.

**CPF em texto livre** (objeto e informação complementar):

| Campo | CPF formatado (`000.000.000-00`) | 11 dígitos seguidos com dígito verificador válido | CPF mascarado | Palavra "CPF" citada |
| --- | --- | --- | --- | --- |
| `contratacoes.objetoCompra` | 0 | 0 | 0 | 2 |
| `contratacoes.informacaoComplementar` | 0 | 0 | 0 | 2 |
| `contratos.objetoContrato` | 0 | 0 | 0 | 0 |
| `contratos.informacaoComplementar` | 1 | 0 | 0 | 1 |

- O único CPF encontrado em texto livre é válido e é o do próprio fornecedor pessoa física daquele contrato.
- A busca por padrões não consegue identificar nomes de pessoas em texto livre. Esse risco continua existindo.

## 6. Versões

| Tabela | Linhas | Registros | Com mais de uma versão | Empates de `dataAtualizacaoGlobal` |
| --- | --- | --- | --- | --- |
| `raw.contratacoes` | 13.004 | 13.004 | 0 | 0 |
| `raw.contratos` | 6.774 | 6.774 | 0 | 0 |

- A raw só tem a versão de cada registro vigente em 07/11/2026, e o incremental de 08/11/2026 não trouxe mudanças.
- Mesmo assim, o dado já foi alterado depois da publicação em 10.359 contratações (80%) e 4.230 contratos (62%). Essas versões anteriores não foram coletadas.
- **Ordem das datas de atualização:** em 133 contratações, a `dataAtualizacaoGlobal` é anterior à `dataAtualizacao`.
  - Em 127 delas, a diferença é de segundos, no mesmo dia.
  - Nas outras 6, é de 1 a 15 dias.
  - Em contratos, a global é sempre maior ou igual.
  - Isso não afeta a regra enquanto houver uma versão por registro. Mas, quando houver várias, a escolha pela `dataAtualizacaoGlobal` pode divergir da escolha pela `dataAtualizacao` nesses casos.

## 7. Ligação dos contratos com as compras

| Grupo | Contratos | % |
| --- | --- | --- |
| Compra encontrada na raw | 6.430 | 94,9 |
| Compra da FAB anterior a 2023 | 140 | 2,1 |
| Compra de filial da FAB (raiz 00394429, outro final) | 180 | 2,7 |
| Compra de outro órgão | 24 | 0,4 |
| **Total** | **6.774** | **100** |

- **Compras da FAB anteriores a 2023:** 139 são de 2022 e 1 de 2021.
- **Compras da FAB de 2023 em diante:** todas foram encontradas.
- **Outros órgãos:** 5 CNPJs: `00489828000155` (19 contratos), `00394452000103` (2), `00508903000188` (1), `00394544000185` (1) e `33663683000116` (1).
- **Órgão dos registros:** todos os contratos e todas as compras da raw têm `orgaoEntidade.cnpj` igual à matriz (`00394429000100`). O que aponta para as filiais é só a referência à compra.

## 8. Cobertura das filiais

Sete CNPJs de filiais da FAB aparecem nas referências dos contratos. A tabela traz as contratações que cada filial publicou por ano, nas modalidades 6 (pregão eletrônico), 8 (dispensa) e 9 (inexigibilidade), com o formato pregão/dispensa/inexigibilidade = total. Os números são o `totalRegistros` do endpoint `/v1/contratacoes/publicacao`, com janelas anuais e a pausa de 3 s do `config.toml`, sem gravar nada na landing.

| Filial | Contratos da raw que apontam para ela | 2023 | 2024 | 2025 | 2026 (até 08/11) |
| --- | --- | --- | --- | --- | --- |
| `00394429018824` | 62 | 0 | 57/4/18 = 79 | 7/1/2 = 10 | 0 |
| `00394429019715` | 30 | 0 | 88/21/6 = 115 | 24/0/12 = 36 | 0 |
| `00394429018310` | 29 | 0 | 34/21/10 = 65 | 9/4/2 = 15 | 0 |
| `00394429019391` | 21 | 0 | 34/37/16 = 87 | 8/12/15 = 35 | 0 |
| `00394429017933` | 18 | 0 | 29/13/13 = 55 | 12/1/1 = 14 | 0 |
| `00394429018409` | 10 | 0 | 25/17/6 = 48 | 8/1/0 = 9 | 0 |
| `00394429018581` | 10 | 0 | 0 | 43/17/0 = 60 | 0 |
| **Total** | **180** | **0** | **449** | **179** | **0** |

- **As filiais publicaram só em 2024 e 2025.** Em 2023 e 2026, nenhuma das sete publicou contratação nessas modalidades.
- **Tamanho da lacuna:** a carga consulta só o CNPJ da matriz, então essas compras ficam de fora.
  - Em 2024, as 449 compras das filiais equivalem a 11,8% do total da FAB nessas modalidades (3.362 da matriz).
  - Em 2025, as 179 equivalem a 4,3% (4.010 da matriz).
- **Ano das compras referenciadas:** pelos contratos, as compras das filiais são de 2023 (1), 2024 (157) e 2025 (22). A compra de 2023 deve ser de outra modalidade, já que a contagem acima deu zero para 2023.
- **A lista pode estar incompleta.** Ela vem só dos contratos da matriz, então uma filial que nunca teve contrato registrado sob a matriz não aparece.
- **Tentativa de listar todas as filiais pela API:** testei quatro consultas da API principal do PNCP (`/api/pncp/v1/orgaos/{cnpj}`, `/api/pncp/v1/orgaos` com filtro de razão social e de CNPJ, e `/api/pncp/v1/orgaos/{cnpj}/unidades`). Todas falharam no momento do teste (HTTP 503, tempo esgotado ou conexão encerrada), então não foi possível confirmar se existe um jeito de listar as filiais de uma raiz. A API de consulta só aceita o CNPJ completo e não lista órgãos.
- **Instabilidade:** a API de consulta também esteve instável. Janelas anuais levaram até cerca de 55 s por chamada, e duas contagens falharam com HTTP 500 persistente e só deram certo numa segunda rodada. Foram 99 chamadas de contagem no total, mais 1 de teste e 4 de tentativa de listagem.

## 9. Valor estimado zero

548 compras (4,2%) têm `valorTotalEstimado` igual a zero.

**Por situação:**

| Situação | Estimado zero | Total da situação |
| --- | --- | --- |
| Revogada | 269 | 271 |
| Anulada | 30 | 32 |
| Suspensa | 3 | 129 |
| Divulgada no PNCP | 246 | 12.572 |

Quase todas as compras revogadas e anuladas têm estimado zero. Isso indica que o valor é zerado quando a compra é revogada ou anulada.

**Por modalidade** (todas as 548):

| Modalidade | Estimado zero | % da modalidade |
| --- | --- | --- |
| Pregão eletrônico | 355 | 6,0 |
| Inexigibilidade | 85 | 2,7 |
| Dispensa | 58 | 1,6 |
| Credenciamento | 31 | 29,0 |
| Concorrência eletrônica | 16 | 7,0 |
| Concorrência presencial | 2 | 20,0 |
| Concurso | 1 | 50,0 |

**Por amparo legal:**

| Amparo legal (Lei 14.133/2021) | Compras |
| --- | --- |
| Art. 28, I (pregão) | 355 |
| Art. 74, IV (inexigibilidade, credenciamento) | 49 |
| Art. 75, II (dispensa por valor) | 37 |
| Art. 79, II | 21 |
| Art. 28, II (concorrência) | 18 |
| Art. 74, caput | 14 |
| Art. 74, I | 12 |
| Art. 79, I | 10 |
| Outros | 32 |

**Registro de preços:** 211 com registro de preços, 337 sem. Todas as 211 são pregões. A proporção (38,5%) é próxima da geral (33,3%).

**Compatibilidade com orçamento sigiloso:**
- Nenhum campo da compra indica sigilo, e nenhuma das 548 cita "sigiloso" no objeto ou na informação complementar.
- Nas 246 compras divulgadas com estimado zero:
  - os 147 pregões não têm homologado, e só 1 tem contrato;
  - 144 deles já passaram da data de encerramento das propostas;
  - as 44 inexigibilidades têm homologado também zero.
- Com orçamento sigiloso, o normal seria haver resultado e valor homologado depois da disputa. O padrão encontrado é mais compatível com compras sem resultado (desertas ou fracassadas) e, nas inexigibilidades e credenciamentos, com valor que não se conhece de antemão.
- Não dá para confirmar nem descartar sigilo só com a raw: o detalhe por item está fora do escopo.
- Há também 72 compras com estimado zero e homologado positivo.

## 10. Anomalias

| Anomalia | Ocorrências |
| --- | --- |
| Contrato publicado no PNCP antes da data de assinatura | 533 contratos |
| Contrato assinado antes da publicação da compra a que se refere | 352 contratos |
| `anoContrato` diferente do ano da assinatura | 472 contratos |
| Contrato apontando para compra de ano posterior ao do contrato | 59 contratos, 9 deles para compras de 2027 |
| Compra com `anoCompra` posterior ao ano de publicação | 122 compras, 33 delas de 2027 |
| Compra com `anoCompra` anterior ao ano de publicação | 615 compras (611 de 1 ano antes, 4 de 2 anos antes) |
| Vigência final antes da inicial | 0 |
| Vigência inicial mais de 30 dias antes da assinatura | 0 |
| Homologado maior que o estimado (estimado maior que zero) | 39 compras (26 credenciamentos, 11 pregões, 2 dispensas); 24 com mais do dobro, 7 com mais de 10 vezes |
| Homologado positivo com estimado zero | 72 compras |
| Compra revogada ou anulada com homologado positivo | 67 compras |
| Abertura das propostas antes da publicação da compra | 3 compras |
| Encerramento das propostas antes da abertura | 0 |
| Contrato com `valorGlobal` zero | 156 contratos |
| `valorGlobal` menor que `valorInicial` | 3 contratos |
| `valorParcela` vezes `numeroParcelas` diferente do `valorGlobal` em mais de 1% | 91 contratos |
| Assinatura antes de 2023 | 30 contratos |
| Vigência de mais de 10 anos | 10 contratos |
| Contrato retificado (`numeroRetificacao` maior que zero) | 2.535 contratos, até 28 retificações |
| Espaços nas pontas: `processo` | 386 compras, 0 contratos |
| Espaços nas pontas: `objetoCompra` e `informacaoComplementar` das compras | 1.002 e 5.617 compras |
| Espaços nas pontas: `nomeRazaoSocialFornecedor` | 14 contratos |
| Nome do fornecedor vazio | 7 contratos (todos de pessoa jurídica) |

Contratos e compras com datas trocadas ou anos futuros devem ser mantidos e sinalizados, não corrigidos, conforme já registrado na spec da ingestão.

## 11. Fontes orçamentárias

- **Preenchimento:** 1.416 compras (10,9%) têm a lista preenchida. O tamanho máximo é 1: nenhuma compra tem mais de uma fonte.
- **Valores:** Federal (código 4) em 1.404 compras, Não se aplica (1) em 11, Estadual (3) em 1.
- **Período:** quase só em compras publicadas desde junho de 2026: 2 em março, 1 em maio, 18 em junho e cerca de 92% das compras de julho em diante.
- **Por modalidade:** 740 pregões, 321 dispensas, 311 inexigibilidades, 33 concorrências e 11 credenciamentos.

Como a lista nunca tem mais de um elemento, ela pode virar colunas simples na refined. Mesmo assim, convém um aviso se aparecer uma compra com mais de uma fonte.

## Atualização depois da inclusão das filiais

Consulta somente de leitura feita em 10/11/2026 sobre a raw depois da carga completa das 7 filiais e do incremental de 09/11/2026 (dados até 09/11/2026). Ela refaz o item 7 com a regra de versão vigente da spec da transformação: a de maior valor entre `dataAtualizacaoGlobal` e `dataAtualizacao`, com o `_extraido_em` mais recente como desempate.

**Base:**

| Tabela | Linhas | Registros | Com mais de uma versão | Registros de filiais |
| --- | --- | --- | --- | --- |
| `raw.contratacoes` | 13.696 | 13.677 | 19 | 649 |
| `raw.contratos` | 6.797 | 6.786 | 11 | 5 |

- A regra de versão vigente foi exercitada pela primeira vez: nos 30 registros com duas versões, ela escolhe a mesma versão que a regra só pela `dataAtualizacaoGlobal`, e não há empate de data.
- As contratações com `dataAtualizacaoGlobal` anterior à `dataAtualizacao` passaram de 133 para 155. Em contratos, continuam sendo nenhuma.
- `orgaoEntidade.cnpj` deixou de ser sempre a matriz: os registros de filiais trazem o CNPJ da própria filial.

### 7. Ligação dos contratos com as compras (refeita)

| Grupo | Contratos | % |
| --- | --- | --- |
| Compra encontrada na raw | 6.622 | 97,6 |
| Compra da FAB anterior a 2023 | 140 | 2,1 |
| Compra de filial da FAB fora da lista configurada | 0 | 0 |
| Compra de outro órgão | 24 | 0,4 |
| **Total** | **6.786** | **100** |

- **Filiais:** os 180 contratos que apontavam para compras de filiais agora encontram a compra, inclusive o que aponta para uma compra de filial de 2023. Por filial: `00394429018824` 62, `00394429019715` 30, `00394429018310` 30, `00394429017933` 22, `00394429019391` 21, `00394429018409` 10 e `00394429018581` 10, num total de 185 com os 5 contratos publicados pelas próprias filiais.
- **Contratos novos:** são 12 a mais que na investigação (5 publicados pelas filiais e 7 trazidos pelo incremental da matriz), e todos encontram a compra.
- **Compras da FAB anteriores a 2023:** as mesmas 140, todas da matriz (139 de 2022 e 1 de 2021).
- **Compras da FAB de 2023 em diante:** todas foram encontradas, da matriz e das 7 filiais.
- **Outros órgãos:** os mesmos 24 contratos e os mesmos 5 CNPJs.
- **Filial fora da lista:** nenhum contrato aponta hoje para uma compra de CNPJ com a raiz `00394429` fora da lista configurada. O grupo continua existindo, porque a lista de filiais pode estar incompleta.
