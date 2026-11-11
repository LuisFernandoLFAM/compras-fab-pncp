"""Marts num DuckDB em memória, sobre uma raw falsa transformada: sem internet e sem o banco do projeto.

Data de referência do cenário: 2026-11-07 (dados_ate da rodada falsa).
"""

import json
import shutil
from dataclasses import replace
from datetime import date, datetime

import duckdb
import pytest
from conftest import CNPJ_MATRIZ, contratacao_falsa, contrato_falso

from pipeline import banco, marts, transformacao
from pipeline.processamento import hash_registro, texto_registro
from pipeline.refinamento import (
    LinhaRaw,
    ler_registro,
    linhas_contratacoes,
    linhas_contratos,
)

FILIAL = "00394429018824"
REFERENCIA = date(2026, 11, 7)
UNIDADE_2 = {
    "codigoUnidade": "120002", "nomeUnidade": "UNIDADE DOIS", "codigoIbge": "3304557",
    "municipioNome": "Rio de Janeiro", "ufSigla": "RJ", "ufNome": "Rio de Janeiro",
}
X, Y, Z = "11222333000181", "99888777000166", "55444333000122"
CPF = "12345678909"  # inventado, com dígito verificador válido
MEI, CPF_MEI = "33222111000199", "98765432100"  # empresário individual inventado


def compra(seq: int, ano: int, **campos) -> dict:
    return contratacao_falsa(f"{CNPJ_MATRIZ}-1-{seq:06d}/{ano}", anoCompra=ano, sequencialCompra=seq, **campos)


def contrato(seq: int, compra_ref: str = f"{CNPJ_MATRIZ}-1-000099/2022", **campos) -> dict:
    return contrato_falso(f"{CNPJ_MATRIZ}-2-{seq:06d}/2026", compra=compra_ref, **campos)


def com_disputa(publicacao: str, abertura: str, encerramento: str) -> dict:
    return {"dataPublicacaoPncp": publicacao, "dataAberturaProposta": abertura, "dataEncerramentoProposta": encerramento}


COMPRAS = [
    # A: pregão com proposta aberta, objeto de dados.
    compra(1, 2026, objetoCompra="Aquisição de licenças de software Power BI", valorTotalEstimado=100000.0,
           **com_disputa("2026-10-01T10:00:00", "2026-10-05T08:00:00", "2026-11-20T08:00:00")),
    # B: provavelmente sem resultado.
    compra(2, 2026, valorTotalEstimado=1000.5,
           **com_disputa("2026-03-01T10:00:00", "2026-03-05T08:00:00", "2026-03-15T08:00:00")),
    # C: igual à B, mas revogada.
    compra(3, 2026, situacaoCompraId=2, situacaoCompraNome="Revogada", valorTotalEstimado=1000.5,
           **com_disputa("2026-03-01T10:00:00", "2026-03-05T08:00:00", "2026-03-15T08:00:00")),
    # D: homologada com 20% de desconto e contrato ligado.
    compra(4, 2026, valorTotalEstimado=1000.0, valorTotalHomologado=800.0,
           **com_disputa("2026-03-01T10:00:00", "2026-03-05T08:00:00", "2026-03-15T08:00:00")),
    # E: dispensa com disputa, unidade 2, 10% de desconto.
    compra(5, 2025, modalidadeId=8, modalidadeNome="Dispensa", unidadeOrgao=UNIDADE_2,
           valorTotalEstimado=10000.0, valorTotalHomologado=9000.0,
           **com_disputa("2025-06-10T10:00:00", "2025-06-12T08:00:00", "2025-06-20T08:00:00")),
    # F: dispensa sem disputa, unidade 2; "voz e dados" não é dados.
    compra(6, 2025, modalidadeId=8, modalidadeNome="Dispensa", unidadeOrgao=UNIDADE_2,
           objetoCompra="Contratação de link de voz e dados", valorTotalEstimado=2000.0, valorTotalHomologado=2000.0,
           **com_disputa("2025-06-10T10:00:00", None, None)),
    # G: credenciamento com homologado acima do estimado: fora do desconto.
    compra(7, 2026, modalidadeId=12, modalidadeNome="Credenciamento", valorTotalEstimado=1000.0,
           valorTotalHomologado=5000.0,
           **com_disputa("2026-02-01T10:00:00", "2026-02-05T08:00:00", "2026-02-10T08:00:00")),
    # H: estimado zero, sem disputa; "dados" sozinho não classifica.
    compra(8, 2026, modalidadeId=9, modalidadeNome="Inexigibilidade", objetoCompra="Coleta de dados meteorológicos",
           valorTotalEstimado=0.0, **com_disputa("2026-04-01T10:00:00", None, None)),
]

