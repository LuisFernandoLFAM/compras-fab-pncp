"""Matriz e filiais (decisão 12), sondagem anual (decisão 1) e migração das execuções antigas.

Fluxo completo do main() com API falsa; landing e banco numa pasta temporária.
"""

import json
from dataclasses import replace
from datetime import date
from typing import ClassVar

import duckdb
import pytest
from conftest import VAZIO, ok

from pipeline import banco, ingestao, landing
from pipeline.api import FalhaAPI
from pipeline.config import validar_cnpjs
from pipeline.processamento import caminho_janela, montar_manifesto

MATRIZ, FILIAL, OUTRA = "00394429000100", "00394429018824", "00394429019715"
COMPLETA_ATE = "2026-10-31"
INCREMENTAL_ATE = "2026-11-05"


class ApiPorCnpj:
    """Só os contratos de outubro de 2026 têm registros; a sondagem responde de acordo."""

    instancias: ClassVar[list["ApiPorCnpj"]] = []
    falha_em: ClassVar[str | None] = None  # CNPJ cuja consulta falha
    falha_na_sondagem: ClassVar[str | None] = None  # endpoint cuja sondagem falha
    falha_na_janela: ClassVar[str | None] = None  # endpoint cujas janelas mensais falham

    def __init__(self, cfg):
        self.cfg = cfg
        self.chamados: list[tuple[str, dict, float | None]] = []
        ApiPorCnpj.instancias.append(self)

    @property
    def chamadas(self) -> int:
        return len(self.chamados)

    def buscar(self, endpoint, parametros, contexto, timeout=None, novas_tentativas=None):
        self.chamados.append((endpoint, parametros, timeout))
        cnpj = parametros.get("cnpj") or parametros.get("cnpjOrgao")
        sondagem = parametros["tamanhoPagina"] == self.cfg.tamanho_pagina_sondagem
        falha = ApiPorCnpj.falha_na_sondagem if sondagem else ApiPorCnpj.falha_na_janela
        if cnpj == ApiPorCnpj.falha_em or endpoint == falha:
            raise FalhaAPI(f"falha persistente em {contexto}: HTTP 500")
        contratos = endpoint in ("/v1/contratos", "/v1/contratos/atualizacao")
        if sondagem:
            return ok("contratos_pagina_unica.json") if contratos and parametros["dataInicial"][:4] == "2026" else VAZIO
        if contratos and parametros["dataInicial"][:6] == "202610":
            return ok("contratos_pagina_unica.json")
        return VAZIO

    def de(self, cnpj):
        return [(e, p, t) for e, p, t in self.chamados if cnpj in (p.get("cnpj"), p.get("cnpjOrgao"))]


class ApiProibida:
    def __init__(self, cfg):
        raise AssertionError("esta execução não pode chamar a API")


@pytest.fixture
def ambiente(cfg, monkeypatch):
    """Período de 2025-11 a 2026-10, só a modalidade 6; `usar(cnpjs)` troca a lista do config."""
    estado = {"cfg": replace(cfg, data_inicial=date(2025, 11, 1), modalidades=(6,), cnpjs=(MATRIZ,))}

    def usar(*cnpjs):
        estado["cfg"] = replace(estado["cfg"], cnpjs=cnpjs)
        return estado["cfg"]

    monkeypatch.setattr(ingestao, "carregar_config", lambda: estado["cfg"])
    monkeypatch.setattr(ingestao, "ClienteAPI", ApiPorCnpj)
    ApiPorCnpj.instancias = []
    ApiPorCnpj.falha_em = ApiPorCnpj.falha_na_sondagem = ApiPorCnpj.falha_na_janela = None
    return usar


def consultar(cfg, sql):
    con = banco.conectar(cfg.banco)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def execucoes(cfg, cnpj):
    return consultar(
        cfg,
        f"SELECT modo, status, dados_ate FROM raw.execucoes WHERE cnpj = '{cnpj}' ORDER BY inicio",
    )


# --- ponto de partida por CNPJ -------------------------------------------------


