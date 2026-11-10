"""Regras de anomalia num DuckDB em memória, com dados falsos: sem internet e sem o banco do projeto."""

import json
from datetime import date

import duckdb
import pytest
from conftest import CNPJ_MATRIZ, contratacao_falsa, contrato_falso

from pipeline.anomalias import REGRAS, registrar_anomalias
from pipeline.refinamento import (
    LinhaRaw,
    ler_registro,
    linhas_contratacoes,
    linhas_contratos,
)
from pipeline.transformacao import TABELAS, gravar

FILIAL = "00394429018824"
COMPRA = f"{CNPJ_MATRIZ}-1-000001/2024"


def linha(registro: dict) -> LinhaRaw:
    return LinhaRaw(ler_registro(json.dumps(registro)), "h", "2026-11-08T00:00:00-03:00", "exec")


def anomalias(contratacoes=(), contratos=()) -> list[tuple[str, str, str]]:
    """(regra, chave, descricao) de cada anomalia sobre a refined montada com os registros."""
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE SCHEMA refined")
        compras, fontes = linhas_contratacoes([linha(r) for r in contratacoes])
        chaves = {c["numero_controle_pncp"] for c in compras}
        contratos_ = linhas_contratos(
            [linha(r) for r in contratos], chaves, (CNPJ_MATRIZ, FILIAL), CNPJ_MATRIZ, date(2023, 1, 1)
        )
        for tabela, valores in (("contratacoes", compras), ("contratacoes_fontes", fontes), ("contratos", contratos_)):
            gravar(con, tabela, TABELAS[tabela], valores)
        registrar_anomalias(con)
        return con.execute("SELECT regra, chave, descricao FROM refined.anomalias").fetchall()
    finally:
        con.close()


def regras(contratacoes=(), contratos=()) -> set[str]:
    return {regra for regra, _, _ in anomalias(contratacoes, contratos)}


def test_registros_padrao_nao_geram_anomalia():
    assert anomalias([contratacao_falsa()], [contrato_falso()]) == []


def test_sao_as_onze_regras_registradas_da_spec():
    assert [r.nome for r in REGRAS] == [
        "publicado_antes_assinatura",
        "assinado_antes_compra_com_disputa",
        "compra_de_ano_posterior",
        "compra_fab_nao_encontrada",
        "vigencia_fim_antes_inicio",
        "vigencia_inicio_antes_assinatura",
        "fornecedor_sem_nome",
        "ano_compra_futuro",
        "homologado_acima_estimado",
        "abertura_antes_publicacao",
        "encerramento_antes_abertura",
    ]


# --- contratos -------------------------------------------------------------------


def test_publicado_antes_assinatura():
    contrato = contrato_falso(dataPublicacaoPncp="2024-03-31T23:00:00")
    assert anomalias([contratacao_falsa()], [contrato]) == [
        (
            "publicado_antes_assinatura",
            f"{CNPJ_MATRIZ}-2-000001/2024",
            "publicado em 2024-03-31, assinado em 2024-04-01",
        )
    ]


def test_publicado_no_dia_da_assinatura_nao_dispara():
    contrato = contrato_falso(dataPublicacaoPncp="2024-04-01T00:00:00")
    assert regras([contratacao_falsa()], [contrato]) == set()


def assinado_em(dia: str) -> dict:
    return contrato_falso(dataAssinatura=dia, dataVigenciaInicio=dia)


def test_assinado_antes_compra_com_disputa():
    # A compra padrão tem disputa e foi publicada em 2024-03-01.
    assert regras([contratacao_falsa()], [assinado_em("2024-02-28")]) == {
        "assinado_antes_compra_com_disputa"
    }


def test_assinado_antes_compra_sem_disputa_nao_dispara():
    compra = contratacao_falsa(dataAberturaProposta=None, dataEncerramentoProposta=None)
    assert regras([compra], [assinado_em("2024-02-28")]) == set()


def test_assinado_no_dia_da_publicacao_da_compra_nao_dispara():
    assert regras([contratacao_falsa()], [assinado_em("2024-03-01")]) == set()


def test_compra_de_ano_posterior_compara_com_a_assinatura():
    compra = contratacao_falsa(f"{CNPJ_MATRIZ}-1-000001/2025", anoCompra=2025, dataPublicacaoPncp="2024-12-01T10:00:00",
                               dataAberturaProposta=None, dataEncerramentoProposta=None)
    # anoContrato 2025 igual ao da compra, mas assinado em 2024.
    contrato = contrato_falso(
        compra=f"{CNPJ_MATRIZ}-1-000001/2025", anoContrato=2025,
        dataAssinatura="2024-12-20", dataVigenciaInicio="2024-12-20", dataPublicacaoPncp="2024-12-21T09:00:00",
    )
    assert regras([compra], [contrato]) == {"compra_de_ano_posterior"}


def test_compra_de_ano_posterior_nao_dispara_com_assinatura_no_ano_da_compra():
    compra = contratacao_falsa(f"{CNPJ_MATRIZ}-1-000001/2025", anoCompra=2025, dataPublicacaoPncp="2024-12-01T10:00:00",
                               dataAberturaProposta=None, dataEncerramentoProposta=None)
    # anoContrato 2024 diferente, mas a assinatura é de 2025.
    contrato = contrato_falso(
        compra=f"{CNPJ_MATRIZ}-1-000001/2025", anoContrato=2024,
        dataAssinatura="2025-01-10", dataVigenciaInicio="2025-01-10", dataPublicacaoPncp="2025-01-11T09:00:00",
    )
    assert regras([compra], [contrato]) == set()


