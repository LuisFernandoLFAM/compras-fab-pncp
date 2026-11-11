"""Painel, gráficos e relatório sobre um banco temporário com o cenário dos marts.

Nada aqui chama a API nem abre o banco do projeto.
"""

import re
from dataclasses import replace
from datetime import date, datetime

import duckdb
import pandas as pd
import plotly.graph_objects as go
import pytest
from conftest import CNPJ_MATRIZ
from streamlit.testing.v1 import AppTest
from test_marts import COMPRAS, CONTRATOS, CPF, CPF_MEI, FILIAL, REFERENCIA, inserir_raw

import graficos as g
import painel
import relatorio
from pipeline import banco as banco_raw
from pipeline import marts, transformacao
from pipeline.config import RAIZ_PROJETO, carregar_config


@pytest.fixture(scope="module")
def banco(tmp_path_factory):
    """Arquivo DuckDB com raw falsa, refined e marts; fechado antes dos testes."""
    pasta = tmp_path_factory.mktemp("painel")
    cfg = replace(
        carregar_config(), raiz=pasta, landing=pasta / "landing", banco=pasta / "teste.duckdb",
        cnpjs=(CNPJ_MATRIZ, FILIAL), matriz=CNPJ_MATRIZ, data_inicial=date(2023, 1, 1),
    )
    con = duckdb.connect(str(cfg.banco))
    banco_raw.criar_tabelas(con, ["contratacoes", "contratos"])
    inserir_raw(con, "contratacoes", COMPRAS)
    inserir_raw(con, "contratos", CONTRATOS)
    for cnpj in cfg.cnpjs:
        banco_raw.abrir_execucao(
            con, f"r1-{cnpj}", "completa", datetime(2026, 11, 8, 10).astimezone(), REFERENCIA, cnpj, "r1"
        )
        banco_raw.fechar_execucao(
            con, f"r1-{cnpj}", status="sucesso", dados_ate=REFERENCIA, chamadas_api=0, linhas_novas=0,
            linhas_ja_existentes=0, mb_landing=0.0, mensagem_erro=None,
        )
    assert transformacao.executar(con, cfg) == 0
    assert marts.executar(con) == 0
    con.close()
    return cfg.banco


# --- ler() ----------------------------------------------------------------------------------


def test_ler_fecha_a_conexao(banco):
    painel.ler("SELECT 1", banco=banco)
    # Com a conexão fechada, o arquivo pode ser aberto para escrita.
    duckdb.connect(str(banco)).close()


def test_ler_e_somente_leitura(banco):
    with pytest.raises(duckdb.Error):
        painel.ler("CREATE TABLE marts.intrusa (a INTEGER)", banco=banco)


def test_banco_padrao_aceita_variavel_de_ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("PAINEL_BANCO", str(tmp_path / "x.duckdb"))
    assert painel.banco_padrao() == tmp_path / "x.duckdb"


# --- consultas -----------------------------------------------------------------------------


def test_kpis(banco):
    k = painel.kpis(banco)
    assert (k["compras_ano"], k["propostas_abertas"], k["contratos_a_vencer_3_meses"]) == (6, 1, 1)
    assert k["fornecedores_80_por_cento"] == 2


def test_anos(banco):
    assert painel.anos(banco) == [2026, 2025, 2024]


def test_propostas_abertas_por_segmento(banco):
    assert len(painel.propostas_abertas("todos", banco)) == 1
    assert len(painel.propostas_abertas("ti", banco)) == 1  # ti inclui dados
    assert painel.propostas_abertas("dados", banco)["segmento"].tolist() == ["dados"]


def test_contratos_a_vencer_por_segmento_e_faixa(banco):
    assert len(painel.contratos_a_vencer("todos", banco=banco)) == 4
    assert painel.contratos_a_vencer("ti", banco=banco)["segmento"].tolist() == ["ti"]
    assert len(painel.contratos_a_vencer("todos", ["ate_3_meses"], banco)) == 1


def test_compras_por_unidade_ordena_pelo_valor(banco):
    df = painel.compras_por_unidade(2026, banco)
    assert df["unidade_nome"].tolist() == ["UNIDADE TESTE"]


def test_compras_sem_resultado_aplica_o_minimo_de_elegiveis(banco, monkeypatch):
    assert painel.compras_sem_resultado(2026, banco).empty  # no cenário, no máximo 2 elegíveis
    monkeypatch.setattr(painel, "MINIMO_ELEGIVEIS", 1)
    assert len(painel.compras_sem_resultado(2026, banco)) == 2


def test_nenhuma_consulta_le_identificador_do_fornecedor(banco):
    resultados = [
        painel.propostas_abertas(banco=banco), painel.contratos_a_vencer(banco=banco), painel.fornecedores(banco),
        painel.ti_e_dados_fornecedores(banco),
    ]
    for df in resultados:
        assert not {"fornecedor_id", "ni_fornecedor"} & set(df.columns)


def test_pessoa_fisica_agregada_e_sem_objeto(banco):
    fornecedores = painel.fornecedores(banco)
    assert "Pessoa física" in fornecedores["fornecedor_nome"].tolist()
    assert "Empresário individual" in fornecedores["fornecedor_nome"].tolist()
    agregados = painel.contratos_a_vencer(banco=banco).query(
        "fornecedor_nome in ['Pessoa física', 'Empresário individual']"
    )
    assert len(agregados) == 2
    assert agregados["objeto_contrato"].isna().all() and agregados["cliente_desde"].isna().all()