def test_filial_nova_faz_carga_completa_so_dela(ambiente):
    ambiente(MATRIZ)
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    cfg = ambiente(MATRIZ, FILIAL)
    assert ingestao.main(["--ate", INCREMENTAL_ATE]) == 0

    api = ApiPorCnpj.instancias[-1]
    da_matriz = api.de(MATRIZ)
    assert {e for e, _, _ in da_matriz} == {"/v1/contratacoes/atualizacao", "/v1/contratos/atualizacao"}
    assert {p["dataInicial"] for _, p, _ in da_matriz} == {"20261101"}
    assert {e for e, _, _ in api.de(FILIAL)} == {"/v1/contratacoes/publicacao", "/v1/contratos"}

    assert execucoes(cfg, MATRIZ) == [
        ("completa", "sucesso", date(2026, 10, 31)),
        ("incremental", "sucesso", date(2026, 11, 5)),
    ]
    assert execucoes(cfg, FILIAL) == [("completa", "sucesso", date(2026, 11, 5))]

    # As duas execuções da segunda chamada pertencem à mesma rodada.
    linhas = consultar(cfg, "SELECT execucao_id, cnpj, rodada_id FROM raw.execucoes ORDER BY inicio")
    [(id_m, _, rodada_m), (id_f, _, rodada_f)] = linhas[1:]
    assert rodada_m == rodada_f
    assert (id_m, id_f) == (f"{rodada_m}-{MATRIZ}", f"{rodada_m}-{FILIAL}")


def test_falha_de_um_cnpj_nao_avanca_os_outros(ambiente):
    cfg = ambiente(MATRIZ, FILIAL, OUTRA)
    ApiPorCnpj.falha_em = FILIAL
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 1

    assert execucoes(cfg, MATRIZ) == [("completa", "sucesso", date(2026, 10, 31))]
    assert execucoes(cfg, FILIAL) == [("completa", "falha", date(2026, 10, 31))]
    assert execucoes(cfg, OUTRA) == []  # a rodada parou antes dela
    assert ApiPorCnpj.instancias[-1].de(OUTRA) == []

    ApiPorCnpj.falha_em = None
    assert ingestao.main(["--ate", INCREMENTAL_ATE]) == 0
    api = ApiPorCnpj.instancias[-1]
    assert {e for e, _, _ in api.de(MATRIZ)} == {"/v1/contratacoes/atualizacao", "/v1/contratos/atualizacao"}
    assert {e for e, _, _ in api.de(FILIAL)} == {"/v1/contratacoes/publicacao", "/v1/contratos"}
    assert execucoes(cfg, FILIAL)[-1] == ("completa", "sucesso", date(2026, 11, 5))
    assert execucoes(cfg, OUTRA) == [("completa", "sucesso", date(2026, 11, 5))]


# --- sondagem anual ------------------------------------------------------------


def test_sondagem_pula_os_meses_dos_anos_sem_registros(ambiente):
    cfg = ambiente(FILIAL)
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0

    api = ApiPorCnpj.instancias[-1]
    sondagens = [(e, p, t) for e, p, t in api.chamados if p["tamanhoPagina"] == cfg.tamanho_pagina_sondagem]
    mensais = [(e, p) for e, p, t in api.chamados if p["tamanhoPagina"] == cfg.tamanho_pagina]
    # 2 anos x (modalidade 6 + contratos), com o tempo limite próprio.
    assert len(sondagens) == 4
    assert {t for _, _, t in sondagens} == {cfg.timeout_sondagem}
    assert {(p["dataInicial"], p["dataFinal"]) for _, p, _ in sondagens} == {
        ("20251101", "20251231"), ("20260101", "20261031")
    }
    # Só os contratos de 2026 descem mês a mês: 10 janelas, em vez de 24.
    assert len(mensais) == 10
    assert {e for e, _ in mensais} == {"/v1/contratos"}
    assert {p["dataInicial"][:4] for _, p in mensais} == {"2026"}

    # A sondagem fica na landing como prova, mas não vira janela nem linha na raw.
    pasta = caminho_janela(cfg.landing, "/v1/contratos", FILIAL, None,
                           date(2025, 11, 1), date(2025, 12, 31), "sondagem")
    manifesto = landing.ler_manifesto(pasta)
    assert (manifesto["tipo"], manifesto["total_api"]) == ("sondagem", 0)
    janelas, _ = landing.listar_janelas(cfg.landing)
    assert {m["tipo"] for m in janelas} == {"janela"}
    assert consultar(cfg, "SELECT count(*) FROM raw.contratos") == [(1,)]


