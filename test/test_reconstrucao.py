"""Fluxo completo do main() com API falsa: incremental, reconstrução e banco descartável.

Landing e banco ficam numa pasta temporária; nada aqui chama a API nem abre o
banco do projeto.
"""

import json
from dataclasses import replace
from datetime import date
from typing import ClassVar

import pytest
from conftest import VAZIO, ok

from pipeline import banco, ingestao, landing
from pipeline.api import Resposta
from pipeline.processamento import ClasseResposta, escolher_modo, janela_incremental

COMPLETA_ATE = "2026-10-31"
INCREMENTAL_ATE = "2026-11-05"


def contrato_alterado() -> Resposta:
    pagina = json.loads(ok("contratos_pagina_unica.json").corpo)
    pagina["data"][0]["valorGlobal"] = 120000.0
    return Resposta(ClasseResposta.SUCESSO, json.dumps(pagina).encode(), "2026-11-06T09:00:00-03:00")


class ApiFalsa:
    """Responde conforme endpoint e parâmetros; anota todas as chamadas."""

    instancias: ClassVar[list["ApiFalsa"]] = []

    def __init__(self, cfg):
        self.cfg = cfg
        self.parametros: list[tuple[str, dict]] = []
        ApiFalsa.instancias.append(self)

    @property
    def chamadas(self) -> int:
        return len(self.parametros)

    def buscar(self, endpoint, parametros, contexto, timeout=None, novas_tentativas=None):
        self.parametros.append((endpoint, parametros))
        modalidade = parametros.get("codigoModalidadeContratacao")
        if parametros["tamanhoPagina"] == self.cfg.tamanho_pagina_sondagem:
            # Sondagem anual: só a modalidade 6 e os contratos têm registros.
            if endpoint == "/v1/contratacoes/publicacao" and modalidade == 6:
                return ok("contratacoes_pagina_1.json")
            if endpoint == "/v1/contratos":
                return ok("contratos_pagina_unica.json")
            return VAZIO
        mes = parametros["dataInicial"][:6]
        if endpoint == "/v1/contratacoes/publicacao" and modalidade == 6 and mes == "202609":
            arquivo = ["contratacoes_pagina_1.json", "contratacoes_pagina_2.json"]
            return ok(arquivo[parametros["pagina"] - 1])
        if endpoint == "/v1/contratos" and mes == "202610":
            return ok("contratos_pagina_unica.json")
        if endpoint == "/v1/contratos/atualizacao":
            return contrato_alterado()
        return VAZIO


class ApiProibida:
    def __init__(self, cfg):
        raise AssertionError("a reconstrução não pode chamar a API")


@pytest.fixture
def ambiente(cfg, monkeypatch):
    """Configuração com período e modalidades reduzidos, landing e banco temporários."""
    cfg = replace(cfg, data_inicial=date(2026, 9, 1), modalidades=(6, 8), cnpjs=(cfg.matriz,))
    monkeypatch.setattr(ingestao, "carregar_config", lambda: cfg)
    monkeypatch.setattr(ingestao, "ClienteAPI", ApiFalsa)
    ApiFalsa.instancias = []
    return cfg


def consultar(cfg, sql):
    con = banco.conectar(cfg.banco)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def raw_completa(cfg):
    colunas = ", ".join(banco.COLUNAS_RAW)
    return {
        tabela: sorted(consultar(cfg, f"SELECT {colunas} FROM raw.{tabela}"))
        for tabela in ("contratacoes", "contratos")
    }


def historico(cfg):
    return consultar(cfg, "SELECT execucao_id, modo, status, dados_ate FROM raw.execucoes ORDER BY inicio")


def test_incremental_consulta_a_partir_do_dia_seguinte_pelo_endpoint_de_atualizacao(ambiente):
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    assert ingestao.main(["--ate", INCREMENTAL_ATE]) == 0

    api = ApiFalsa.instancias[-1]
    endpoints = {e for e, _ in api.parametros}
    assert endpoints == {"/v1/contratacoes/atualizacao", "/v1/contratos/atualizacao"}
    assert {p["dataInicial"] for _, p in api.parametros} == {"20261101"}
    assert {p["dataFinal"] for _, p in api.parametros} == {"20261105"}
    # 2 modalidades de contratações + contratos, uma janela cada.
    assert api.chamadas == 3

    modos = [(m, s, d) for _, m, s, d in historico(ambiente)]
    assert modos == [
        ("completa", "sucesso", date(2026, 10, 31)),
        ("incremental", "sucesso", date(2026, 11, 5)),
    ]
    # A versão nova do contrato foi acrescentada; a antiga continua.
    assert len(raw_completa(ambiente)["contratos"]) == 2


