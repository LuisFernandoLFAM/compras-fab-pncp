-- Grão: uma linha por unidade e ano de publicação, onde houve dispensa (modalidade 8).
-- Pergunta: quais unidades fazem dispensas com disputa, em que volume e com que desconto?
-- Dispensa com disputa: modalidade 8 com data_abertura_proposta preenchida.

CREATE OR REPLACE TABLE marts.dispensas_com_disputa AS
WITH unidades AS (
    SELECT unidade_codigo_unidade AS unidade_codigo,
           unidade_nome_unidade AS unidade_nome,
           unidade_uf_sigla AS uf
    FROM refined.contratacoes
    QUALIFY row_number() OVER (
        PARTITION BY unidade_codigo_unidade
        ORDER BY data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
dispensas AS (
    SELECT *,
           data_abertura_proposta IS NOT NULL AS com_disputa,
           -- Termo "Desconto" (specs/marts.md); a modalidade 8 nunca é credenciamento.
           CASE
               WHEN data_abertura_proposta IS NOT NULL
                    AND valor_total_estimado > 0 AND valor_total_homologado > 0
               THEN CAST(valor_total_estimado - valor_total_homologado AS DOUBLE)
                    / CAST(valor_total_estimado AS DOUBLE)
           END AS desconto
    FROM refined.contratacoes
    WHERE modalidade_id = 8
),
agregado AS (
    SELECT unidade_codigo_unidade AS unidade_codigo,
           year(data_publicacao_pncp) AS ano,
           count(*) AS dispensas,
           count(*) FILTER (WHERE com_disputa) AS dispensas_com_disputa,
           coalesce(sum(valor_total_estimado) FILTER (WHERE com_disputa), 0) AS valor_estimado,
           coalesce(sum(valor_total_homologado) FILTER (WHERE com_disputa), 0) AS valor_homologado,
           avg(desconto) AS desconto_medio,
           median(desconto) AS desconto_mediano,
           count(desconto) AS compras_com_desconto
    FROM dispensas
    GROUP BY ALL
)
SELECT a.unidade_codigo,
       a.ano,
       u.unidade_nome,
       u.uf,
       a.dispensas,
       a.dispensas_com_disputa,
       a.dispensas_com_disputa / a.dispensas AS participacao_com_disputa,
       a.valor_estimado,
       a.valor_homologado,
       a.desconto_medio,
       a.desconto_mediano,
       a.compras_com_desconto
FROM agregado a
JOIN unidades u USING (unidade_codigo)
ORDER BY a.unidade_codigo, a.ano;