def test_sondagem_com_falha_persistente_cai_para_mes_a_mes_sem_pular_nenhum_mes(ambiente, caplog):
    cfg = ambiente(FILIAL)
    ApiPorCnpj.falha_na_sondagem = "/v1/contratos"
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0  # a falha da sondagem não para a execução

    assert execucoes(cfg, FILIAL) == [("completa", "sucesso", date(2026, 10, 31))]
    api = ApiPorCnpj.instancias[-1]
    mensais = [p for e, p, _ in api.chamados
               if e == "/v1/contratos" and p["tamanhoPagina"] == cfg.tamanho_pagina]
    # Os dois anos descem mês a mês: os 12 meses de 2025-11 a 2026-10, nenhum pulado.
    assert [p["dataInicial"] for p in mensais] == [
        "20251101", "20251201", *(f"2026{mes:02d}01" for mes in range(1, 11))
    ]
    # A modalidade 6, cuja sondagem funcionou e deu zero, continua pulada.
    assert not [e for e, p, _ in api.chamados
                if e == "/v1/contratacoes/publicacao" and p["tamanhoPagina"] == cfg.tamanho_pagina]

    # O manifesto registra que o ano foi consultado sem sondagem, com o erro.
    pasta = caminho_janela(cfg.landing, "/v1/contratos", FILIAL, None,
                           date(2025, 11, 1), date(2025, 12, 31), "sondagem")
    manifesto = landing.ler_manifesto(pasta)
    assert manifesto["consultado_sem_sondagem"] is True
    assert manifesto["total_api"] is None
    assert "HTTP 500" in manifesto["erro"]
    assert not list(pasta.glob("pagina_*.json"))
    avisos = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert sum("mês a mês" in a for a in avisos) == 2  # um por ano
    assert consultar(cfg, "SELECT count(*) FROM raw.contratos") == [(1,)]


def test_janela_mensal_com_falha_persistente_continua_parando_a_execucao(ambiente):
    cfg = ambiente(FILIAL)
    ApiPorCnpj.falha_na_janela = "/v1/contratos"
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 1

    [(modo, status, _)] = execucoes(cfg, FILIAL)
    assert (modo, status) == ("completa", "falha")
    [(mensagem,)] = consultar(cfg, "SELECT mensagem_erro FROM raw.execucoes")
    assert "HTTP 500" in mensagem and "janela 2026-01-01_2026-01-31" in mensagem
    # A primeira janela que falhou não ganhou manifesto, e as seguintes não foram consultadas.
    assert not [p for p in cfg.landing.rglob("janela=*") if "contratos" in p.parts]
    mensais = [p for e, p, _ in ApiPorCnpj.instancias[-1].chamados
               if e == "/v1/contratos" and p["tamanhoPagina"] == cfg.tamanho_pagina]
    assert len(mensais) == 1


# --- migração das execuções anteriores à lista de CNPJs --------------------------

ESQUEMA_ANTIGO = """
    CREATE SCHEMA raw;
    CREATE TABLE raw.execucoes (
        execucao_id VARCHAR PRIMARY KEY, modo VARCHAR, inicio TIMESTAMPTZ, fim TIMESTAMPTZ,
        status VARCHAR, dados_ate DATE, chamadas_api INTEGER, linhas_novas INTEGER,
        linhas_ja_existentes INTEGER, mb_landing DOUBLE, mensagem_erro VARCHAR
    );
"""

ANTIGAS = [
    # Extraiu uma janela da filial: o CNPJ sai do manifesto.
    {"execucao_id": "antiga-1", "modo": "completa", "inicio": "2026-11-01T10:00:00.000000-03",
     "fim": "2026-11-01T11:00:00.000000-03", "status": "sucesso", "dados_ate": "2026-10-31",
     "chamadas_api": 1, "linhas_novas": 0, "linhas_ja_existentes": 0, "mb_landing": 0.0,
     "mensagem_erro": None},
    # Nada a consultar, 0 chamadas: sem manifesto, fica com a matriz.
    {"execucao_id": "antiga-2", "modo": "incremental", "inicio": "2026-11-02T10:00:00.000000-03",
     "fim": "2026-11-02T10:00:01.000000-03", "status": "sucesso", "dados_ate": "2026-10-31",
     "chamadas_api": 0, "linhas_novas": 0, "linhas_ja_existentes": 0, "mb_landing": 0.0,
     "mensagem_erro": None},
]