def test_incremental_sem_nada_a_consultar_nao_chama_api_nem_retrocede(ambiente):
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0  # mesmo dia
    assert ingestao.main(["--ate", "2026-10-15"]) == 0  # antes do último dados_ate

    assert len(ApiFalsa.instancias) == 1  # só a carga completa criou cliente
    execucoes = consultar(
        ambiente, "SELECT modo, status, dados_ate, chamadas_api FROM raw.execucoes ORDER BY inicio"
    )
    assert execucoes[1:] == [
        ("incremental", "sucesso", date(2026, 10, 31), 0),
        ("incremental", "sucesso", date(2026, 10, 31), 0),
    ]


def test_banco_descartavel_reconstrucao_deixa_tudo_pronto_para_o_incremental(ambiente, monkeypatch):
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    assert ingestao.main(["--ate", INCREMENTAL_ATE]) == 0
    raw_antes = raw_completa(ambiente)
    historico_antes = historico(ambiente)

    ambiente.banco.unlink()
    monkeypatch.setattr(ingestao, "ClienteAPI", ApiProibida)
    assert ingestao.main(["--reconstruir"]) == 0

    # Mesmas linhas, com os mesmos _execucao_id e _extraido_em originais.
    assert raw_completa(ambiente) == raw_antes
    depois = historico(ambiente)
    assert depois[:2] == historico_antes
    assert depois[2][1:] == ("reconstrucao", "sucesso", date(2026, 11, 5))
    [(chamadas,)] = consultar(
        ambiente, "SELECT chamadas_api FROM raw.execucoes WHERE modo = 'reconstrucao'"
    )
    assert chamadas == 0

    # O próximo incremental parte do dia seguinte ao último dados_ate, sem carga completa.
    assert escolher_modo(depois, completa=False, reconstruir=False) == "incremental"
    assert janela_incremental(depois, date(2026, 11, 7)) == (date(2026, 11, 6), date(2026, 11, 7))
    monkeypatch.setattr(ingestao, "ClienteAPI", ApiFalsa)
    assert ingestao.main(["--ate", "2026-11-07"]) == 0
    api = ApiFalsa.instancias[-1]
    assert {e for e, _ in api.parametros} == {"/v1/contratacoes/atualizacao", "/v1/contratos/atualizacao"}
    assert {p["dataInicial"] for _, p in api.parametros} == {"20261106"}


def test_espelho_recebe_execucoes_anteriores_a_ele(ambiente, monkeypatch):
    # Simula um banco com execuções registradas antes de o espelho existir.
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    (ambiente.landing / landing.ESPELHO).unlink()

    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0  # qualquer execução sincroniza
    modos = [e["modo"] for e in landing.ler_execucoes(ambiente.landing)]
    assert modos == ["completa", "incremental"]

    ambiente.banco.unlink()
    monkeypatch.setattr(ingestao, "ClienteAPI", ApiProibida)
    assert ingestao.main(["--reconstruir"]) == 0
    assert [m for _, m, _, _ in historico(ambiente)] == ["completa", "incremental", "reconstrucao"]


def test_espelho_registra_inicio_e_fim_de_cada_execucao(ambiente):
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    linhas = (ambiente.landing / landing.ESPELHO).read_text(encoding="utf-8").splitlines()
    assert [json.loads(linha)["status"] for linha in linhas] == ["falha", "sucesso"]
    [execucao] = landing.ler_execucoes(ambiente.landing)
    assert execucao["status"] == "sucesso"
    assert execucao["chamadas_api"] == ApiFalsa.instancias[0].chamadas


def test_reconstrucao_ignora_janela_sem_manifesto(ambiente, monkeypatch):
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    antes = raw_completa(ambiente)
    incompleta = ambiente.landing / "contratos" / f"cnpj={ambiente.matriz}" / "janela=2026-12-01_2026-12-31"
    landing.salvar_pagina(incompleta, 1, contrato_alterado().corpo)

    monkeypatch.setattr(ingestao, "ClienteAPI", ApiProibida)
    assert ingestao.main(["--reconstruir"]) == 0
    assert raw_completa(ambiente) == antes


def test_reconstrucao_que_falha_nao_apaga_o_banco(ambiente, monkeypatch):
    assert ingestao.main(["--ate", COMPLETA_ATE]) == 0
    antes = raw_completa(ambiente)
    pagina = next(ambiente.landing.rglob("pagina_002.json"))
    pagina.write_bytes(b"corrompido")

    monkeypatch.setattr(ingestao, "ClienteAPI", ApiProibida)
    assert ingestao.main(["--reconstruir"]) == 1
    assert raw_completa(ambiente) == antes
    assert [(m, s) for _, m, s, _ in historico(ambiente)] == [
        ("completa", "sucesso"), ("reconstrucao", "falha")
    ]


@pytest.mark.parametrize("argumentos", [["--reconstruir", "--completa"], ["--reconstruir", "--ate", "2026-10-01"]])
def test_reconstruir_nao_combina_com_outros_parametros(ambiente, argumentos):
    assert ingestao.main(argumentos) == 2
    assert not ambiente.banco.exists()
