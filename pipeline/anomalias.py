"""Regras de anomalia (spec: specs/transformacao.md, decisão 7): registradas, nunca corrigidas.

Cada regra é uma consulta sobre as tabelas da refined já gravadas, dentro da
mesma transação. As situações de prática normal da spec não entram.
"""

from collections import Counter
from dataclasses import dataclass

import duckdb

MODALIDADE_CREDENCIAMENTO = 12  # código do PNCP
TOLERANCIA_VIGENCIA_DIAS = 30
ULTIMO_MES_FORA_DO_PLANEJAMENTO = 8  # agosto; de setembro a dezembro é planejamento


@dataclass(frozen=True)
class Regra:
    nome: str
    tabela: str  # contratacoes ou contratos; o registro é o alias t
    condicao: str
    descricao: str  # expressão SQL com os valores envolvidos
    juncao: str = ""


ANO_DA_COMPRA = "CAST(split_part(t.numero_controle_pncp_compra, '/', 2) AS INTEGER)"

REGRAS = [
    Regra(
        "publicado_antes_assinatura", "contratos",
        "CAST(t.data_publicacao_pncp AS DATE) < t.data_assinatura",
        "format('publicado em {}, assinado em {}', CAST(t.data_publicacao_pncp AS DATE), t.data_assinatura)",
    ),
    Regra(
        "assinado_antes_compra_com_disputa", "contratos",
        "t.ligacao_compra = 'compra_encontrada' AND c.data_abertura_proposta IS NOT NULL "
        "AND t.data_assinatura < CAST(c.data_publicacao_pncp AS DATE)",
        "format('assinado em {}, compra publicada em {}', t.data_assinatura, "
        "CAST(c.data_publicacao_pncp AS DATE))",
        "JOIN refined.contratacoes c ON c.numero_controle_pncp = t.numero_controle_pncp_compra",
    ),
    Regra(
        "compra_de_ano_posterior", "contratos",
        f"{ANO_DA_COMPRA} > year(t.data_assinatura)",
        f"format('compra de {{}}, assinado em {{}}', {ANO_DA_COMPRA}, t.data_assinatura)",
    ),
    Regra(
        "compra_fab_nao_encontrada", "contratos",
        "t.ligacao_compra = 'compra_fab_nao_encontrada'",
        "format('compra {} ausente da refined', t.numero_controle_pncp_compra)",
    ),
    Regra(
        "vigencia_fim_antes_inicio", "contratos",
        "t.data_vigencia_fim < t.data_vigencia_inicio",
        "format('vigência de {} a {}', t.data_vigencia_inicio, t.data_vigencia_fim)",
    ),
    Regra(
        "vigencia_inicio_antes_assinatura", "contratos",
        f"t.data_assinatura - t.data_vigencia_inicio > {TOLERANCIA_VIGENCIA_DIAS}",
        "format('vigência a partir de {}, assinado em {} ({} dias depois)', t.data_vigencia_inicio, "
        "t.data_assinatura, t.data_assinatura - t.data_vigencia_inicio)",
    ),
    Regra(
        "fornecedor_sem_nome", "contratos",
        "t.nome_razao_social_fornecedor IS NULL",
        "format('nome do fornecedor nulo, tipo de pessoa {}', t.tipo_pessoa)",
    ),
    Regra(
        "ano_compra_futuro", "contratacoes",
        "t.ano_compra > year(t.data_publicacao_pncp) "
        f"AND month(t.data_publicacao_pncp) <= {ULTIMO_MES_FORA_DO_PLANEJAMENTO}",
        "format('compra de {}, publicada em {}', t.ano_compra, CAST(t.data_publicacao_pncp AS DATE))",
    ),
    Regra(
        "homologado_acima_estimado", "contratacoes",
        "t.valor_total_homologado > t.valor_total_estimado AND t.valor_total_estimado > 0 "
        f"AND t.modalidade_id IS DISTINCT FROM {MODALIDADE_CREDENCIAMENTO}",
        "format('homologado {}, estimado {}', t.valor_total_homologado, t.valor_total_estimado)",
    ),
    Regra(
        "abertura_antes_publicacao", "contratacoes",
        "CAST(t.data_abertura_proposta AS DATE) < CAST(t.data_publicacao_pncp AS DATE)",
        "format('publicada em {}, propostas abertas em {}', CAST(t.data_publicacao_pncp AS DATE), "
        "CAST(t.data_abertura_proposta AS DATE))",
    ),
    Regra(
        "encerramento_antes_abertura", "contratacoes",
        "t.data_encerramento_proposta < t.data_abertura_proposta",
        "format('abertura em {}, encerramento em {}', t.data_abertura_proposta, "
        "t.data_encerramento_proposta)",
    ),
]


def registrar_anomalias(con: duckdb.DuckDBPyConnection) -> Counter:
    """Recria refined.anomalias a partir da refined gravada; devolve a contagem por regra."""
    con.execute(
        "CREATE OR REPLACE TABLE refined.anomalias "
        "(tabela VARCHAR, chave VARCHAR, regra VARCHAR, descricao VARCHAR)"
    )
    consultas = " UNION ALL ".join(
        f"SELECT '{r.tabela}' AS tabela, t.numero_controle_pncp AS chave, '{r.nome}' AS regra, "
        f"{r.descricao} AS descricao FROM refined.{r.tabela} t {r.juncao} WHERE {r.condicao}"
        for r in REGRAS
    )
    con.execute(
        f"INSERT INTO refined.anomalias SELECT * FROM ({consultas}) ORDER BY regra, chave"
    ).fetchall()
    contagem = dict(con.execute("SELECT regra, count(*) FROM refined.anomalias GROUP BY regra").fetchall())
    return Counter({r.nome: contagem.get(r.nome, 0) for r in REGRAS})
