"""Leitura do config.toml: único lugar com CNPJ, datas, endpoints e limites (decisão 9)."""

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Endpoint:
    tabela: str  # nome da tabela em raw (contratacoes ou contratos)
    publicacao: str
    filtro_cnpj: str
    filtro_modalidade: str | None  # None quando o endpoint não exige modalidade
    chave: str


@dataclass(frozen=True)
class Config:
    raiz: Path
    cnpj: str
    data_inicial: date
    url_base: str
    tamanho_pagina: int
    timeout: float
    novas_tentativas: int
    esperas: tuple[float, ...]  # espera antes de cada nova tentativa
    esperas_429: tuple[float, ...]  # idem, para HTTP 429 sem Retry-After
    pausa: float
    user_agent: str
    modalidades: tuple[int, ...]
    endpoints: tuple[Endpoint, ...]
    landing: Path
    banco: Path


def carregar_config(caminho: Path = RAIZ_PROJETO / "config.toml") -> Config:
    with open(caminho, "rb") as f:
        dados = tomllib.load(f)

    raiz = caminho.resolve().parent
    api = dados["api"]
    novas_tentativas = api["novas_tentativas"]
    for chave in ("esperas_segundos", "esperas_429_segundos"):
        if len(api[chave]) < novas_tentativas:
            raise ValueError(f"config.toml: {chave} precisa de {novas_tentativas} valores")
    endpoints = tuple(
        Endpoint(
            tabela=nome,
            publicacao=ep["publicacao"],
            filtro_cnpj=ep["filtro_cnpj"],
            filtro_modalidade=ep.get("filtro_modalidade"),
            chave=ep["chave"],
        )
        for nome, ep in dados["endpoints"].items()
    )

    return Config(
        raiz=raiz,
        cnpj=dados["orgao"]["cnpj"],
        data_inicial=dados["periodo"]["data_inicial"],
        url_base=api["url_base"].rstrip("/"),
        tamanho_pagina=api["tamanho_pagina"],
        timeout=api["timeout_segundos"],
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
