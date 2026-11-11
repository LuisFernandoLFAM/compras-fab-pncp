-- Grão: uma linha por ano e mês de publicação no PNCP.
-- Perguntas: quanto a FAB compra por mês e por ano? Em que meses ela compra mais?

CREATE OR REPLACE TABLE marts.compras_mensal AS
WITH compras AS (
    SELECT year(data_publicacao_pncp) AS ano,
           month(data_publicacao_pncp) AS mes,
           count(*) AS compras,
           sum(valor_total_estimado) AS valor_estimado,
           sum(valor_total_homologado) AS valor_homologado,
           count(*) FILTER (WHERE valor_total_estimado = 0) AS compras_estimado_zero,
           count(*) FILTER (WHERE valor_total_homologado IS NULL) AS compras_sem_homologado
    FROM refined.contratacoes
    GROUP BY ALL
),
contratos AS (
    SELECT year(data_publicacao_pncp) AS ano,
           month(data_publicacao_pncp) AS mes,
           count(*) AS contratos,
           sum(valor_global) AS valor_contratado
    FROM refined.contratos
    GROUP BY ALL
),
meses AS (
    SELECT ano, mes FROM compras
    UNION
    SELECT ano, mes FROM contratos
),
juntos AS (
    SELECT m.ano,
           m.mes,
           NOT (
               m.ano = year(r.data_referencia) AND m.mes = month(r.data_referencia)
               AND r.data_referencia < last_day(r.data_referencia)
           ) AS mes_completo,
           coalesce(c.compras, 0) AS compras,
           coalesce(c.valor_estimado, 0) AS valor_estimado,
           coalesce(c.valor_homologado, 0) AS valor_homologado,
           coalesce(c.compras_estimado_zero, 0) AS compras_estimado_zero,
           coalesce(c.compras_sem_homologado, 0) AS compras_sem_homologado,
           coalesce(k.contratos, 0) AS contratos,
           coalesce(k.valor_contratado, 0) AS valor_contratado
    FROM meses m
    CROSS JOIN marts.referencia r
    LEFT JOIN compras c USING (ano, mes)
    LEFT JOIN contratos k USING (ano, mes)
)
SELECT *,
       compras / nullif(sum(compras) OVER (PARTITION BY ano), 0) AS participacao_compras_no_ano,
       CAST(valor_estimado AS DOUBLE)
           / nullif(sum(CAST(valor_estimado AS DOUBLE)) OVER (PARTITION BY ano), 0) AS participacao_valor_no_ano
FROM juntos
ORDER BY ano, mes;
