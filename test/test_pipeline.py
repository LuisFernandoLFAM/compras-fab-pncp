"""Comando único python -m pipeline, com a ingestão e a transformação falsas."""

import pytest

import pipeline.__main__ as comando


@pytest.fixture
def chamadas(monkeypatch):
    """Substitui as duas etapas; a ingestão devolve o código definido em chamadas['codigo']."""
    registro = {"codigo": 0, "ingestao": [], "transformacao": 0}

    def ingestao_falsa(argv):
        registro["ingestao"].append(argv)
        return registro["codigo"]

    def transformacao_falsa():
        registro["transformacao"] += 1
        return 0

    monkeypatch.setattr(comando.ingestao, "main", ingestao_falsa)
    monkeypatch.setattr(comando.transformacao, "main", transformacao_falsa)
    return registro


def test_ingestao_com_sucesso_roda_a_transformacao(chamadas):
    assert comando.main(["--ate", "2026-10-31"]) == 0
    assert chamadas["ingestao"] == [["--ate", "2026-10-31"]]
    assert chamadas["transformacao"] == 1


@pytest.mark.parametrize("codigo", [1, 2, 130])
def test_ingestao_que_falha_nao_roda_a_transformacao(chamadas, codigo):
    chamadas["codigo"] = codigo
    assert comando.main(["--completa"]) == codigo
    assert chamadas["transformacao"] == 0


def test_codigo_da_transformacao_e_devolvido(chamadas, monkeypatch):
    monkeypatch.setattr(comando.transformacao, "main", lambda: 1)
    assert comando.main([]) == 1
