"""Comando único python -m pipeline, com as três etapas falsas."""

import pytest

import pipeline.__main__ as comando


@pytest.fixture
def chamadas(monkeypatch):
    """Substitui as etapas; cada uma devolve o código definido em chamadas['codigos']."""
    registro = {"codigos": {"ingestao": 0, "transformacao": 0, "marts": 0}, "argv": [], "ordem": []}

    def etapa(nome):
        def falsa(*args):
            registro["ordem"].append(nome)
            if nome == "ingestao":
                registro["argv"].append(args[0])
            return registro["codigos"][nome]
        return falsa

    monkeypatch.setattr(comando.ingestao, "main", etapa("ingestao"))
    monkeypatch.setattr(comando.transformacao, "main", etapa("transformacao"))
    monkeypatch.setattr(comando.marts, "main", etapa("marts"))
    return registro


def test_tudo_com_sucesso_roda_as_tres_etapas_em_ordem(chamadas):
    assert comando.main(["--ate", "2026-10-31"]) == 0
    assert chamadas["argv"] == [["--ate", "2026-10-31"]]
    assert chamadas["ordem"] == ["ingestao", "transformacao", "marts"]


@pytest.mark.parametrize("codigo", [1, 2, 130])
def test_ingestao_que_falha_nao_roda_as_outras(chamadas, codigo):
    chamadas["codigos"]["ingestao"] = codigo
    assert comando.main(["--completa"]) == codigo
    assert chamadas["ordem"] == ["ingestao"]


def test_transformacao_que_falha_nao_roda_os_marts(chamadas):
    chamadas["codigos"]["transformacao"] = 1
    assert comando.main([]) == 1
    assert chamadas["ordem"] == ["ingestao", "transformacao"]


def test_codigo_dos_marts_e_devolvido(chamadas):
    chamadas["codigos"]["marts"] = 1
    assert comando.main([]) == 1
