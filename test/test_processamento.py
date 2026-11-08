import hashlib
import json
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path

import pytest
from conftest import fixture_bytes

from pipeline.processamento import (
    ClasseResposta,
    RespostaInvalida,
    caminho_janela,
    classificar_status,
    conferir_janela,
    espera_429,
    hash_registro,
    ids_retomaveis,
    janela_ja_concluida,
    janelas_mensais,
    ler_pagina,
    linhas_da_resposta,
    montar_manifesto,
    montar_parametros,
    nome_endpoint,
    texto_registro,
)

# --- espera após HTTP 429 ----------------------------------------------------

AGORA = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)


def test_espera_429_sem_retry_after_usa_o_padrao():
    assert espera_429(None, 60, AGORA) == 60


def test_espera_429_com_retry_after_em_segundos():
    assert espera_429("90", 30, AGORA) == 90
    assert espera_429(" 5 ", 30, AGORA) == 5


def test_espera_429_com_retry_after_em_data_http():
    assert espera_429("Sat, 07 Nov 2026 12:01:15 GMT", 30, AGORA) == 75


def test_espera_429_com_data_no_passado_nao_espera():
    assert espera_429("Sat, 07 Nov 2026 11:00:00 GMT", 30, AGORA) == 0


@pytest.mark.parametrize("valor", ["", "amanhã", "-5", "1.5"])
def test_espera_429_com_retry_after_invalido_usa_o_padrao(valor):
    assert espera_429(valor, 30, AGORA) == 30


# --- janelas mensais ---------------------------------------------------------


def test_janelas_mensais_cobrem_o_periodo_sem_buracos():
    janelas = janelas_mensais(date(2023, 1, 1), date(2023, 3, 15))
    assert janelas == [
        (date(2023, 1, 1), date(2023, 1, 31)),
        (date(2023, 2, 1), date(2023, 2, 28)),
        (date(2023, 3, 1), date(2023, 3, 15)),
    ]


def test_janelas_mensais_ano_bissexto_e_virada_de_ano():
    janelas = janelas_mensais(date(2023, 12, 10), date(2024, 2, 29))
    assert janelas == [
        (date(2023, 12, 10), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
    ]


def test_janelas_mensais_de_um_dia():
    assert janelas_mensais(date(2026, 11, 6), date(2026, 11, 6)) == [
        (date(2026, 11, 6), date(2026, 11, 6))
    ]


def test_periodo_completo_tem_um_mes_por_janela():
    janelas = janelas_mensais(date(2023, 1, 1), date(2026, 11, 6))
    assert len(janelas) == 47
    for (_, fim), (inicio_seguinte, _) in pairwise(janelas):
        assert (inicio_seguinte - fim).days == 1


def test_janelas_mensais_recusa_periodo_invertido():
    with pytest.raises(ValueError):
        janelas_mensais(date(2026, 2, 1), date(2026, 1, 1))


# --- parâmetros --------------------------------------------------------------


def test_parametros_de_contratacoes_incluem_modalidade():
    parametros = montar_parametros(
        inicio=date(2026, 3, 1), fim=date(2026, 3, 31), pagina=2, tamanho_pagina=50,
        filtro_cnpj="cnpj", cnpj="00394429000100",
        filtro_modalidade="codigoModalidadeContratacao", modalidade=6,
    )
    assert parametros == {
        "dataInicial": "20260301",
        "dataFinal": "20260331",
        "cnpj": "00394429000100",
        "pagina": 2,
        "tamanhoPagina": 50,
        "codigoModalidadeContratacao": 6,
    }


def test_parametros_de_contratos_sem_modalidade():
    parametros = montar_parametros(
        inicio=date(2026, 3, 1), fim=date(2026, 3, 31), pagina=1, tamanho_pagina=50,
        filtro_cnpj="cnpjOrgao", cnpj="00394429000100",
    )
    assert parametros["cnpjOrgao"] == "00394429000100"
    assert "codigoModalidadeContratacao" not in parametros


# --- códigos HTTP ------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "classe"),
    [
        (200, ClasseResposta.SUCESSO),
        (204, ClasseResposta.VAZIO),
        (429, ClasseResposta.FALHA_TEMPORARIA),
        (500, ClasseResposta.FALHA_TEMPORARIA),
        (503, ClasseResposta.FALHA_TEMPORARIA),
        (504, ClasseResposta.FALHA_TEMPORARIA),
        (400, ClasseResposta.FALHA_DEFINITIVA),
        (404, ClasseResposta.FALHA_DEFINITIVA),
        (301, ClasseResposta.FALHA_DEFINITIVA),
        (201, ClasseResposta.FALHA_DEFINITIVA),
    ],
)
def test_classificar_status(codigo, classe):
    assert classificar_status(codigo) is classe