# --- sinal da extração ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dias", "cor"), [(0, "verde"), (7, "verde"), (8, "amarelo"), (30, "amarelo"), (31, "vermelho")]
)
def test_sinal_da_extracao(dias, cor):
    hoje = date(2026, 12, 31)
    extraido = datetime.combine(hoje - pd.Timedelta(days=dias), datetime.min.time())
    assert painel.sinal_da_extracao(extraido, hoje) == (dias, cor)


# --- gráficos e formatação ----------------------------------------------------------------------


def test_formatacao():
    assert g.reais(11_503_960_145.54) == "R$ 11,5 bi"
    assert g.reais(578_628_791.58) == "R$ 578,6 mi"
    assert g.reais(25_850) == "R$ 25,9 mil"
    assert g.reais(900) == "R$ 900,00"
    assert g.percentual(0.2124) == "21,2%"
    assert g.numero(3151) == "3.151"
    assert g.reais(None) == g.percentual(None) == g.numero(None) == "-"


def test_cartoes_na_ordem_do_rascunho(banco):
    cartoes = g.cartoes(painel.kpis(banco))
    assert [c["titulo"] for c in cartoes] == [
        "Compras em 2026", "Propostas abertas", "Contratos a vencer em 3 meses", "Desconto mediano em 2026",
        "Concentração",
    ]
    assert cartoes[3]["valor"] == "20,0%"


def test_figuras_com_dados(banco):
    figuras = [
        g.fig_compras_mensal(painel.compras_mensal(banco)),
        g.fig_sazonalidade(painel.compras_mensal(banco)),
        g.fig_unidades(painel.compras_por_unidade(2026, banco), 2026),
        g.fig_categorias(painel.contratos_por_categoria(2026, banco), 2026),
        g.fig_pareto(painel.fornecedores(banco)),
        g.fig_sem_resultado(painel.compras_sem_resultado(2026, banco), 2026),
        g.fig_dispensas(painel.dispensas_com_disputa(2025, banco), 2025),
        g.fig_ti_e_dados(painel.ti_e_dados(2026, "ti", banco), 2026, "ti"),
    ]
    assert all(isinstance(f, go.Figure) and f.data for f in figuras)


def test_figuras_sem_linhas_nao_quebram(banco):
    # Um ano sem dados devolve DataFrames vazios.
    g.fig_unidades(painel.compras_por_unidade(1999, banco), 1999)
    g.fig_sem_resultado(painel.compras_sem_resultado(1999, banco), 1999)
    g.fig_dispensas(painel.dispensas_com_disputa(1999, banco), 1999)
    g.fig_ti_e_dados(painel.ti_e_dados(1999, "dados", banco), 1999, "dados")


def test_tabelas_rotuladas(banco):
    contratos = g.tabela_contratos(painel.contratos_a_vencer(banco=banco))
    assert "Incumbente" in contratos.columns
    assert set(contratos["Faixa"]) == {"até 3 meses", "3 a 6 meses", "6 a 12 meses"}


def test_toda_secao_tem_notas_de_leitura():
    assert set(g.NOTAS) == {"quando_agir", "dinheiro", "contra_quem", "espaco", "ti_e_dados"}
    assert all(g.NOTAS.values())


# --- relatório ----------------------------------------------------------------------------------


def test_relatorio_autocontido(banco, tmp_path):
    destino = relatorio.gerar(banco, tmp_path / "docs" / "relatorio.html", hoje=date(2026, 11, 10))
    texto = destino.read_text(encoding="utf-8")
    assert "dados até 07/11/2026" in texto
    for secao in ("Quando agir", "Onde está o dinheiro", "Contra quem", "Onde há espaço", "TI e dados"):
        assert f"<h2>{secao}</h2>" in texto
    # Plotly embutido uma vez, nada carregado da internet.
    assert texto.count("plotly.js v") >= 1
    assert not re.search(r"<script[^>]+src=", texto)
    assert texto.count("Notas de leitura") == 5


def test_relatorio_sem_pessoa_fisica(banco, tmp_path):
    texto = relatorio.gerar(banco, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "PESSOA FICTICIA" not in texto
    assert CPF not in texto and "456.789" not in texto
    assert "Serviço de instrutor" not in texto
    assert "JOAO FICTICIO" not in texto and CPF_MEI not in texto and "654.321" not in texto
    assert "Serviço de pintura" not in texto


# --- app ----------------------------------------------------------------------------------------


def test_app_abre_sem_erro(banco, monkeypatch):
    monkeypatch.setenv("PAINEL_BANCO", str(banco))
    app = AppTest.from_file(str(RAIZ_PROJETO / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception
    assert app.title[0].value == "Compras da FAB no PNCP"
    assert [h.value for h in app.header] == [
        "Quando agir", "Onde está o dinheiro", "Contra quem", "Onde há espaço", "TI e dados",
    ]
    assert app.metric[0].label == "Compras em 2026"
    assert any(b.label == "Recarregar dados" for b in app.button)
