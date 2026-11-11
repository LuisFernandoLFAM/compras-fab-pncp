-- Grão: marts.fornecedores, uma linha por fornecedor (ni_fornecedor), com todos os contratos de
--       pessoa física numa linha só ("Pessoa física") e todos os de empresário individual em
--       outra ("Empresário individual"), as duas sem identificador (decisão 5);
--       marts.fornecedores_resumo, uma linha.
-- Perguntas: quem são os maiores fornecedores da FAB e quão concentrado é o mercado?
-- Valor contratado: soma de valor_global em todos os contratos, qualquer que seja a ligacao_compra.

CREATE OR REPLACE TABLE marts.fornecedores AS
WITH nomes AS (
    SELECT ni_fornecedor, nome_razao_social_fornecedor AS nome, tipo_pessoa
    FROM refined.contratos
    WHERE tipo_pessoa IS DISTINCT FROM 'PF' AND NOT fornecedor_empresario_individual
    QUALIFY row_number() OVER (
        PARTITION BY ni_fornecedor
        ORDER BY data_assinatura DESC, data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
contratos AS (
    SELECT *,
           CASE
               WHEN tipo_pessoa = 'PF' THEN 'Pessoa física'
               WHEN fornecedor_empresario_individual THEN 'Empresário individual'
           END AS grupo
    FROM refined.contratos
),
agregado AS (
    SELECT CASE WHEN grupo IS NULL THEN ni_fornecedor END AS fornecedor_id,
           grupo,
           count(*) AS contratos,
           sum(valor_global) AS valor_contratado
    FROM contratos
    GROUP BY 1, 2
),
ranking AS (
    SELECT a.*,
           coalesce(a.grupo, n.nome) AS fornecedor_nome,
           CASE a.grupo WHEN 'Pessoa física' THEN 'PF' WHEN 'Empresário individual' THEN 'PJ' ELSE n.tipo_pessoa END
               AS tipo_pessoa,
           row_number() OVER (
               ORDER BY a.valor_contratado DESC, a.contratos DESC, coalesce(a.fornecedor_id, a.grupo)
           ) AS posicao
    FROM agregado a
    LEFT JOIN nomes n ON a.grupo IS NULL AND n.ni_fornecedor = a.fornecedor_id
),
pareto AS (
    SELECT *,
           CAST(valor_contratado AS DOUBLE)
               / nullif(sum(CAST(valor_contratado AS DOUBLE)) OVER (), 0) AS participacao,
           CAST(sum(valor_contratado) OVER (ORDER BY posicao ROWS UNBOUNDED PRECEDING) AS DOUBLE)
               / nullif(sum(CAST(valor_contratado AS DOUBLE)) OVER (), 0) AS participacao_acumulada
    FROM ranking
)
SELECT posicao,
       fornecedor_id,
       fornecedor_nome,
       tipo_pessoa,
       contratos,
       valor_contratado,
       participacao,
       participacao_acumulada,
       -- Inclui o fornecedor que cruza os 80%.
       participacao_acumulada - participacao < 0.8 AS ate_80_por_cento
FROM pareto
ORDER BY posicao;

CREATE OR REPLACE TABLE marts.fornecedores_resumo AS
SELECT count(*) AS fornecedores,
       count(*) FILTER (WHERE ate_80_por_cento) AS fornecedores_80_por_cento,
       coalesce(sum(valor_contratado), 0) AS valor_contratado
FROM marts.fornecedores;
