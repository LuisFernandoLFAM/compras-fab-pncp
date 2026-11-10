"""Regras de novas tentativas do ClienteAPI, com uma sessão HTTP falsa (sem rede)."""

import logging

import pytest
import requests

from pipeline.api import ClienteAPI, FalhaAPI
from pipeline.processamento import ClasseResposta


class RespostaHTTP:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode()
        self.headers = headers or {}


class SessaoFalsa:
    def __init__(self, resultados):
        self.resultados = list(resultados)
        self.headers = {}
        self.chamadas = []

    def get(self, url, params, timeout):
        self.chamadas.append((url, params, timeout))
        resultado = self.resultados.pop(0)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


def cliente(cfg, resultados):
    esperas = []
    sessao = SessaoFalsa(resultados)
    return ClienteAPI(cfg, sessao=sessao, dormir=esperas.append), sessao, esperas


def test_sucesso_identifica_o_projeto_e_usa_timeout(cfg):
    c, sessao, _ = cliente(cfg, [RespostaHTTP(200, b"{}")])
    resposta = c.buscar("/v1/contratos", {"pagina": 1}, "ctx")
    assert resposta.classe is ClasseResposta.SUCESSO
    assert sessao.headers["User-Agent"] == cfg.user_agent
    url, _, timeout = sessao.chamadas[0]
    assert url == "https://pncp.gov.br/api/consulta/v1/contratos"
    assert timeout == 60


def test_sondagem_usa_tempo_limite_proprio(cfg):
    c, sessao, _ = cliente(cfg, [RespostaHTTP(200, b"{}")])
    c.buscar("/v1/contratos", {"pagina": 1}, "ctx", timeout=cfg.timeout_sondagem)
    assert sessao.chamadas[0][2] == 120


def test_sondagem_desiste_depois_de_uma_nova_tentativa(cfg):
    c, sessao, esperas = cliente(cfg, [RespostaHTTP(500)] * 2)
    with pytest.raises(FalhaAPI, match="após 1 novas tentativas"):
        c.buscar("/v1/contratos", {}, "sondagem", novas_tentativas=cfg.novas_tentativas_sondagem)
    assert len(sessao.chamadas) == 2
    assert esperas == [2, cfg.pausa]  # espera da única nova tentativa e pausa entre chamadas


def test_204_e_vazio_sem_nova_tentativa(cfg):
    c, sessao, _ = cliente(cfg, [RespostaHTTP(204)])
    assert c.buscar("/v1/contratos", {}, "ctx").classe is ClasseResposta.VAZIO
    assert len(sessao.chamadas) == 1


def test_falha_temporaria_tenta_de_novo_com_espera_crescente(cfg):
    c, _, esperas = cliente(
        cfg, [requests.Timeout("lento"), RespostaHTTP(503), RespostaHTTP(500), RespostaHTTP(200, b"{}")]
    )
    assert c.buscar("/v1/contratos", {}, "ctx").classe is ClasseResposta.SUCESSO
    assert c.chamadas == 4
    # Antes de cada nova tentativa: espera crescente + pausa entre chamadas.
    assert esperas == [2, cfg.pausa, 4, cfg.pausa, 8, cfg.pausa]


def test_429_com_retry_after_espera_o_tempo_indicado(cfg):
    c, _, esperas = cliente(
        cfg, [RespostaHTTP(429, headers={"Retry-After": "17"}), RespostaHTTP(200, b"{}")]
    )
    assert c.buscar("/v1/contratos", {}, "ctx").classe is ClasseResposta.SUCESSO
    assert esperas == [17, cfg.pausa]


def test_429_sem_retry_after_espera_30_60_120(cfg):
    c, sessao, esperas = cliente(cfg, [RespostaHTTP(429)] * 4)
    with pytest.raises(FalhaAPI, match="persistente.*HTTP 429"):
        c.buscar("/v1/contratos", {}, "ctx")
    assert len(sessao.chamadas) == 4
    assert esperas == [30, cfg.pausa, 60, cfg.pausa, 120, cfg.pausa]


def test_429_e_outras_falhas_misturadas_usam_cada_uma_sua_espera(cfg):
    c, _, esperas = cliente(
        cfg, [RespostaHTTP(429), requests.Timeout("lento"), RespostaHTTP(429), RespostaHTTP(200, b"{}")]
    )
    c.buscar("/v1/contratos", {}, "ctx")
    assert esperas == [30, cfg.pausa, 4, cfg.pausa, 120, cfg.pausa]


def test_cada_nova_tentativa_gera_aviso_no_log(cfg, caplog):
    c, _, _ = cliente(
        cfg,
        [
            RespostaHTTP(429, headers={"Retry-After": "45"}),
            RespostaHTTP(503),
            RespostaHTTP(200, b"{}"),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="pipeline.api"):
        c.buscar("/v1/contratos", {}, "modalidade 1, janela 2023-07-01_2023-07-31, página 1")

    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    contexto = "modalidade 1, janela 2023-07-01_2023-07-31, página 1"
    assert [r.getMessage() for r in avisos] == [
        f"HTTP 429 em {contexto}: nova tentativa 1 de 3 em 45 s",
        f"HTTP 503 em {contexto}: nova tentativa 2 de 3 em 4 s",
    ]


def test_falha_persistente_nao_gera_aviso_de_quarta_tentativa(cfg, caplog):
    c, _, _ = cliente(cfg, [RespostaHTTP(500)] * 4)
    with caplog.at_level(logging.WARNING, logger="pipeline.api"), pytest.raises(FalhaAPI):
        c.buscar("/v1/contratos", {}, "ctx")
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3


def test_falha_persistente_para_com_contexto(cfg):
    c, sessao, _ = cliente(cfg, [RespostaHTTP(500)] * 4)
    with pytest.raises(FalhaAPI, match="persistente.*modalidade 6, janela X, página 3"):
        c.buscar("/v1/contratos", {}, "modalidade 6, janela X, página 3")
    assert len(sessao.chamadas) == 4


def test_erro_de_conexao_persistente_vira_falha(cfg):
    c, _, _ = cliente(cfg, [requests.ConnectionError("sem rede")] * 4)
    with pytest.raises(FalhaAPI, match="ConnectionError"):
        c.buscar("/v1/contratos", {}, "ctx")


def test_falha_definitiva_para_sem_nova_tentativa(cfg):
    c, sessao, _ = cliente(cfg, [RespostaHTTP(400, b"parametro invalido")])
    with pytest.raises(FalhaAPI, match="HTTP 400"):
        c.buscar("/v1/contratos", {}, "ctx")
    assert len(sessao.chamadas) == 1


def test_pausa_entre_chamadas(cfg):
    c, _, esperas = cliente(cfg, [RespostaHTTP(200, b"{}"), RespostaHTTP(200, b"{}")])
    c.buscar("/v1/contratos", {}, "ctx")
    c.buscar("/v1/contratos", {}, "ctx")
    assert esperas == [cfg.pausa]
