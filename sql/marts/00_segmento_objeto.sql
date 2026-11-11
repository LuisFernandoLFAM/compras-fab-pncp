-- Grão: uma linha por compra (refined.contratacoes) e por contrato (refined.contratos).
-- Segmento do objeto (decisão 4 de specs/marts.md): dados, ti ou outros; dados é subconjunto de ti.
-- Classificação heurística por palavras-chave sobre o objeto sem acento e em minúsculas,
-- com limite de palavra nas duas pontas. "termo" guarda o trecho que casou, para auditoria.

CREATE OR REPLACE TABLE marts.segmento_objeto AS
WITH termos (segmento, ordem, padrao) AS (
    VALUES
        -- dados: a palavra "dados" sozinha nunca classifica
        ('dados', 1, 'business intelligence'),
        ('dados', 2, 'inteligencia de negocios?'),
        ('dados', 3, 'power ?bi'),
        ('dados', 4, 'qlik'),
        ('dados', 5, 'tableau'),
        ('dados', 6, 'bancos? de dados'),
        ('dados', 7, 'sgbd'),
        ('dados', 8, 'analytics'),
        ('dados', 9, 'ciencia de dados'),
        ('dados', 10, 'cientistas? de dados'),
        ('dados', 11, 'engenharia de dados'),
        ('dados', 12, 'engenheiros? de dados'),
        ('dados', 13, 'data ?warehouse'),
        ('dados', 14, 'data ?lake'),
        ('dados', 15, 'etl'),
        ('dados', 16, 'big data'),
        ('dados', 17, 'mineracao de dados'),
        ('dados', 18, 'data science'),
        ('dados', 19, 'governanca de dados'),
        -- ti
        ('ti', 101, 'tecnologias? da informacao'),
        ('ti', 102, 'tecnologias? de informacao'),
        ('ti', 103, 'ti'),
        ('ti', 104, 'tic'),
        ('ti', 105, 'informatica'),
        ('ti', 106, 'fabrica de software'),
        ('ti', 107, 'softwares?'),
        ('ti', 108, 'sistemas? de informacao'),
        ('ti', 109, 'sistemas? informatizados?'),
        ('ti', 110, 'desenvolvimento de sistemas?'),
        ('ti', 111, 'microcomputador(es)?'),
        ('ti', 112, 'computador(es)?'),
        ('ti', 113, 'notebooks?'),
        ('ti', 114, 'desktops?'),
        ('ti', 115, 'servidor(es)? de rede'),
        ('ti', 116, 'storage'),
        ('ti', 117, 'firewall'),
        ('ti', 118, 'seguranca da informacao'),
        ('ti', 119, 'ciberseguranca'),
        ('ti', 120, 'seguranca cibernetica'),
        ('ti', 121, 'antivirus'),
        ('ti', 122, 'computacao em nuvem'),
        ('ti', 123, 'cloud'),
        ('ti', 124, 'data ?center'),
        ('ti', 125, 'rede de computadores'),
        ('ti', 126, 'cabeamento estruturado'),
        ('ti', 127, 'rede logica'),
        ('ti', 128, 'aplicativos?')
),
objetos AS (
    SELECT 'contratacoes' AS tabela, numero_controle_pncp AS chave,
           lower(strip_accents(coalesce(objeto_compra, ''))) AS texto,
           NULL::INTEGER AS categoria_processo_id
    FROM refined.contratacoes
    UNION ALL
    SELECT 'contratos', numero_controle_pncp,
           lower(strip_accents(coalesce(objeto_contrato, ''))),
           categoria_processo_id
    FROM refined.contratos
),
textos AS (
    -- As exclusões valem só para os termos de dados.
    SELECT *,
           regexp_replace(
               texto, '\b(dados bancarios|voz e dados|folha de dados|banco de dados de precos)\b', ' ', 'g'
           ) AS texto_dados
    FROM objetos
),
casamentos AS (
    SELECT o.tabela, o.chave, t.segmento, t.ordem,
           regexp_extract(
               CASE WHEN t.segmento = 'dados' THEN o.texto_dados ELSE o.texto END,
               '\b(' || t.padrao || ')\b', 1
           ) AS termo
    FROM textos o
    JOIN termos t
      ON regexp_matches(
             CASE WHEN t.segmento = 'dados' THEN o.texto_dados ELSE o.texto END,
             '\b(' || t.padrao || ')\b'
         )
),
primeiro AS (
    SELECT * FROM casamentos
    QUALIFY row_number() OVER (PARTITION BY tabela, chave ORDER BY ordem) = 1
)
SELECT o.tabela,
       o.chave,
       coalesce(p.segmento, CASE WHEN o.categoria_processo_id = 3 THEN 'ti' ELSE 'outros' END) AS segmento,
       coalesce(p.termo, CASE WHEN o.categoria_processo_id = 3 THEN 'categoria_processo: Informática (TIC)' END) AS termo
FROM objetos o
LEFT JOIN primeiro p USING (tabela, chave)
ORDER BY o.tabela, o.chave;
