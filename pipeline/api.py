"""A parte que busca: chamadas HTTP à API de consulta do PNCP (decisão 6)."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

from pipeline.config import Config
from pipeline.processamento import ClasseResposta, classificar_status, espera_429

log = logging.getLogger(__name__)

ERROS_TEMPORARIOS = (
    requests.Timeout,
    requests.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


class FalhaAPI(Exception):
    """Falha persistente ou definitiva. A execução deve parar."""


@dataclass(frozen=True)
class Resposta:
    classe: ClasseResposta  # SUCESSO ou VAZIO; falhas viram FalhaAPI
    corpo: bytes
    extraido_em: str


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ClienteAPI:
    def __init__(self, cfg: Config, sessao: requests.Session | None = None, dormir=time.sleep):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self.sessao.headers["User-Agent"] = cfg.user_agent
        self.dormir = dormir
        self.chamadas = 0

    def buscar(
        self, endpoint: str, parametros: dict, contexto: str, timeout: float | None = None,
        novas_tentativas: int | None = None,
    ) -> Resposta:
        """Faz a chamada com novas tentativas só para falhas temporárias.

        `timeout` e `novas_tentativas` substituem os valores padrão (a sondagem
        anual usa um tempo limite maior e menos tentativas).
        """
        url = self.cfg.url_base + endpoint
        timeout = timeout or self.cfg.timeout
        if novas_tentativas is None:
            novas_tentativas = self.cfg.novas_tentativas
        detalhe = ""
        for tentativa in range(novas_tentativas + 1):
            if self.chamadas:
                self.dormir(self.cfg.pausa)
            self.chamadas += 1
            extraido_em = agora()
            try:
                r = self.sessao.get(url, params=parametros, timeout=timeout)
            except ERROS_TEMPORARIOS as e:
                detalhe = f"{type(e).__name__}: {e}"
                espera = self.cfg.esperas[tentativa] if tentativa < novas_tentativas else 0
            else:
                classe = classificar_status(r.status_code)
                if classe in (ClasseResposta.SUCESSO, ClasseResposta.VAZIO):
                    return Resposta(classe, r.content, extraido_em)
                if classe is ClasseResposta.FALHA_DEFINITIVA:
                    raise FalhaAPI(f"HTTP {r.status_code} em {contexto}: {r.text[:300]}")
                detalhe = f"HTTP {r.status_code}"
                if tentativa >= novas_tentativas:
                    espera = 0
                elif r.status_code == 429:
                    espera = espera_429(
                        r.headers.get("Retry-After"),
                        self.cfg.esperas_429[tentativa],
                        datetime.now(UTC),
                    )
                else:
                    espera = self.cfg.esperas[tentativa]

            if tentativa < novas_tentativas:
                log.warning(
                    "%s em %s: nova tentativa %d de %d em %g s",
                    detalhe, contexto, tentativa + 1, novas_tentativas, espera,
                )
                self.dormir(espera)

        raise FalhaAPI(
            f"falha persistente após {novas_tentativas} novas tentativas em {contexto}: {detalhe}"
        )
