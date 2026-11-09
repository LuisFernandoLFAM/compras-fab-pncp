from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.api import Resposta
from pipeline.config import carregar_config
from pipeline.processamento import ClasseResposta

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(nome: str) -> bytes:
    return (FIXTURES / nome).read_bytes()


def ok(nome: str) -> Resposta:
    return Resposta(ClasseResposta.SUCESSO, fixture_bytes(nome), "2026-11-07T10:00:00-03:00")


VAZIO = Resposta(ClasseResposta.VAZIO, b"", "2026-11-07T10:00:00-03:00")


class ClienteFalso:
    """Substitui o ClienteAPI: devolve respostas prontas, na ordem, e anota as chamadas."""

    def __init__(self, respostas: list[Resposta]):
        self.respostas = list(respostas)
        self.parametros: list[dict] = []

    @property
    def chamadas(self) -> int:
        return len(self.parametros)

    def buscar(self, endpoint: str, parametros: dict, contexto: str) -> Resposta:
        self.parametros.append(parametros)
        return self.respostas.pop(0)


@pytest.fixture
def cfg(tmp_path):
    """Configuração real, mas com landing e banco numa pasta temporária."""
    return replace(
        carregar_config(),
        raiz=tmp_path,
        landing=tmp_path / "data" / "landing",
        banco=tmp_path / "teste.duckdb",
    )