CONTRATOS = [
    # K0: primeiro contrato de X com a unidade 1.
    contrato(0, niFornecedor=X, nomeRazaoSocialFornecedor="FORNECEDOR X ANTIGO", valorGlobal=500.0,
             dataAssinatura="2024-01-10", dataVigenciaInicio="2024-01-10", dataVigenciaFim="2024-12-31",
             dataPublicacaoPncp="2024-01-11T09:00:00"),
    # K1: X, ligado à compra D, vence em até 3 meses.
    contrato(1, f"{CNPJ_MATRIZ}-1-000004/2026", niFornecedor=X, nomeRazaoSocialFornecedor="FORNECEDOR X LTDA",
             valorGlobal=900.0, dataAssinatura="2026-04-01", dataVigenciaInicio="2026-04-01",
             dataVigenciaFim="2027-01-15", dataPublicacaoPncp="2026-04-02T09:00:00"),
    # K2: pessoa física, vence entre 3 e 6 meses.
    contrato(2, tipoPessoa="PF", niFornecedor=CPF, nomeRazaoSocialFornecedor="PESSOA FICTICIA",
             objetoContrato="Serviço de instrutor", valorGlobal=300.0, dataAssinatura="2026-04-01",
             dataVigenciaInicio="2026-04-01", dataVigenciaFim="2027-04-01", dataPublicacaoPncp="2026-04-02T09:00:00"),
    # K3: Y, TI pelo objeto, vence entre 6 e 12 meses.
    contrato(3, niFornecedor=Y, nomeRazaoSocialFornecedor="EMPRESA Y", objetoContrato="Suporte técnico de informática",
             categoriaProcesso={"id": 8, "nome": "Serviços"}, valorGlobal=5000.0, dataAssinatura="2026-05-01",
             dataVigenciaInicio="2026-05-01", dataVigenciaFim="2027-09-01", dataPublicacaoPncp="2026-05-02T09:00:00"),
    # K4: Y, TI pela categoria, vence depois de 12 meses.
    contrato(4, niFornecedor=Y, nomeRazaoSocialFornecedor="EMPRESA Y", objetoContrato="Manutenção predial",
             categoriaProcesso={"id": 3, "nome": "Informática (TIC)"}, valorGlobal=100.0, dataAssinatura="2026-06-01",
             dataVigenciaInicio="2026-06-01", dataVigenciaFim="2028-01-01", dataPublicacaoPncp="2026-06-01T09:00:00"),
    # K5: Z, vigência sem fim, valor zero; "servidores públicos" não é TI.
    contrato(5, niFornecedor=Z, nomeRazaoSocialFornecedor="EMPRESA Z",
             objetoContrato="Pagamento de servidores públicos cedidos", valorInicial=0.0, valorGlobal=0.0,
             valorParcela=0.0, dataAssinatura="2026-06-01", dataVigenciaInicio="2026-06-01", dataVigenciaFim=None,
             dataPublicacaoPncp="2026-06-01T09:00:00"),
    # K6: empresário individual (CPF no nome), vence entre 3 e 6 meses.
    contrato(6, niFornecedor=MEI, nomeRazaoSocialFornecedor=f"JOAO FICTICIO {CPF_MEI}",
             objetoContrato="Serviço de pintura", valorGlobal=250.0, dataAssinatura="2026-07-01",
             dataVigenciaInicio="2026-07-01", dataVigenciaFim="2027-03-01", dataPublicacaoPncp="2026-07-01T09:00:00"),
    # K7: o mesmo fornecedor, num contrato antigo sem CPF no nome.
    contrato(7, niFornecedor=MEI, nomeRazaoSocialFornecedor="JOAO FICTICIO", objetoContrato="Serviço de pintura antigo",
             valorGlobal=100.0, dataAssinatura="2025-03-01", dataVigenciaInicio="2025-03-01",
             dataVigenciaFim="2025-12-31", dataPublicacaoPncp="2025-03-01T09:00:00"),
]