# --- leitura da página -------------------------------------------------------


def test_ler_pagina_valida():
    pagina = ler_pagina(fixture_bytes("contratacoes_pagina_1.json"))
    assert pagina["totalRegistros"] == 3
    assert len(pagina["data"]) == 2


@pytest.mark.parametrize(
    "corpo",
    [b"<html>erro</html>", b"[]", b'{"data": []}', b'{"data": {}, "totalRegistros": 0, "totalPaginas": 0}'],
)
def test_ler_pagina_recusa_corpo_inesperado(corpo):
    # Erro nunca vira zero: corpo estranho não pode passar por página vazia.
    with pytest.raises(RespostaInvalida):
        ler_pagina(corpo)


# --- caminhos na landing -----------------------------------------------------


def test_nome_endpoint():
    assert nome_endpoint("/v1/contratacoes/publicacao") == "contratacoes_publicacao"
    assert nome_endpoint("/v1/contratos") == "contratos"


def test_caminho_janela_com_e_sem_modalidade():
    raiz = Path("data/landing")
    com = caminho_janela(raiz, "/v1/contratacoes/publicacao", "00394429000100", 6,
                         date(2026, 3, 1), date(2026, 3, 31))
    sem = caminho_janela(raiz, "/v1/contratos", "00394429000100", None,
                         date(2026, 3, 1), date(2026, 3, 31))
    assert com.as_posix() == (
        "data/landing/contratacoes_publicacao/cnpj=00394429000100/"
        "modalidade=06/janela=2026-03-01_2026-03-31"
    )
    assert sem.as_posix() == (
        "data/landing/contratos/cnpj=00394429000100/janela=2026-03-01_2026-03-31"
    )


# --- hash e texto do registro ------------------------------------------------


def test_hash_ignora_ordem_das_chaves():
    a = {"numeroControlePNCP": "X", "valor": 1.5, "orgao": {"cnpj": "1", "nome": "Á"}}
    b = {"orgao": {"nome": "Á", "cnpj": "1"}, "valor": 1.5, "numeroControlePNCP": "X"}
    assert hash_registro(a) == hash_registro(b)


def test_texto_do_registro_mantem_ordem_original():
    a = {"z": 1, "a": 2}
    b = {"a": 2, "z": 1}
    assert texto_registro(a) == '{"z": 1, "a": 2}'
    assert texto_registro(a) != texto_registro(b)


def test_hash_muda_quando_o_conteudo_muda():
    assert hash_registro({"valor": 1.0}) != hash_registro({"valor": 2.0})


def test_hash_e_sha256_da_forma_canonica():
    registro = {"b": "ção", "a": [1, 2]}
    esperado = hashlib.sha256('{"a":[1,2],"b":"ção"}'.encode()).hexdigest()
    assert hash_registro(registro) == esperado


# --- linhas da camada bruta --------------------------------------------------


