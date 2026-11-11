"""Contrato de dados com registros falsos: sem internet e sem banco."""

import json

from conftest import contratacao_falsa, contrato_falso

from pipeline.contrato_dados import conferir_contrato, esperado
from pipeline.refinamento import LinhaRaw, ler_registro


def linha(registro: dict) -> LinhaRaw:
    return LinhaRaw(ler_registro(json.dumps(registro)), "h", "2026-11-08T00:00:00-03:00", "exec")


def conferir(tabela: str, todos: list[dict], ultima: list[dict] | None = None):
    ultima = todos if ultima is None else ultima
    return conferir_contrato(tabela, [linha(r) for r in todos], [linha(r) for r in ultima])


def sem(registro: dict, *caminho: str) -> dict:
    """Cópia do registro sem a chave (no primeiro nível ou dentro de um bloco)."""
    copia = json.loads(json.dumps(registro))
    alvo = copia
    for parte in caminho[:-1]:
        alvo = alvo[parte]
    del alvo[caminho[-1]]
    return copia


def test_registros_completos_nao_geram_aviso_nem_falha():
    for tabela, registro in (("contratacoes", contratacao_falsa()), ("contratos", contrato_falso())):
        resultado = conferir(tabela, [registro])
        assert resultado.avisos == []
        assert resultado.falhas == []


def test_esperado_sai_da_tabela_de_para():
    esp = esperado("contratos")
    assert "numeroControlePncpCompra" in esp.primeiro_nivel
    assert esp.blocos["orgaoSubRogado"] == {"cnpj", "razaoSocial", "esferaId", "poderId"}
    assert "urlCipi" in esp.descartados and "urlCipi" not in esp.primeiro_nivel
    assert "dataInclusao" in esperado("contratacoes").fontes


# --- campo novo ------------------------------------------------------------------


def test_campo_novo_no_primeiro_nivel_avisa_com_registros_distintos():
    novo = contratacao_falsa(campoNovo="x")
    outra = contratacao_falsa("00394429000100-1-000002/2024", campoNovo="y")
    # Duas versões do mesmo registro contam uma vez.
    resultado = conferir("contratacoes", [novo, novo, outra])
    assert resultado.avisos == ["contratacoes: campo novo campoNovo em 2 registros"]
    assert resultado.falhas == []


def test_campo_novo_dentro_de_bloco_e_de_fonte():
    registro = contratacao_falsa(
        unidadeOrgao={**contratacao_falsa()["unidadeOrgao"], "codigoNovo": "1"},
        fontesOrcamentarias=[
            {"codigo": 1, "nome": "a", "descricao": "b", "dataInclusao": "2026-06-01T00:00:00", "extra": 1}
        ],
    )
    assert conferir("contratacoes", [registro]).avisos == [
        "contratacoes: campo novo fontesOrcamentarias[].extra em 1 registros",
        "contratacoes: campo novo unidadeOrgao.codigoNovo em 1 registros",
    ]


def test_bloco_novo_avisa_uma_vez_sem_descer_nele():
    registro = contrato_falso(blocoNovo={"a": 1, "b": 2})
    assert conferir("contratos", [registro]).avisos == ["contratos: campo novo blocoNovo em 1 registros"]


def test_campo_novo_e_procurado_em_toda_a_raw():
    resultado = conferir("contratos", [contrato_falso(campoNovo=1)], ultima=[])
    assert resultado.avisos == ["contratos: campo novo campoNovo em 1 registros"]


# --- descartado que passa a ter dado ------------------------------------------------------


def test_descartado_com_dado_avisa():
    registro = contrato_falso(niFornecedorSubContratado="11222333000181")
    assert conferir("contratos", [registro]).avisos == [
        "contratos: campo descartado niFornecedorSubContratado preenchido em 1 registros"
    ]


def test_descartado_com_bloco_avisa():
    registro = contratacao_falsa(orgaoSubRogado={"cnpj": "00394429000100"})
    assert conferir("contratacoes", [registro]).avisos == [
        "contratacoes: campo descartado orgaoSubRogado preenchido em 1 registros"
    ]


def test_descartado_com_texto_vazio_nao_e_dado():
    assert conferir("contratos", [contrato_falso(urlCipi="   ")]).avisos == []


# --- campo que some -----------------------------------------------------------------------


def test_campo_da_tabela_de_para_ausente_na_ultima_rodada_falha():
    registro = sem(contrato_falso(), "valorGlobal")
    resultado = conferir("contratos", [registro])
    assert resultado.falhas == ["contratos: campo valorGlobal ausente em 1 registros da última rodada"]


def test_campo_ausente_fora_da_ultima_rodada_nao_falha():
    antigo = sem(contrato_falso(), "valorGlobal")
    assert conferir("contratos", [antigo, contrato_falso()], ultima=[contrato_falso()]).falhas == []


def test_chave_com_nulo_nao_e_ausente():
    assert conferir("contratos", [contrato_falso(valorAcumulado=None)]).falhas == []


def test_campo_ausente_em_bloco_obrigatorio_falha():
    registro = sem(contrato_falso(), "unidadeOrgao", "codigoIbge")
    assert conferir("contratos", [registro]).falhas == [
        "contratos: campo unidadeOrgao.codigoIbge ausente em 1 registros da última rodada"
    ]


def test_bloco_obrigatorio_nulo_conta_como_campos_ausentes():
    registro = contrato_falso(tipoContrato=None)
    assert conferir("contratos", [registro]).falhas == [
        "contratos: campo tipoContrato.id ausente em 1 registros da última rodada",
        "contratos: campo tipoContrato.nome ausente em 1 registros da última rodada",
    ]


def test_bloco_opcional_so_e_conferido_quando_existe():
    assert conferir("contratos", [contrato_falso(orgaoSubRogado=None)]).falhas == []
    incompleto = contrato_falso(orgaoSubRogado={"cnpj": "00394429000100", "razaoSocial": "X", "esferaId": "F"})
    assert conferir("contratos", [incompleto]).falhas == [
        "contratos: campo orgaoSubRogado.poderId ausente em 1 registros da última rodada"
    ]


def test_campo_ausente_em_fonte_falha():
    registro = contratacao_falsa(
        fontesOrcamentarias=[{"codigo": 1, "nome": "a", "dataInclusao": "2026-06-01T00:00:00"}]
    )
    assert conferir("contratacoes", [registro]).falhas == [
        "contratacoes: campo fontesOrcamentarias[].descricao ausente em 1 registros da última rodada"
    ]


def test_descartado_ausente_so_avisa():
    registro = sem(contrato_falso(), "urlCipi")
    resultado = conferir("contratos", [registro])
    assert resultado.falhas == []
    assert resultado.avisos == [
        "contratos: campo descartado urlCipi ausente em 1 registros da última rodada"
    ]


def test_ultima_rodada_vazia_nao_confere_ausentes():
    resultado = conferir("contratos", [sem(contrato_falso(), "valorGlobal")], ultima=[])
    assert resultado.falhas == []
    assert resultado.registros_ultima_rodada == 0