def inserir_raw(con, tabela: str, registros: list[dict]) -> None:
    banco.inserir_linhas(con, tabela, [
        {
            "registro": texto_registro(r), "_hash": hash_registro(r), "_endpoint": tabela, "_modalidade": None,
            "_janela_inicio": "2026-01-01", "_janela_fim": "2026-01-31", "_pagina": "1",
            "_arquivo_origem": "pagina_001.json", "_extraido_em": "2026-11-08T00:00:00-03:00",
            "_execucao_id": f"r1-{CNPJ_MATRIZ}",
        }
        for r in registros
    ])


@pytest.fixture
def con(cfg):
    """Banco em memória com a raw falsa já transformada (refined pronta)."""
    cfg = replace(cfg, cnpjs=(CNPJ_MATRIZ, FILIAL), matriz=CNPJ_MATRIZ, data_inicial=date(2023, 1, 1))
    con = duckdb.connect(":memory:")
    banco.criar_tabelas(con, ["contratacoes", "contratos"])
    inserir_raw(con, "contratacoes", COMPRAS)
    inserir_raw(con, "contratos", CONTRATOS)
    for cnpj in cfg.cnpjs:
        banco.abrir_execucao(con, f"r1-{cnpj}", "completa", datetime(2026, 11, 8, 10).astimezone(), REFERENCIA, cnpj, "r1")
        banco.fechar_execucao(
            con, f"r1-{cnpj}", status="sucesso", dados_ate=REFERENCIA, chamadas_api=0, linhas_novas=0,
            linhas_ja_existentes=0, mb_landing=0.0, mensagem_erro=None,
        )
    assert transformacao.executar(con, cfg) == 0
    yield con
    con.close()


@pytest.fixture
def construido(con):
    assert marts.executar(con) == 0
    return con


