-- Grão: marts.compras_por_modalidade, uma linha por modalidade e ano de publicação;
--       marts.contratos_por_categoria, uma linha por categoria do processo e ano de publicação.
-- Perguntas: por qual modalidade a FAB compra, de que tamanho são as compras, quanto tempo há
-- para preparar a proposta e qual desconto costuma sair? Nos contratos, em que categoria?
-- Faixas de valor: limite inferior exclusivo, superior inclusivo.

CREATE OR REPLACE TABLE marts.compras_por_modalidade AS
WITH compras AS (
    SELECT *,
           -- Termo "Desconto" (specs/marts.md); nulo fora das compras elegíveis.
           CASE
               WHEN valor_total_estimado > 0 AND valor_total_homologado > 0
                    AND modalidade_id IS DISTINCT FROM 12
               THEN CAST(valor_total_estimado - valor_total_homologado AS DOUBLE)
                    / CAST(valor_total_estimado AS DOUBLE)
           END AS desconto
    FROM refined.contratacoes
)
SELECT modalidade_id,
       year(data_publicacao_pncp) AS ano,
       any_value(modalidade_nome ORDER BY data_publicacao_pncp DESC) AS modalidade_nome,
       count(*) AS compras,
       sum(valor_total_estimado) AS valor_estimado,
       coalesce(sum(valor_total_homologado), 0) AS valor_homologado,
       CAST(
           sum(valor_total_estimado) / nullif(count(*) FILTER (WHERE valor_total_estimado > 0), 0)
           AS DECIMAL(18, 2)
       ) AS ticket_medio,
       count(*) FILTER (WHERE valor_total_estimado = 0) AS faixa_estimado_zero,
       count(*) FILTER (WHERE valor_total_estimado > 0 AND valor_total_estimado <= 50000) AS faixa_ate_50_mil,
       count(*) FILTER (WHERE valor_total_estimado > 50000 AND valor_total_estimado <= 500000) AS faixa_50_mil_a_500_mil,
       count(*) FILTER (WHERE valor_total_estimado > 500000 AND valor_total_estimado <= 5000000) AS faixa_500_mil_a_5_milhoes,
       count(*) FILTER (WHERE valor_total_estimado > 5000000) AS faixa_acima_5_milhoes,
       avg(date_diff('day', CAST(data_publicacao_pncp AS DATE), CAST(data_encerramento_proposta AS DATE)))
           FILTER (WHERE data_abertura_proposta IS NOT NULL) AS prazo_medio_propostas_dias,
       avg(desconto) AS desconto_medio,
       median(desconto) AS desconto_mediano,
       count(desconto) AS compras_com_desconto
FROM compras
GROUP BY modalidade_id, year(data_publicacao_pncp)
ORDER BY modalidade_id, ano;

CREATE OR REPLACE TABLE marts.contratos_por_categoria AS
SELECT categoria_processo_id,
       year(data_publicacao_pncp) AS ano,
       any_value(categoria_processo_nome ORDER BY data_publicacao_pncp DESC) AS categoria_processo_nome,
       count(*) AS contratos,
       sum(valor_global) AS valor_contratado,
       CAST(sum(valor_global) / nullif(count(*) FILTER (WHERE valor_global > 0), 0) AS DECIMAL(18, 2)) AS ticket_medio,
       count(*) FILTER (WHERE valor_global = 0) AS faixa_valor_zero,
       count(*) FILTER (WHERE valor_global > 0 AND valor_global <= 50000) AS faixa_ate_50_mil,
       count(*) FILTER (WHERE valor_global > 50000 AND valor_global <= 500000) AS faixa_50_mil_a_500_mil,
       count(*) FILTER (WHERE valor_global > 500000 AND valor_global <= 5000000) AS faixa_500_mil_a_5_milhoes,
       count(*) FILTER (WHERE valor_global > 5000000) AS faixa_acima_5_milhoes
FROM refined.contratos
GROUP BY categoria_processo_id, year(data_publicacao_pncp)
ORDER BY categoria_processo_id, ano;