def preparar_landing_antiga(cfg):
    inicio, fim = date(2026, 10, 1), date(2026, 10, 31)
    pasta = caminho_janela(cfg.landing, "/v1/contratos", FILIAL, None, inicio, fim)
    manifesto = montar_manifesto(
        endpoint="/v1/contratos", cnpj=FILIAL, modalidade=None, inicio=inicio, fim=fim,
        total_api=0, total_salvo=0, extracoes=[], execucao_id="antiga-1",
        concluido_em="2026-11-01T11:00:00-03:00",
    )
    del manifesto["tipo"]  # manifestos antigos não têm o campo
    landing.gravar_manifesto(pasta, manifesto)
    for execucao in ANTIGAS:
        landing.acrescentar_execucao(cfg.landing, execucao)


def test_migracao_descobre_o_cnpj_das_execucoes_antigas_pelos_manifestos(ambiente, monkeypatch, caplog):
    # Filial antes da matriz: o resultado não pode depender da ordem do config.toml.
    cfg = ambiente(FILIAL, MATRIZ)
    preparar_landing_antiga(cfg)
    con = duckdb.connect(str(cfg.banco))
    con.execute(ESQUEMA_ANTIGO)
    for e in ANTIGAS:
        con.execute(
            "INSERT INTO raw.execucoes VALUES (?, ?, CAST(? AS TIMESTAMPTZ), CAST(? AS TIMESTAMPTZ), "
            "?, CAST(? AS DATE), ?, ?, ?, ?, ?)",
            [e[c] for c in banco.COLUNAS_EXECUCOES[:11]],
        )
    con.close()

    monkeypatch.setattr(ingestao, "ClienteAPI", ApiProibida)
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0  # os dois CNPJs: nada a consultar

    assert consultar(
        cfg, "SELECT execucao_id, cnpj, rodada_id FROM raw.execucoes WHERE execucao_id LIKE 'antiga%' ORDER BY 1"
    ) == [("antiga-1", FILIAL, "antiga-1"), ("antiga-2", MATRIZ, "antiga-2")]
    avisos = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("antiga-2" in a and MATRIZ in a for a in avisos)
    assert not any("antiga-1" in a for a in avisos)

    # O espelho recebe as execuções antigas já com cnpj e rodada_id.
    espelho = {e["execucao_id"]: e for e in landing.ler_execucoes(cfg.landing)}
    assert (espelho["antiga-1"]["cnpj"], espelho["antiga-2"]["cnpj"]) == (FILIAL, MATRIZ)

    # As execuções novas seguem o histórico migrado de cada CNPJ.
    assert execucoes(cfg, FILIAL)[-1] == ("incremental", "sucesso", date(2026, 10, 31))
    assert execucoes(cfg, MATRIZ)[-1] == ("incremental", "sucesso", date(2026, 10, 31))


def test_reconstrucao_completa_execucoes_antigas_do_espelho(ambiente, monkeypatch):
    cfg = ambiente(MATRIZ, FILIAL)
    preparar_landing_antiga(cfg)  # espelho antigo, sem banco

    monkeypatch.setattr(ingestao, "ClienteAPI", ApiProibida)
    assert ingestao.main(["--reconstruir"]) == 0

    assert consultar(
        cfg, "SELECT execucao_id, cnpj FROM raw.execucoes WHERE execucao_id LIKE 'antiga%' ORDER BY 1"
    ) == [("antiga-1", FILIAL), ("antiga-2", MATRIZ)]
    # Uma linha de reconstrução por CNPJ, cada uma com o dados_ate do próprio CNPJ.
    assert execucoes(cfg, MATRIZ)[-1] == ("reconstrucao", "sucesso", date(2026, 10, 31))
    assert execucoes(cfg, FILIAL)[-1] == ("reconstrucao", "sucesso", date(2026, 10, 31))
    linhas = (cfg.landing / landing.ESPELHO).read_text(encoding="utf-8").splitlines()
    assert all("cnpj" in json.loads(linha) for linha in linhas[len(ANTIGAS):])


# --- configuração ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("cnpjs", "matriz", "erro"),
    [
        ((), MATRIZ, "vazia"),
        ((MATRIZ, "123"), MATRIZ, "14 dígitos"),
        ((MATRIZ, MATRIZ), MATRIZ, "repetido"),
        ((FILIAL,), MATRIZ, "não está na lista"),
    ],
)
def test_lista_de_cnpjs_invalida(cnpjs, matriz, erro):
    with pytest.raises(ValueError, match=erro):
        validar_cnpjs(cnpjs, matriz)


def test_config_do_projeto_tem_matriz_e_sete_filiais(cfg):
    assert cfg.cnpjs[0] == cfg.matriz == MATRIZ
    assert len(cfg.cnpjs) == 8
