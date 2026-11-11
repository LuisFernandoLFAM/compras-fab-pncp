-- Grão: uma linha.
-- Perguntas: quanto a FAB comprou no ano, o que pede ação agora, qual desconto costuma sair, quão
-- concentrado é o mercado e de quando é o dado? Números dos cartões e da saúde do dado do painel
-- (specs/painel.md), que não calcula nada na tela. Roda por último: lê os marts 04, 05 e 06.

CREATE OR REPLACE TABLE marts.kpis AS
WITH ano AS (
    SELECT count(*) AS compras_ano,
           coalesce(sum(c.valor_total_estimado), 0) AS valor_estimado_ano,
           -- Termo "Desconto" (specs/marts.md).
           median(
               CASE
                   WHEN c.valor_total_estimado > 0 AND c.valor_total_homologado > 0
                        AND c.modalidade_id IS DISTINCT FROM 12
                   THEN CAST(c.valor_total_estimado - c.valor_total_homologado AS DOUBLE)
                        / CAST(c.valor_total_estimado AS DOUBLE)
               END
           ) AS desconto_mediano_ano,
           count(*) FILTER (
               WHERE c.valor_total_estimado > 0 AND c.valor_total_homologado > 0
                 AND c.modalidade_id IS DISTINCT FROM 12
           ) AS compras_com_desconto_ano
    FROM refined.contratacoes c
    CROSS JOIN marts.referencia r
    WHERE year(c.data_publicacao_pncp) = year(r.data_referencia)
)
SELECT r.data_referencia,
       year(r.data_referencia) AS ano_referencia,
       (SELECT max(fim) FROM raw.execucoes WHERE rodada_id = r.rodada_ingestao) AS extraido_em,
       greatest(
           (SELECT max(data_publicacao_pncp) FROM refined.contratacoes),
           (SELECT max(data_publicacao_pncp) FROM refined.contratos)
       ) AS publicacao_mais_recente,
       a.compras_ano,
       a.valor_estimado_ano,
       (SELECT count(*) FROM marts.propostas_abertas) AS propostas_abertas,
       (SELECT coalesce(sum(valor_estimado), 0) FROM marts.propostas_abertas) AS valor_estimado_propostas_abertas,
       (SELECT count(*) FROM marts.contratos_a_vencer WHERE faixa_vencimento = 'ate_3_meses')
           AS contratos_a_vencer_3_meses,
       (SELECT coalesce(sum(valor_global), 0) FROM marts.contratos_a_vencer WHERE faixa_vencimento = 'ate_3_meses')
           AS valor_a_vencer_3_meses,
       a.desconto_mediano_ano,
       a.compras_com_desconto_ano,
       f.fornecedores,
       f.fornecedores_80_por_cento
FROM marts.referencia r
CROSS JOIN ano a
CROSS JOIN marts.fornecedores_resumo f;