def test_linhas_da_resposta():
    pagina = ler_pagina(fixture_bytes("contratacoes_pagina_1.json"))
    linhas = linhas_da_resposta(
        pagina, endpoint="/v1/contratacoes/publicacao", modalidade=6,
        inicio=date(2026, 3, 1), fim=date(2026, 3, 31), numero_pagina=1,
        arquivo_origem="data/landing/x/pagina_001.json",
        extraido_em="2026-11-07T10:00:00-03:00", execucao_id="exec-1",
    )
    assert len(linhas) == 2
    primeira = linhas[0]
    assert json.loads(primeira["registro"]) == pagina["data"][0]
    assert primeira["_hash"] == hash_registro(pagina["data"][0])
    assert primeira["_modalidade"] == "6"
    assert primeira["_pagina"] == "1"
    assert primeira["_janela_inicio"] == "2026-03-01"
    # Todas as colunas são texto (princípio da camada bruta).
    assert all(isinstance(v, str) for v in primeira.values())


def test_linhas_de_contratos_tem_modalidade_vazia():
    pagina = ler_pagina(fixture_bytes("contratos_pagina_unica.json"))
    linhas = linhas_da_resposta(
        pagina, endpoint="/v1/contratos", modalidade=None,
        inicio=date(2026, 2, 1), fim=date(2026, 2, 28), numero_pagina=1,
        arquivo_origem="a.json", extraido_em="t", execucao_id="e",
    )
    assert linhas[0]["_modalidade"] is None


# --- conferência -------------------------------------------------------------


def test_conferencia_ok():
    registros = [{"numeroControlePNCP": "A"}, {"numeroControlePNCP": "B"}]
    assert conferir_janela(2, registros, "numeroControlePNCP") == []


def test_conferencia_acusa_contagem_diferente():
    registros = [{"numeroControlePNCP": "A"}]
    problemas = conferir_janela(2, registros, "numeroControlePNCP")
    assert len(problemas) == 1 and problemas[0].startswith("contagem")


def test_conferencia_acusa_duplicata():
    pagina = ler_pagina(fixture_bytes("contratacoes_duplicata.json"))
    problemas = conferir_janela(pagina["totalRegistros"], pagina["data"], "numeroControlePNCP")
    assert len(problemas) == 1 and problemas[0].startswith("duplicatas")


def test_conferencia_acusa_registro_sem_chave():
    problemas = conferir_janela(1, [{"outro": 1}], "numeroControlePNCP")
    assert any("sem a chave" in p for p in problemas)


def test_conferencia_de_janela_vazia():
    assert conferir_janela(0, [], "numeroControlePNCP") == []


# --- manifesto e retomada ----------------------------------------------------


def test_manifesto_de_janela_vazia():
    manifesto = montar_manifesto(
        endpoint="/v1/contratos", cnpj="00394429000100", modalidade=None,
        inicio=date(2023, 1, 1), fim=date(2023, 1, 31), total_api=0, total_salvo=0,
        extracoes=[], execucao_id="e", concluido_em="t",
    )
    assert manifesto["total_api"] == 0
    assert manifesto["total_salvo"] == 0
    assert manifesto["paginas"] == 0


def test_ids_retomaveis_sem_historico():
    assert ids_retomaveis([]) == set()


def test_ids_retomaveis_apos_falhas_da_completa():
    historico = [("e1", "completa", "falha"), ("e2", "completa", "falha")]
    assert ids_retomaveis(historico) == {"e1", "e2"}


def test_ids_retomaveis_zera_apos_sucesso():
    historico = [("e1", "completa", "falha"), ("e2", "completa", "sucesso")]
    assert ids_retomaveis(historico) == set()


def test_ids_retomaveis_so_conta_falhas_posteriores_ao_sucesso():
    historico = [
        ("e1", "completa", "falha"),
        ("e2", "completa", "sucesso"),
        ("e3", "completa", "falha"),
    ]
    assert ids_retomaveis(historico) == {"e3"}


def test_janela_ja_concluida():
    assert janela_ja_concluida({"execucao_id": "e1"}, {"e1"})
    assert not janela_ja_concluida({"execucao_id": "e0"}, {"e1"})
    assert not janela_ja_concluida(None, {"e1"})
