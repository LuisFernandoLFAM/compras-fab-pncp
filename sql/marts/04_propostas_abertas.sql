-- Grão: uma linha por compra com proposta aberta (encerramento posterior à data de referência).
-- Pergunta: o que está aberto agora e até quando dá para enviar proposta?

CREATE OR REPLACE TABLE marts.propostas_abertas AS
SELECT c.numero_controle_pncp,
       c.unidade_codigo_unidade AS unidade_codigo,
       c.unidade_nome_unidade AS unidade_nome,
       c.unidade_uf_sigla AS uf,
       c.unidade_municipio_nome AS municipio,
       c.modalidade_nome,
       c.objeto_compra,
       c.valor_total_estimado AS valor_estimado,
       c.data_publicacao_pncp,
       c.data_encerramento_proposta,
       date_diff('day', r.data_referencia, CAST(c.data_encerramento_proposta AS DATE)) AS dias_para_encerrar,
       c.link_sistema_origem,
       s.segmento
FROM refined.contratacoes c
CROSS JOIN marts.referencia r
JOIN marts.segmento_objeto s ON s.tabela = 'contratacoes' AND s.chave = c.numero_controle_pncp
WHERE CAST(c.data_encerramento_proposta AS DATE) > r.data_referencia
ORDER BY c.data_encerramento_proposta, c.numero_controle_pncp;
