-- Grão: uma linha por unidade (unidade_codigo) e ano de publicação.
-- Perguntas: quais unidades compram mais, onde ficam e com que frequência suas compras são
-- revogadas, anuladas ou ficam provavelmente sem resultado?

CREATE OR REPLACE TABLE marts.compras_por_unidade AS
WITH unidades AS (
    -- Nome e local da compra mais recente da unidade.
    SELECT unidade_codigo_unidade AS unidade_codigo,
           unidade_nome_unidade AS unidade_nome,
           unidade_uf_sigla AS uf,
           unidade_municipio_nome AS municipio,
           orgao_cnpj
    FROM refined.contratacoes
    QUALIFY row_number() OVER (
        PARTITION BY unidade_codigo_unidade
        ORDER BY data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
compras AS (
    SELECT c.*,
           -- Termo "Compra provavelmente sem resultado" (specs/marts.md).
           c.situacao_compra_id = 1
           AND c.data_abertura_proposta IS NOT NULL
           AND r.data_referencia - CAST(c.data_encerramento_proposta AS DATE) > 90
           AND c.valor_total_homologado IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM refined.contratos k
               WHERE k.ligacao_compra = 'compra_encontrada'
                 AND k.numero_controle_pncp_compra = c.numero_controle_pncp
           ) AS provavel_sem_resultado
    FROM refined.contratacoes c
    CROSS JOIN marts.referencia r
),
por_ano AS (
    SELECT unidade_codigo_unidade AS unidade_codigo,
           year(data_publicacao_pncp) AS ano,
           count(*) AS compras,
           sum(valor_total_estimado) AS valor_estimado,
           coalesce(sum(valor_total_homologado), 0) AS valor_homologado,
           count(*) FILTER (WHERE situacao_compra_id = 2) AS revogadas,
           count(*) FILTER (WHERE situacao_compra_id = 3) AS anuladas,
           count(*) FILTER (WHERE provavel_sem_resultado) AS provaveis_sem_resultado
    FROM compras
    GROUP BY ALL
)
SELECT p.unidade_codigo,
       p.ano,
       u.unidade_nome,
       u.uf,
       u.municipio,
       u.orgao_cnpj,
       p.compras,
       p.valor_estimado,
       p.valor_homologado,
       p.revogadas,
       p.anuladas,
       p.provaveis_sem_resultado,
       p.revogadas / p.compras AS taxa_revogadas,
       p.anuladas / p.compras AS taxa_anuladas,
       p.provaveis_sem_resultado / p.compras AS taxa_provaveis_sem_resultado
FROM por_ano p
JOIN unidades u USING (unidade_codigo)
ORDER BY p.unidade_codigo, p.ano;
