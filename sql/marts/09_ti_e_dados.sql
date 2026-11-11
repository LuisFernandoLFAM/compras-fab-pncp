-- Grão: marts.ti_e_dados, uma linha por segmento (ti ou dados), ano de publicação e unidade;
--       marts.ti_e_dados_fornecedores, os 10 maiores fornecedores de cada segmento.
-- Perguntas: quanto a FAB compra de TI e de dados, onde, o que está aberto e quem fornece?
-- dados é subconjunto de ti: as linhas de ti incluem as de dados.

CREATE OR REPLACE TABLE marts.ti_e_dados AS
WITH segmentos AS (
    SELECT tabela, chave, 'ti' AS segmento
    FROM marts.segmento_objeto WHERE segmento IN ('ti', 'dados')
    UNION ALL
    SELECT tabela, chave, 'dados'
    FROM marts.segmento_objeto WHERE segmento = 'dados'
),
unidades AS (
    -- Nome e UF do registro mais recente da unidade, entre compras e contratos.
    SELECT unidade_codigo, unidade_nome, uf
    FROM (
        SELECT unidade_codigo_unidade AS unidade_codigo, unidade_nome_unidade AS unidade_nome,
               unidade_uf_sigla AS uf, data_publicacao_pncp, numero_controle_pncp
        FROM refined.contratacoes
        UNION ALL
        SELECT unidade_codigo_unidade, unidade_nome_unidade, unidade_uf_sigla,
               data_publicacao_pncp, numero_controle_pncp
        FROM refined.contratos
    )
    QUALIFY row_number() OVER (
        PARTITION BY unidade_codigo ORDER BY data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
compras AS (
    SELECT s.segmento,
           year(c.data_publicacao_pncp) AS ano,
           c.unidade_codigo_unidade AS unidade_codigo,
           count(*) AS compras,
           sum(c.valor_total_estimado) AS valor_estimado,
           coalesce(sum(c.valor_total_homologado), 0) AS valor_homologado,
           count(*) FILTER (WHERE CAST(c.data_encerramento_proposta AS DATE) > r.data_referencia)
               AS propostas_abertas,
           coalesce(
               sum(c.valor_total_estimado)
                   FILTER (WHERE CAST(c.data_encerramento_proposta AS DATE) > r.data_referencia),
               0
           ) AS valor_estimado_propostas_abertas
    FROM refined.contratacoes c
    CROSS JOIN marts.referencia r
    JOIN segmentos s ON s.tabela = 'contratacoes' AND s.chave = c.numero_controle_pncp
    GROUP BY ALL
),
contratos AS (
    SELECT s.segmento,
           year(k.data_publicacao_pncp) AS ano,
           k.unidade_codigo_unidade AS unidade_codigo,
           count(*) AS contratos,
           sum(k.valor_global) AS valor_contratado
    FROM refined.contratos k
    JOIN segmentos s ON s.tabela = 'contratos' AND s.chave = k.numero_controle_pncp
    GROUP BY ALL
)
SELECT segmento,
       ano,
       unidade_codigo,
       u.unidade_nome,
       u.uf,
       coalesce(c.compras, 0) AS compras,
       coalesce(c.valor_estimado, 0) AS valor_estimado,
       coalesce(c.valor_homologado, 0) AS valor_homologado,
       coalesce(c.propostas_abertas, 0) AS propostas_abertas,
       coalesce(c.valor_estimado_propostas_abertas, 0) AS valor_estimado_propostas_abertas,
       coalesce(k.contratos, 0) AS contratos,
       coalesce(k.valor_contratado, 0) AS valor_contratado
FROM compras c
FULL OUTER JOIN contratos k USING (segmento, ano, unidade_codigo)
JOIN unidades u USING (unidade_codigo)
ORDER BY segmento, ano, unidade_codigo;

CREATE OR REPLACE TABLE marts.ti_e_dados_fornecedores AS
WITH segmentos AS (
    SELECT chave, 'ti' AS segmento
    FROM marts.segmento_objeto WHERE tabela = 'contratos' AND segmento IN ('ti', 'dados')
    UNION ALL
    SELECT chave, 'dados'
    FROM marts.segmento_objeto WHERE tabela = 'contratos' AND segmento = 'dados'
),
nomes AS (
    SELECT ni_fornecedor, nome_razao_social_fornecedor AS nome, tipo_pessoa
    FROM refined.contratos
    WHERE tipo_pessoa IS DISTINCT FROM 'PF'
    QUALIFY row_number() OVER (
        PARTITION BY ni_fornecedor
        ORDER BY data_assinatura DESC, data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
agregado AS (
    SELECT s.segmento,
           CASE WHEN k.tipo_pessoa = 'PF' THEN NULL ELSE k.ni_fornecedor END AS fornecedor_id,
           k.tipo_pessoa = 'PF' AS pessoa_fisica,
           count(*) AS contratos,
           sum(k.valor_global) AS valor_contratado
    FROM refined.contratos k
    JOIN segmentos s ON s.chave = k.numero_controle_pncp
    GROUP BY 1, 2, 3
),
ranking AS (
    SELECT a.*,
           CASE WHEN a.pessoa_fisica THEN 'Pessoa física' ELSE n.nome END AS fornecedor_nome,
           CASE WHEN a.pessoa_fisica THEN 'PF' ELSE n.tipo_pessoa END AS tipo_pessoa,
           row_number() OVER (
               PARTITION BY a.segmento
               ORDER BY a.valor_contratado DESC, a.contratos DESC, coalesce(a.fornecedor_id, '')
           ) AS posicao,
           CAST(a.valor_contratado AS DOUBLE)
               / nullif(sum(CAST(a.valor_contratado AS DOUBLE)) OVER (PARTITION BY a.segmento), 0)
               AS participacao_no_segmento
    FROM agregado a
    LEFT JOIN nomes n ON NOT a.pessoa_fisica AND n.ni_fornecedor = a.fornecedor_id
)
SELECT segmento, posicao, fornecedor_id, fornecedor_nome, tipo_pessoa, contratos,
       valor_contratado, participacao_no_segmento
FROM ranking
WHERE posicao <= 10
ORDER BY segmento, posicao;
