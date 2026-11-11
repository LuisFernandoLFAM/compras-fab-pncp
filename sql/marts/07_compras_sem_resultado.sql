-- Grão: uma linha por unidade, modalidade e ano de publicação, só onde há compras elegíveis
-- (divulgadas no PNCP, com disputa e propostas encerradas há mais de 90 dias da data de referência).
-- Pergunta: onde as compras com disputa costumam terminar sem resultado?

CREATE OR REPLACE TABLE marts.compras_sem_resultado AS
WITH unidades AS (
    SELECT unidade_codigo_unidade AS unidade_codigo, unidade_nome_unidade AS unidade_nome
    FROM refined.contratacoes
    QUALIFY row_number() OVER (
        PARTITION BY unidade_codigo_unidade
        ORDER BY data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
elegiveis AS (
    SELECT c.*,
           -- Termo "Compra provavelmente sem resultado" (specs/marts.md), sobre as elegíveis.
           c.valor_total_homologado IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM refined.contratos k
               WHERE k.ligacao_compra = 'compra_encontrada'
                 AND k.numero_controle_pncp_compra = c.numero_controle_pncp
           ) AS provavel_sem_resultado
    FROM refined.contratacoes c
    CROSS JOIN marts.referencia r
    WHERE c.situacao_compra_id = 1
      AND c.data_abertura_proposta IS NOT NULL
      AND r.data_referencia - CAST(c.data_encerramento_proposta AS DATE) > 90
),
agregado AS (
    SELECT unidade_codigo_unidade AS unidade_codigo,
           modalidade_id,
           year(data_publicacao_pncp) AS ano,
           any_value(modalidade_nome ORDER BY data_publicacao_pncp DESC) AS modalidade_nome,
           count(*) AS compras_elegiveis,
           count(*) FILTER (WHERE provavel_sem_resultado) AS provaveis_sem_resultado,
           coalesce(sum(valor_total_estimado) FILTER (WHERE provavel_sem_resultado), 0)
               AS valor_estimado_provaveis_sem_resultado
    FROM elegiveis
    GROUP BY unidade_codigo_unidade, modalidade_id, year(data_publicacao_pncp)
)
SELECT a.unidade_codigo,
       a.modalidade_id,
       a.ano,
       u.unidade_nome,
       a.modalidade_nome,
       a.compras_elegiveis,
       a.provaveis_sem_resultado,
       a.provaveis_sem_resultado / a.compras_elegiveis AS taxa_provaveis_sem_resultado,
       a.valor_estimado_provaveis_sem_resultado
FROM agregado a
JOIN unidades u USING (unidade_codigo)
ORDER BY a.unidade_codigo, a.modalidade_id, a.ano;
