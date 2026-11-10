"""Fluxo da transformação sobre uma raw falsa num DuckDB temporário.

Nada aqui chama a API nem abre o banco do projeto.
"""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import CNPJ_MATRIZ, contratacao_falsa, contrato_falso

from pipeline import banco, transformacao
from pipeline.processamento import hash_registro, texto_registro

FILIAL = "00394429018824"
COMPRA = f"{CNPJ_MATRIZ}-1-000001/2024"


@pytest.fixture
def cfg_teste(cfg):
    return replace(cfg, cnpjs=(CNPJ_MATRIZ, FILIAL), matriz=CNPJ_MATRIZ, data_inicial=date(2023, 1, 1))


@pytest.fixture
def con(cfg_teste):
    con = banco.conectar(cfg_teste.banco)
    banco.criar_tabelas(con, ["contratacoes", "contratos"])
    yield con
    con.close()


def inserir_raw(con, tabela: str, *registros: dict, extraido_em: str = "2026-11-08T00:00:00-03:00"):
    linhas = [
        {
            "registro": texto_registro(r),
            "_hash": hash_registro(r),
            "_endpoint": tabela,
            "_modalidade": None,
            "_janela_inicio": "2024-01-01",
            "_janela_fim": "2024-01-31",
            "_pagina": "1",
            "_arquivo_origem": "pagina_001.json",
            "_extraido_em": extraido_em,
            "_execucao_id": "rodada-1-cnpj",
        }
        for r in registros
    ]
    banco.inserir_linhas(con, tabela, linhas)


def registrar_rodada(con, rodada: str, status: dict[str, str], inicio: datetime):
    for cnpj, situacao in status.items():
        execucao_id = f"{rodada}-{cnpj}"
        banco.abrir_execucao(con, execucao_id, "completa", inicio, date(2026, 11, 7), cnpj, rodada)
        banco.fechar_execucao(
            con, execucao_id, status=situacao, dados_ate=date(2026, 11, 7), chamadas_api=0,
            linhas_novas=0, linhas_ja_existentes=0, mb_landing=0.0, mensagem_erro=None,
        )


def rodada_ok(con, cfg):
    registrar_rodada(con, "r1", dict.fromkeys(cfg.cnpjs, "sucesso"), datetime(2026, 11, 8, 10).astimezone())


def raw_padrao(con):
    fonte = {"codigo": 1, "nome": "Tesouro", "descricao": "Recursos", "dataInclusao": "2026-06-01T00:00:00"}
    inserir_raw(
        con, "contratacoes",
        contratacao_falsa(COMPRA, fontesOrcamentarias=[fonte]),
        contratacao_falsa(f"{FILIAL}-1-000002/2025", valorTotalHomologado=950.1),
    )
    inserir_raw(
        con, "contratos",
        contrato_falso(),
        # Mesma chave, versão mais nova.
        contrato_falso(valorGlobal=1200.0, dataAtualizacaoGlobal="2024-06-01T00:00:00"),
        contrato_falso(f"{CNPJ_MATRIZ}-2-000002/2024", compra=f"{CNPJ_MATRIZ}-1-000099/2022"),
        contrato_falso(f"{CNPJ_MATRIZ}-2-000003/2024", compra="00489828000155-1-000001/2024"),
    )


def execucoes(con):
    return con.execute(
        "SELECT status, rodada_ingestao, linhas_contratacoes, linhas_contratos, linhas_fontes, "
        "linhas_anomalias, avisos, mensagem_erro FROM refined.execucoes ORDER BY inicio"
    ).fetchall()


def tabela_existe(con, tabela: str) -> bool:
    [(n,)] = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'refined' AND table_name = ?",
        [tabela],
    ).fetchall()
    return n == 1


def conteudo(con, tabela: str):
    return con.execute(f"SELECT * FROM refined.{tabela} ORDER BY ALL").fetchall()


# --- sucesso ---------------------------------------------------------------------


def test_sucesso_grava_as_tres_tabelas(con, cfg_teste):
    raw_padrao(con)
    rodada_ok(con, cfg_teste)

    assert transformacao.executar(con, cfg_teste) == 0

    assert execucoes(con) == [("sucesso", "r1", 2, 3, 1, None, 0, None)]
    ligacoes = dict(con.execute("SELECT numero_controle_pncp, ligacao_compra FROM refined.contratos").fetchall())
    assert ligacoes == {
        f"{CNPJ_MATRIZ}-2-000001/2024": "compra_encontrada",
        f"{CNPJ_MATRIZ}-2-000002/2024": "compra_fab_anterior_ao_periodo",
        f"{CNPJ_MATRIZ}-2-000003/2024": "compra_outro_orgao",
    }
    [(global_, parcela, processo, inicio)] = con.execute(
        f"SELECT valor_global, valor_parcela, processo, data_vigencia_inicio FROM refined.contratos "
        f"WHERE numero_controle_pncp = '{CNPJ_MATRIZ}-2-000001/2024'"
    ).fetchall()
    assert global_ == Decimal("1200.00")  # a versão mais nova
    assert parcela == Decimal("75.0208")
    assert processo == "67000.000001/2024-01"
    assert inicio == date(2024, 4, 1)


