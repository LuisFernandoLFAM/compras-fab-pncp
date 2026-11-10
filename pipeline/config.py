"""Leitura do config.toml: único lugar com CNPJ, datas, endpoints e limites (decisão 9)."""

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Endpoint:
    tabela: str  # nome da tabela em raw (contratacoes ou contratos)
    publicacao: str  # carga completa
    atualizacao: str  # incremental
    filtro_cnpj: str
    filtro_modalidade: str | None  # None quando o endpoint não exige modalidade
    chave: str


@dataclass(frozen=True)
class Config:
    raiz: Path
    cnpjs: tuple[str, ...]  # matriz e filiais, cada um com o próprio ponto de partida
    matriz: str  # CNPJ das execuções antigas sem manifesto (migração)
    data_inicial: date
    url_base: str
    tamanho_pagina: int
    timeout: float
    timeout_sondagem: float
    tamanho_pagina_sondagem: int
    novas_tentativas_sondagem: int
    novas_tentativas: int
    esperas: tuple[float, ...]  # espera antes de cada nova tentativa
    esperas_429: tuple[float, ...]  # idem, para HTTP 429 sem Retry-After
    pausa: float
    user_agent: str
    modalidades: tuple[int, ...]
    endpoints: tuple[Endpoint, ...]
    landing: Path
    banco: Path


def validar_cnpjs(cnpjs: tuple[str, ...], matriz: str) -> None:
    if not cnpjs:
        raise ValueError("config.toml: a lista de CNPJs está vazia")
    invalidos = [c for c in cnpjs if len(c) != 14 or not c.isdigit()]
    if invalidos:
        raise ValueError(f"config.toml: CNPJ precisa de 14 dígitos: {invalidos}")
    if len(set(cnpjs)) != len(cnpjs):
        raise ValueError("config.toml: CNPJ repetido na lista")
    if matriz not in cnpjs:
        raise ValueError(f"config.toml: a matriz {matriz} não está na lista de CNPJs")


def carregar_config(caminho: Path = RAIZ_PROJETO / "config.toml") -> Config:
    with open(caminho, "rb") as f:
        dados = tomllib.load(f)

    raiz = caminho.resolve().parent
    api = dados["api"]
    novas_tentativas = api["novas_tentativas"]
    if api["novas_tentativas_sondagem"] > novas_tentativas:
        raise ValueError("config.toml: novas_tentativas_sondagem maior que novas_tentativas")
    for chave in ("esperas_segundos", "esperas_429_segundos"):
        if len(api[chave]) < novas_tentativas:
            raise ValueError(f"config.toml: {chave} precisa de {novas_tentativas} valores")
    cnpjs = tuple(dados["orgao"]["cnpjs"])
    matriz = dados["orgao"]["matriz"]
    validar_cnpjs(cnpjs, matriz)
    endpoints = tuple(
        Endpoint(
            tabela=nome,
            publicacao=ep["publicacao"],
            atualizacao=ep["atualizacao"],
            filtro_cnpj=ep["filtro_cnpj"],
            filtro_modalidade=ep.get("filtro_modalidade"),
            chave=ep["chave"],
        )
        for nome, ep in dados["endpoints"].items()
    )

    return Config(
        raiz=raiz,
        cnpjs=cnpjs,
        matriz=matriz,
        data_inicial=dados["periodo"]["data_inicial"],
        url_base=api["url_base"].rstrip("/"),
        tamanho_pagina=api["tamanho_pagina"],
        timeout=api["timeout_segundos"],
        timeout_sondagem=api["timeout_sondagem_segundos"],
        tamanho_pagina_sondagem=api["tamanho_pagina_sondagem"],
        novas_tentativas_sondagem=api["novas_tentativas_sondagem"],
        novas_tentativas=novas_tentativas,
        esperas=tuple(api["esperas_segundos"][:novas_tentativas]),
        esperas_429=tuple(api["esperas_429_segundos"][:novas_tentativas]),
        pausa=api["pausa_segundos"],
        user_agent=api["user_agent"],
        modalidades=tuple(dados["modalidades"]["codigos"]),
        endpoints=endpoints,
        landing=raiz / dados["caminhos"]["landing"],
        banco=raiz / dados["caminhos"]["banco"],
    )
