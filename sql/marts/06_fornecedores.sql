-- Grão: marts.fornecedores, uma linha por fornecedor (ni_fornecedor), com todos os contratos de
--       pessoa física numa linha só ("Pessoa física", sem identificador);
--       marts.fornecedores_resumo, uma linha.
-- Perguntas: quem são os maiores fornecedores da FAB e quão concentrado é o mercado?
-- Valor contratado: soma de valor_global em todos os contratos, qualquer que seja a ligacao_compra.

CREATE OR REPLACE TABLE marts.fornecedores AS
WITH nomes AS (
    SELECT ni_fornecedor, nome_razao_social_fornecedor AS nome, tipo_pessoa
    FROM refined.contratos
    WHERE tipo_pessoa IS DISTINCT FROM 'PF'
    QUALIFY row_number() OVER (
        PARTITION BY ni_fornecedor
        ORDER BY data_assinatura DESC, data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
agregado AS (
    SELECT CASE WHEN tipo_pessoa = 'PF' THEN NULL ELSE ni_fornecedor END AS fornecedor_id,
           tipo_pessoa = 'PF' AS pessoa_fisica,
           count(*) AS contratos,
           sum(valor_global) AS valor_contratado
    FROM refined.contratos
    GROUP BY 1, 2
),
ranking AS (
    SELECT a.*,
           CASE WHEN a.pessoa_fisica THEN 'Pessoa física' ELSE n.nome END AS fornecedor_nome,
           CASE WHEN a.pessoa_fisica THEN 'PF' ELSE n.tipo_pessoa END AS tipo_pessoa,
           row_number() OVER (
               ORDER BY a.valor_contratado DESC, a.contratos DESC, coalesce(a.fornecedor_id, '')
           ) AS posicao
    FROM agregado a
    LEFT JOIN nomes n ON NOT a.pessoa_fisica AND n.ni_fornecedor = a.fornecedor_id
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