def test_tipos_da_spec(con, cfg_teste):
    raw_padrao(con)
    rodada_ok(con, cfg_teste)
    transformacao.executar(con, cfg_teste)

    tipos = dict(
        con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'refined' AND table_name = 'contratos'"
        ).fetchall()
    )
    assert tipos["valor_global"] == "DECIMAL(18,2)"
    assert tipos["valor_parcela"] == "DECIMAL(18,4)"
    assert tipos["data_assinatura"] == "DATE"
    assert tipos["data_publicacao_pncp"] == "TIMESTAMP"
    assert tipos["ano_contrato"] == "INTEGER"
    assert tipos["receita"] == "BOOLEAN"
    assert tipos["unidade_codigo_ibge"] == "VARCHAR"
    assert tipos["_extraido_em"] == "TIMESTAMP"


def test_duas_execucoes_geram_tabelas_identicas(con, cfg_teste):
    raw_padrao(con)
    rodada_ok(con, cfg_teste)
    transformacao.executar(con, cfg_teste)
    antes = {t: conteudo(con, t) for t in transformacao.TABELAS}

    assert transformacao.executar(con, cfg_teste) == 0

    assert {t: conteudo(con, t) for t in transformacao.TABELAS} == antes
    assert [e[0] for e in execucoes(con)] == ["sucesso", "sucesso"]


def test_compra_fab_nao_encontrada_avisa_e_nao_para(con, cfg_teste, caplog):
    inserir_raw(con, "contratacoes", contratacao_falsa())
    inserir_raw(con, "contratos", contrato_falso(compra=f"{FILIAL}-1-000050/2024"))
    rodada_ok(con, cfg_teste)

    assert transformacao.executar(con, cfg_teste) == 0

    assert conteudo(con, "contratos")[0][-4] == "compra_fab_nao_encontrada"
    assert execucoes(con)[0][6] == 1  # avisos
    assert "1 contratos apontam para compra da FAB" in caplog.text


# --- pré-condição --------------------------------------------------------------------


def test_recusa_sem_rodada_de_ingestao(con, cfg_teste):
    raw_padrao(con)

    assert transformacao.executar(con, cfg_teste) == 1

    [execucao] = execucoes(con)
    assert execucao[0] == "falha"
    assert "nenhuma rodada" in execucao[-1]
    assert not tabela_existe(con, "contratos")


def test_recusa_com_cnpj_que_falhou_na_ultima_rodada(con, cfg_teste):
    raw_padrao(con)
    rodada_ok(con, cfg_teste)
    registrar_rodada(
        con, "r2", {CNPJ_MATRIZ: "sucesso", FILIAL: "falha"}, datetime(2026, 11, 9, 10).astimezone()
    )

    assert transformacao.executar(con, cfg_teste) == 1

    [execucao] = execucoes(con)
    assert execucao[1] is None
    assert "(r2)" in execucao[-1] and FILIAL in execucao[-1]


def test_recusa_com_cnpj_sem_linha_na_ultima_rodada(con, cfg_teste):
    raw_padrao(con)
    registrar_rodada(con, "r1", {CNPJ_MATRIZ: "sucesso"}, datetime(2026, 11, 8, 10).astimezone())

    assert transformacao.executar(con, cfg_teste) == 1
    assert FILIAL in execucoes(con)[0][-1]


# --- falha no meio -----------------------------------------------------------------------


def test_valor_que_nao_cabe_mantem_a_refined_anterior(con, cfg_teste):
    raw_padrao(con)
    rodada_ok(con, cfg_teste)
    transformacao.executar(con, cfg_teste)
    antes = {t: conteudo(con, t) for t in transformacao.TABELAS}

    inserir_raw(
        con, "contratos",
        contrato_falso(valorGlobal=10.001, dataAtualizacaoGlobal="2024-07-01T00:00:00"),
        extraido_em="2026-11-09T00:00:00-03:00",
    )
    assert transformacao.executar(con, cfg_teste) == 1

    assert {t: conteudo(con, t) for t in transformacao.TABELAS} == antes
    status, *_, mensagem = execucoes(con)[-1]
    assert status == "falha"
    assert "valor_global" in mensagem and "casas decimais" in mensagem


def test_conferencia_de_somas_desfaz_a_transacao(con, cfg_teste, monkeypatch):
    raw_padrao(con)
    rodada_ok(con, cfg_teste)
    transformacao.executar(con, cfg_teste)
    antes = {t: conteudo(con, t) for t in transformacao.TABELAS}

    original = transformacao.linhas_contratos

    def com_valor_errado(*args, **kwargs):
        linhas = original(*args, **kwargs)
        linhas[0]["valor_global"] = "1.00"
        return linhas

    monkeypatch.setattr(transformacao, "linhas_contratos", com_valor_errado)
    assert transformacao.executar(con, cfg_teste) == 1

    assert {t: conteudo(con, t) for t in transformacao.TABELAS} == antes
    assert "conferência de somas" in execucoes(con)[-1][-1]