def linhas(con, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    nomes = [d[0] for d in cursor.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]


def conteudo(con) -> dict:
    return {t: con.execute(f"SELECT * FROM marts.{t} ORDER BY ALL").fetchall() for t in marts.tabelas_dos_marts(con)}


def compra_chave(seq: int, ano: int) -> str:
    return f"{CNPJ_MATRIZ}-1-{seq:06d}/{ano}"


def contrato_chave(seq: int) -> str:
    return f"{CNPJ_MATRIZ}-2-{seq:06d}/2026"


# --- execução ----------------------------------------------------------------------


def test_registra_execucao_e_referencia(construido):
    [execucao] = linhas(construido, "SELECT * FROM marts.execucoes")
    assert execucao["status"] == "sucesso"
    assert execucao["data_referencia"] == REFERENCIA
    assert execucao["tabelas"] == len(marts.tabelas_dos_marts(construido))
    [referencia] = linhas(construido, "SELECT * FROM marts.referencia")
    assert referencia["data_referencia"] == REFERENCIA
    assert referencia["rodada_ingestao"] == "r1"


def test_duas_execucoes_geram_tabelas_identicas(construido):
    antes = conteudo(construido)
    assert marts.executar(construido) == 0
    assert conteudo(construido) == antes


def test_recusa_sem_transformacao():
    con = duckdb.connect(":memory:")
    assert marts.executar(con) == 1
    [execucao] = linhas(con, "SELECT status, mensagem_erro FROM marts.execucoes")
    assert execucao["status"] == "falha"
    assert "nenhuma transformação" in execucao["mensagem_erro"]


def test_recusa_quando_a_ultima_transformacao_falhou(construido):
    antes = conteudo(construido)
    construido.execute(
        "INSERT INTO refined.execucoes (execucao_id, inicio, status) VALUES ('t2', now(), 'falha')"
    )
    assert marts.executar(construido) == 1
    assert conteudo(construido) == antes
    ultima = linhas(construido, "SELECT status, mensagem_erro FROM marts.execucoes ORDER BY inicio DESC LIMIT 1")[0]
    assert ultima["status"] == "falha" and "(t2)" in ultima["mensagem_erro"]


def test_falha_no_meio_mantem_os_marts_anteriores(construido, tmp_path):
    antes = conteudo(construido)
    pasta = tmp_path / "sql"
    shutil.copytree(marts.PASTA_SQL, pasta)
    (pasta / "99_quebrado.sql").write_text("CREATE TABLE marts.quebrado AS SELECT * FROM nao_existe;", encoding="utf-8")

    assert marts.executar(construido, pasta) == 1

    assert conteudo(construido) == antes
    ultima = linhas(construido, "SELECT mensagem_erro FROM marts.execucoes ORDER BY inicio DESC LIMIT 1")[0]
    assert "99_quebrado.sql" in ultima["mensagem_erro"]


def test_erro_inesperado_registra_falha_sem_engolir(construido, monkeypatch, caplog):
    antes = conteudo(construido)

    def quebrar(con):
        raise RuntimeError("bug de teste")

    monkeypatch.setattr(marts, "conferir", quebrar)
    assert marts.executar(construido) == 1

    assert conteudo(construido) == antes
    ultima = linhas(construido, "SELECT status, mensagem_erro FROM marts.execucoes ORDER BY inicio DESC LIMIT 1")[0]
    assert ultima == {"status": "falha", "mensagem_erro": "RuntimeError: bug de teste"}
    assert any(r.exc_info and r.exc_info[0] is RuntimeError for r in caplog.records)


def test_nenhum_mart_expoe_pessoa_fisica(construido):
    for tabela in marts.tabelas_dos_marts(construido):
        for linha in construido.execute(f"SELECT * FROM marts.{tabela}").fetchall():
            texto = json.dumps(linha, default=str)
            assert "PESSOA FICTICIA" not in texto
            assert "456.789" not in texto and CPF not in texto
            assert "Serviço de instrutor" not in texto
            assert "JOAO FICTICIO" not in texto and CPF_MEI not in texto and "654.321" not in texto
            assert "Serviço de pintura" not in texto


# --- segmento ----------------------------------------------------------------------


def segmentos(con) -> dict[str, tuple[str, str | None]]:
    return {chave: (s, t) for chave, s, t in con.execute("SELECT chave, segmento, termo FROM marts.segmento_objeto").fetchall()}


def test_segmento_no_cenario(construido):
    s = segmentos(construido)
    assert s[compra_chave(1, 2026)] == ("dados", "power bi")
    assert s[compra_chave(6, 2025)] == ("outros", None)
    assert s[compra_chave(8, 2026)] == ("outros", None)
    assert s[contrato_chave(3)] == ("ti", "informatica")
    assert s[contrato_chave(4)] == ("ti", "categoria_processo: Informática (TIC)")
    assert s[contrato_chave(5)] == ("outros", None)


def linha_raw(registro: dict) -> LinhaRaw:
    return LinhaRaw(ler_registro(json.dumps(registro)), "h", "2026-11-08T00:00:00-03:00", "exec")


@pytest.mark.parametrize(
    ("objeto", "segmento", "termo"),
    [
        ("Contratação de solução de Business Intelligence", "dados", "business intelligence"),
        ("Licenças de banco de dados Oracle", "dados", "banco de dados"),
        ("Serviço de ETL e Data Lake", "dados", "data lake"),
        ("Consultoria em Ciência de Dados", "dados", "ciencia de dados"),
        ("Pagamento por dados bancários de fornecedores", "outros", None),
        ("Link de voz e dados", "outros", None),
        ("Impressão de folha de dados técnicos", "outros", None),
        ("Manutenção predial com preços do banco de dados de preços do SINAPI", "outros", None),
        ("Banco de dados de preços e licenças de banco de dados", "dados", "banco de dados"),
        ("Levantamento de dados topográficos", "outros", None),
        ("Aquisição de microcomputadores", "ti", "microcomputadores"),
        ("Serviços de TI", "ti", "ti"),
        ("Tecnologia da Informação e Comunicação", "ti", "tecnologia da informacao"),
        ("Capacitação de servidores", "outros", None),
        ("Servidores de rede e storage", "ti", "servidores de rede"),
        ("Material de construção para tintas", "outros", None),
        ("Voz e dados com firewall", "ti", "firewall"),
    ],
)
def test_regras_de_segmento(objeto, segmento, termo):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA refined")
    con.execute("CREATE SCHEMA marts")
    compras, fontes = linhas_contratacoes([linha_raw(contratacao_falsa(objetoCompra=objeto))])
    contratos_ = linhas_contratos([], set(), (CNPJ_MATRIZ,), CNPJ_MATRIZ, date(2023, 1, 1))
    for tabela, valores in (("contratacoes", compras), ("contratacoes_fontes", fontes), ("contratos", contratos_)):
        transformacao.gravar(con, tabela, transformacao.TABELAS[tabela], valores)
    con.execute((marts.PASTA_SQL / "00_segmento_objeto.sql").read_text(encoding="utf-8"))
    assert con.execute("SELECT segmento, termo FROM marts.segmento_objeto").fetchall() == [(segmento, termo)]


# --- marts -------------------------------------------------------------------------


def test_01_compras_mensal(construido):
    meses = {(m["ano"], m["mes"]): m for m in linhas(construido, "SELECT * FROM marts.compras_mensal")}
    assert meses[(2026, 3)]["compras"] == 3
    assert meses[(2026, 3)]["valor_homologado"] == 800
    assert meses[(2026, 3)]["compras_sem_homologado"] == 2
    assert meses[(2026, 4)]["compras_estimado_zero"] == 1
    assert meses[(2026, 4)]["contratos"] == 2
    assert meses[(2026, 10)]["mes_completo"]
    assert sum(m["compras"] for m in meses.values()) == len(COMPRAS)
    assert sum(m["participacao_compras_no_ano"] for m in meses.values() if m["ano"] == 2026) == pytest.approx(1)


def test_01_mes_da_referencia_incompleto(con):
    # Um contrato publicado no mês da data de referência cria a linha de novembro.
    con.execute("UPDATE refined.contratos SET data_publicacao_pncp = TIMESTAMP '2026-11-05 09:00:00' "
                f"WHERE numero_controle_pncp = '{contrato_chave(5)}'")
    assert marts.executar(con) == 0
    [novembro] = linhas(con, "SELECT mes_completo FROM marts.compras_mensal WHERE ano = 2026 AND mes = 11")
    assert novembro["mes_completo"] is False


def test_02_compras_por_unidade(construido):
    unidade = {(u["unidade_codigo"], u["ano"]): u for u in linhas(construido, "SELECT * FROM marts.compras_por_unidade")}
    u1 = unidade[("120001", 2026)]
    assert (u1["compras"], u1["revogadas"], u1["anuladas"], u1["provaveis_sem_resultado"]) == (6, 1, 0, 1)
    assert u1["taxa_provaveis_sem_resultado"] == pytest.approx(1 / 6)
    u2 = unidade[("120002", 2025)]
    assert (u2["unidade_nome"], u2["uf"], u2["municipio"], u2["compras"]) == ("UNIDADE DOIS", "RJ", "Rio de Janeiro", 2)


def test_03_compras_por_modalidade(construido):
    m = {(r["modalidade_id"], r["ano"]): r for r in linhas(construido, "SELECT * FROM marts.compras_por_modalidade")}
    pregao = m[(6, 2026)]
    assert pregao["compras"] == 4
    assert pregao["desconto_medio"] == pytest.approx(0.2)
    assert pregao["desconto_mediano"] == pytest.approx(0.2)
    assert pregao["compras_com_desconto"] == 1
    assert (pregao["faixa_ate_50_mil"], pregao["faixa_50_mil_a_500_mil"]) == (3, 1)
    assert pregao["prazo_medio_propostas_dias"] == pytest.approx((50 + 14 + 14 + 14) / 4)
    credenciamento = m[(12, 2026)]
    assert credenciamento["desconto_medio"] is None and credenciamento["compras_com_desconto"] == 0
    inexigibilidade = m[(9, 2026)]
    assert inexigibilidade["faixa_estimado_zero"] == 1 and inexigibilidade["ticket_medio"] is None


def test_03_contratos_por_categoria(construido):
    c = {(r["categoria_processo_id"], r["ano"]): r for r in linhas(construido, "SELECT * FROM marts.contratos_por_categoria")}
    assert c[(3, 2026)]["contratos"] == 1
    assert c[(8, 2026)]["valor_contratado"] == 5000
    assert c[(2, 2026)]["faixa_valor_zero"] == 1


def test_04_propostas_abertas(construido):
    [aberta] = linhas(construido, "SELECT * FROM marts.propostas_abertas")
    assert aberta["numero_controle_pncp"] == compra_chave(1, 2026)
    assert aberta["dias_para_encerrar"] == 13
    assert aberta["segmento"] == "dados"
    assert aberta["valor_estimado"] == 100000


def test_05_contratos_a_vencer(construido):
    v = {r["numero_controle_pncp"]: r for r in linhas(construido, "SELECT * FROM marts.contratos_a_vencer")}
    assert set(v) == {contrato_chave(1), contrato_chave(2), contrato_chave(3), contrato_chave(6)}

    k1 = v[contrato_chave(1)]
    assert k1["faixa_vencimento"] == "ate_3_meses"
    assert k1["fornecedor_nome"] == "FORNECEDOR X LTDA"  # nome do contrato mais recente
    assert k1["cliente_desde"] == date(2024, 1, 10)
    assert k1["contratos_do_fornecedor_na_unidade"] == 2
    assert k1["tempo_de_casa_anos"] == pytest.approx(2.8)

    k2 = v[contrato_chave(2)]
    assert k2["faixa_vencimento"] == "3_a_6_meses"
    assert (k2["fornecedor_id"], k2["fornecedor_nome"], k2["tipo_pessoa"]) == (None, "Pessoa física", "PF")
    assert k2["objeto_contrato"] is None and k2["cliente_desde"] is None and k2["tempo_de_casa_anos"] is None

    k6 = v[contrato_chave(6)]
    assert (k6["fornecedor_id"], k6["fornecedor_nome"], k6["tipo_pessoa"]) == (None, "Empresário individual", "PJ")
    assert k6["objeto_contrato"] is None and k6["cliente_desde"] is None and k6["tempo_de_casa_anos"] is None

    k3 = v[contrato_chave(3)]
    assert (k3["faixa_vencimento"], k3["segmento"]) == ("6_a_12_meses", "ti")


def test_06_fornecedores(construido):
    ranking = linhas(construido, "SELECT * FROM marts.fornecedores ORDER BY posicao")
    assert [(f["fornecedor_id"], f["fornecedor_nome"], f["contratos"]) for f in ranking] == [
        (Y, "EMPRESA Y", 2), (X, "FORNECEDOR X LTDA", 2), (None, "Empresário individual", 2),
        (None, "Pessoa física", 1), (Z, "EMPRESA Z", 1),
    ]
    assert [f["ate_80_por_cento"] for f in ranking] == [True, True, False, False, False]
    assert ranking[2]["tipo_pessoa"] == "PJ" and ranking[3]["tipo_pessoa"] == "PF"
    assert ranking[0]["participacao"] == pytest.approx(5100 / 7150)
    assert ranking[-1]["participacao_acumulada"] == pytest.approx(1)
    [resumo] = linhas(construido, "SELECT * FROM marts.fornecedores_resumo")
    assert (resumo["fornecedores"], resumo["fornecedores_80_por_cento"], resumo["valor_contratado"]) == (5, 2, 7150)


def test_07_compras_sem_resultado(construido):
    s = {(r["unidade_codigo"], r["modalidade_id"], r["ano"]): r
         for r in linhas(construido, "SELECT * FROM marts.compras_sem_resultado")}
    # Pregão 2026: B e D são elegíveis (A está aberta; C foi revogada); só B ficou sem resultado.
    pregao = s[("120001", 6, 2026)]
    assert (pregao["compras_elegiveis"], pregao["provaveis_sem_resultado"]) == (2, 1)
    assert pregao["taxa_provaveis_sem_resultado"] == pytest.approx(0.5)
    assert pregao["valor_estimado_provaveis_sem_resultado"] == pytest.approx(1000.5)
    assert s[("120001", 12, 2026)]["provaveis_sem_resultado"] == 0  # G tem homologado
    assert s[("120002", 8, 2025)]["compras_elegiveis"] == 1


def test_08_dispensas_com_disputa(construido):
    [d] = linhas(construido, "SELECT * FROM marts.dispensas_com_disputa")
    assert (d["unidade_codigo"], d["ano"], d["dispensas"], d["dispensas_com_disputa"]) == ("120002", 2025, 2, 1)
    assert d["participacao_com_disputa"] == pytest.approx(0.5)
    assert (d["valor_estimado"], d["valor_homologado"]) == (10000, 9000)
    assert d["desconto_medio"] == pytest.approx(0.1)


def test_09_ti_e_dados(construido):
    t = {(r["segmento"], r["ano"], r["unidade_codigo"]): r for r in linhas(construido, "SELECT * FROM marts.ti_e_dados")}
    ti = t[("ti", 2026, "120001")]
    # A compra de dados entra também em ti.
    assert (ti["compras"], ti["propostas_abertas"], ti["contratos"], ti["valor_contratado"]) == (1, 1, 2, 5100)
    dados = t[("dados", 2026, "120001")]
    assert (dados["compras"], dados["contratos"], dados["valor_estimado_propostas_abertas"]) == (1, 0, 100000)

    fornecedores = linhas(construido, "SELECT * FROM marts.ti_e_dados_fornecedores")
    assert [(f["segmento"], f["posicao"], f["fornecedor_id"]) for f in fornecedores] == [("ti", 1, Y)]
    assert fornecedores[0]["participacao_no_segmento"] == pytest.approx(1)


def test_10_kpis(construido):
    [k] = linhas(construido, "SELECT * FROM marts.kpis")
    assert (k["data_referencia"], k["ano_referencia"]) == (REFERENCIA, 2026)
    assert k["extraido_em"] is not None
    assert k["publicacao_mais_recente"] == datetime(2026, 10, 1, 10, 0)  # compra A
    # Compras de 2026: A, B, C, D, G e H.
    assert (k["compras_ano"], k["valor_estimado_ano"]) == (6, 104001)
    # Só D entra no desconto (G é credenciamento).
    assert (k["desconto_mediano_ano"], k["compras_com_desconto_ano"]) == (pytest.approx(0.2), 1)
    assert (k["propostas_abertas"], k["valor_estimado_propostas_abertas"]) == (1, 100000)
    assert (k["contratos_a_vencer_3_meses"], k["valor_a_vencer_3_meses"]) == (1, 900)
    assert (k["fornecedores"], k["fornecedores_80_por_cento"]) == (5, 2)