def test_compra_fab_nao_encontrada():
    contrato = contrato_falso(compra=f"{FILIAL}-1-000050/2024")
    assert anomalias([], [contrato]) == [
        (
            "compra_fab_nao_encontrada",
            f"{CNPJ_MATRIZ}-2-000001/2024",
            f"compra {FILIAL}-1-000050/2024 ausente da refined",
        )
    ]


def test_compra_fab_anterior_ao_periodo_nao_e_anomalia():
    assert regras([], [contrato_falso(compra=f"{FILIAL}-1-000050/2022")]) == set()


def test_vigencia_fim_antes_inicio():
    assert regras([contratacao_falsa()], [contrato_falso(dataVigenciaFim="2024-03-31")]) == {
        "vigencia_fim_antes_inicio"
    }


def test_vigencia_fim_no_dia_do_inicio_nao_dispara():
    assert regras([contratacao_falsa()], [contrato_falso(dataVigenciaFim="2024-04-01")]) == set()


def test_vigencia_inicio_31_dias_antes_da_assinatura_dispara():
    # Assinatura em 2024-04-01; março tem 31 dias.
    assert anomalias([contratacao_falsa()], [contrato_falso(dataVigenciaInicio="2024-03-01")]) == [
        (
            "vigencia_inicio_antes_assinatura",
            f"{CNPJ_MATRIZ}-2-000001/2024",
            "vigência a partir de 2024-03-01, assinado em 2024-04-01 (31 dias depois)",
        )
    ]


def test_vigencia_inicio_30_dias_antes_da_assinatura_nao_dispara():
    assert regras([contratacao_falsa()], [contrato_falso(dataVigenciaInicio="2024-03-02")]) == set()


def test_fornecedor_sem_nome():
    assert anomalias([contratacao_falsa()], [contrato_falso(nomeRazaoSocialFornecedor="  ")]) == [
        (
            "fornecedor_sem_nome",
            f"{CNPJ_MATRIZ}-2-000001/2024",
            "nome do fornecedor nulo, tipo de pessoa PJ",
        )
    ]


def test_fornecedor_com_nome_nao_dispara():
    assert regras([contratacao_falsa()], [contrato_falso(nomeRazaoSocialFornecedor="EMPRESA X")]) == set()


# --- contratações ---------------------------------------------------------------------


def publicada_em(momento: str, **campos) -> dict:
    return contratacao_falsa(
        dataPublicacaoPncp=momento, dataAberturaProposta=None, dataEncerramentoProposta=None, **campos
    )


def test_ano_compra_futuro_ate_31_de_agosto():
    compra = publicada_em("2024-08-31T23:59:59", anoCompra=2025)
    assert anomalias([compra]) == [
        ("ano_compra_futuro", COMPRA, "compra de 2025, publicada em 2024-08-31")
    ]


def test_ano_compra_futuro_de_setembro_em_diante_e_planejamento():
    assert regras([publicada_em("2024-09-01T00:00:00", anoCompra=2025)]) == set()


def test_ano_compra_anterior_a_publicacao_nao_e_anomalia():
    assert regras([publicada_em("2024-03-01T10:00:00", anoCompra=2023)]) == set()


def test_homologado_acima_estimado():
    compra = contratacao_falsa(valorTotalEstimado=1000.5, valorTotalHomologado=1000.51)
    assert anomalias([compra]) == [
        ("homologado_acima_estimado", COMPRA, "homologado 1000.51, estimado 1000.5")
    ]


@pytest.mark.parametrize(
    "campos",
    [
        {"valorTotalEstimado": 1000.5, "valorTotalHomologado": 1000.5},
        {"valorTotalEstimado": 1000.5, "valorTotalHomologado": 2000.0, "modalidadeId": 12,
         "modalidadeNome": "Credenciamento"},
        {"valorTotalEstimado": 0.0, "valorTotalHomologado": 500.0},
        {"valorTotalEstimado": 1000.5, "valorTotalHomologado": None},
    ],
    ids=["igual", "credenciamento", "estimado_zero", "sem_homologado"],
)
def test_homologado_acima_estimado_nao_dispara(campos):
    assert regras([contratacao_falsa(**campos)]) == set()


def test_abertura_antes_publicacao():
    compra = contratacao_falsa(dataAberturaProposta="2024-02-29T08:00:00")
    assert regras([compra]) == {"abertura_antes_publicacao"}


def test_abertura_no_dia_da_publicacao_nao_dispara():
    # Publicação às 10h; abertura às 8h do mesmo dia: a regra compara o dia.
    compra = contratacao_falsa(dataAberturaProposta="2024-03-01T08:00:00")
    assert regras([compra]) == set()


def test_encerramento_antes_abertura():
    compra = contratacao_falsa(dataEncerramentoProposta="2024-03-05T07:59:59")
    assert regras([compra]) == {"encerramento_antes_abertura"}


def test_encerramento_no_momento_da_abertura_nao_dispara():
    compra = contratacao_falsa(dataEncerramentoProposta="2024-03-05T08:00:00")
    assert regras([compra]) == set()


def test_pratica_normal_nao_entra():
    # Valor global zero e global menor que o inicial estão na lista de prática normal.
    contrato = contrato_falso(valorGlobal=0.0, numeroRetificacao=3)
    assert regras([contratacao_falsa()], [contrato]) == set()
