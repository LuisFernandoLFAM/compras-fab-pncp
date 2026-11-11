-- Grão: uma linha por contrato a vencer (fim da vigência posterior à data de referência e até
-- 12 meses depois, inclusive; vigência sem fim fica de fora).
-- Perguntas: quais contratos vencem em 3, 6 e 12 meses, quem os detém e há quanto tempo atende a unidade?
-- Pessoa física e empresário individual: incumbente "Pessoa física" ou "Empresário individual", sem
-- identificador, nome, objeto nem tempo de casa (decisão 5).

CREATE OR REPLACE TABLE marts.contratos_a_vencer AS
WITH nomes AS (
    -- Nome e tipo de pessoa do contrato mais recente de cada fornecedor.
    SELECT ni_fornecedor, nome_razao_social_fornecedor AS nome, tipo_pessoa
    FROM refined.contratos
    WHERE tipo_pessoa IS DISTINCT FROM 'PF' AND NOT fornecedor_empresario_individual
    QUALIFY row_number() OVER (
        PARTITION BY ni_fornecedor
        ORDER BY data_assinatura DESC, data_publicacao_pncp DESC, numero_controle_pncp DESC
    ) = 1
),
na_unidade AS (
    SELECT ni_fornecedor,
           unidade_codigo_unidade,
           min(data_assinatura) AS cliente_desde,
           count(*) AS contratos
    FROM refined.contratos
    WHERE tipo_pessoa IS DISTINCT FROM 'PF' AND NOT fornecedor_empresario_individual
    GROUP BY ALL
),
a_vencer AS (
    SELECT k.*, r.data_referencia,
           CASE
               WHEN k.tipo_pessoa = 'PF' THEN 'Pessoa física'
               WHEN k.fornecedor_empresario_individual THEN 'Empresário individual'
           END AS grupo
    FROM refined.contratos k
    CROSS JOIN marts.referencia r
    WHERE k.data_vigencia_fim > r.data_referencia
      AND k.data_vigencia_fim <= CAST(r.data_referencia + INTERVAL 12 MONTH AS DATE)
)
SELECT v.numero_controle_pncp,
       v.unidade_codigo_unidade AS unidade_codigo,
       v.unidade_nome_unidade AS unidade_nome,
       v.unidade_uf_sigla AS uf,
       v.unidade_municipio_nome AS municipio,
       CASE WHEN v.grupo IS NULL THEN v.objeto_contrato END AS objeto_contrato,
       v.valor_global,
       v.data_vigencia_fim,
       v.data_vigencia_fim - v.data_referencia AS dias_para_vencer,
       CASE
           WHEN v.data_vigencia_fim <= CAST(v.data_referencia + INTERVAL 3 MONTH AS DATE) THEN 'ate_3_meses'
           WHEN v.data_vigencia_fim <= CAST(v.data_referencia + INTERVAL 6 MONTH AS DATE) THEN '3_a_6_meses'
           ELSE '6_a_12_meses'
       END AS faixa_vencimento,
       CASE WHEN v.grupo IS NULL THEN v.ni_fornecedor END AS fornecedor_id,
       coalesce(v.grupo, n.nome) AS fornecedor_nome,
       CASE WHEN v.grupo IS NULL THEN n.tipo_pessoa ELSE v.tipo_pessoa END AS tipo_pessoa,
       u.cliente_desde,
       round((v.data_referencia - u.cliente_desde) / 365.25, 1) AS tempo_de_casa_anos,
       u.contratos AS contratos_do_fornecedor_na_unidade,
       s.segmento
FROM a_vencer v
LEFT JOIN nomes n ON v.grupo IS NULL AND n.ni_fornecedor = v.ni_fornecedor
LEFT JOIN na_unidade u
       ON v.grupo IS NULL
      AND u.ni_fornecedor = v.ni_fornecedor
      AND u.unidade_codigo_unidade = v.unidade_codigo_unidade
JOIN marts.segmento_objeto s ON s.tabela = 'contratos' AND s.chave = v.numero_controle_pncp
ORDER BY v.data_vigencia_fim, v.numero_controle_pncp;
