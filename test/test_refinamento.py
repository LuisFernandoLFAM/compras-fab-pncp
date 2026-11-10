"""Regras puras da transformação, com dados falsos: sem internet e sem banco."""

import json
from datetime import date
from decimal import Decimal

import pytest
from conftest import CNPJ_MATRIZ, contratacao_falsa, contrato_falso

from pipeline.refinamento import (
    COLUNAS_CONTRATACOES,
    COLUNAS_CONTRATOS,
    FalhaTransformacao,
    LinhaRaw,
    classificar_ligacao,
    converter,
    converter_dinheiro,
    cpf_valido,
    escolher_vigentes,
    extraido_em_brasilia,
    ler_registro,
    linhas_contratacoes,
    linhas_contratos,
    mascarar_ni_fornecedor,
    mascarar_texto,
    snake_case,
)

# CPF inventado com dígito verificador válido, e o mesmo com o último dígito trocado.
CPF = "12345678909"
CPF_INVALIDO = "12345678900"
MASCARA = "***.456.789-**"


def linha(registro: dict, extraido_em: str = "2026-11-08T00:00:00-03:00", hash_: str = "h") -> LinhaRaw:
    # Passa pelo texto, como na raw: os números com casas decimais viram Decimal.
    return LinhaRaw(ler_registro(json.dumps(registro)), hash_, extraido_em, "exec")


# --- nomes das colunas ---------------------------------------------------------


def test_snake_case_mecanico():
    assert snake_case("numeroControlePNCP") == "numero_controle_pncp"
    assert snake_case("numeroControlePncpCompra") == "numero_controle_pncp_compra"
    assert snake_case("tipoInstrumentoConvocatorioCodigo") == "tipo_instrumento_convocatorio_codigo"


def test_nomes_com_prefixo_do_bloco():
    nomes = {c.nome for c in COLUNAS_CONTRATOS}
    assert {"unidade_nome_unidade", "orgao_sub_rogado_cnpj", "tipo_contrato_id"} <= nomes
    assert "amparo_legal_codigo" in {c.nome for c in COLUNAS_CONTRATACOES}


# --- versão vigente ------------------------------------------------------------


def test_vigente_pela_maior_das_duas_datas():
    # Na antiga, a global é a maior; na nova, a global é anterior à dataAtualizacao.
    antiga = contratacao_falsa(
        dataAtualizacaoGlobal="2024-05-01T00:00:00", dataAtualizacao="2024-04-01T00:00:00"
    )
    nova = contratacao_falsa(
        dataAtualizacaoGlobal="2024-04-15T00:00:00", dataAtualizacao="2024-06-01T00:00:00"
    )
    [vigente] = escolher_vigentes([linha(antiga, hash_="a"), linha(nova, hash_="b")], "contratacoes")
    assert vigente.hash == "b"


def test_vigente_empate_de_data_decide_pela_extracao():
    registro = contratacao_falsa()
    linhas = [
        linha(registro, "2026-11-08T10:00:00-03:00", "cedo"),
        linha(registro, "2026-11-08T14:00:00+00:00", "tarde"),  # 11h em Brasília
    ]
    [vigente] = escolher_vigentes(linhas, "contratacoes")
    assert vigente.hash == "tarde"


def test_vigente_empate_total_falha():
    registro = contratacao_falsa()
    linhas = [linha(registro, hash_="a"), linha(registro, hash_="b")]
    with pytest.raises(FalhaTransformacao, match="mesmo _extraido_em"):
        escolher_vigentes(linhas, "contratacoes")


def test_vigentes_uma_por_chave_ordenadas():
    linhas = [
        linha(contratacao_falsa(f"{CNPJ_MATRIZ}-1-000002/2024"), hash_="2"),
        linha(contratacao_falsa(f"{CNPJ_MATRIZ}-1-000001/2024"), hash_="1"),
    ]
    assert [v.hash for v in escolher_vigentes(linhas, "contratacoes")] == ["1", "2"]


def test_extraido_em_no_horario_de_brasilia_sem_fuso():
    assert extraido_em_brasilia("2026-11-08T03:00:00+00:00", "x") == "2026-11-08T00:00:00"


# --- dinheiro ------------------------------------------------------------------


def test_dinheiro_vem_do_texto_sem_ponto_flutuante():
    registro = ler_registro('{"v": 0.1, "w": 1234.5, "z": 300}')
    assert isinstance(registro["v"], Decimal)
    assert converter_dinheiro(registro["v"], 2, "x") == Decimal("0.1")
    assert converter_dinheiro(registro["w"], 2, "x") == Decimal("1234.50")
    assert converter_dinheiro(registro["z"], 2, "x") == Decimal(300)
    assert converter_dinheiro(None, 2, "x") is None


def test_dinheiro_soma_exata():
    valores = [converter_dinheiro(v, 2, "x") for v in ler_registro("[0.1, 0.2]")]
    assert sum(valores) == Decimal("0.3")


def test_dinheiro_15_digitos_significativos():
    [valor] = ler_registro("[12345678901.2345]")
    assert converter_dinheiro(valor, 4, "x") == Decimal("12345678901.2345")


def test_dinheiro_casas_demais_falha_sem_arredondar():
    with pytest.raises(FalhaTransformacao, match="mais de 2 casas"):
        converter_dinheiro(ler_registro("[10.123]")[0], 2, "contratos k valor_global")
    assert converter_dinheiro(ler_registro("[10.1234]")[0], 4, "x") == Decimal("10.1234")
    with pytest.raises(FalhaTransformacao, match="mais de 4 casas"):
        converter_dinheiro(ler_registro("[10.12345]")[0], 4, "x")


def test_dinheiro_artefato_de_ponto_flutuante_falha():
    with pytest.raises(FalhaTransformacao, match="casas"):
        converter_dinheiro(ler_registro("[0.30000000000000004]")[0], 2, "x")


def test_dinheiro_parte_inteira_grande_demais_falha():
    assert converter_dinheiro(10**16 - 1, 2, "x") == Decimal(10**16 - 1)
    with pytest.raises(FalhaTransformacao, match="16 dígitos"):
        converter_dinheiro(10**16, 2, "x")
    with pytest.raises(FalhaTransformacao, match="14 dígitos"):
        converter_dinheiro(10**14, 4, "x")


def test_dinheiro_tipo_errado_falha():
    for valor in (True, "100.00", 1.5):
        with pytest.raises(FalhaTransformacao, match="não numérico"):
            converter_dinheiro(valor, 2, "x")


def test_falha_de_dinheiro_diz_tabela_chave_e_campo():
    registro = contrato_falso(valorGlobal=10.001)
    with pytest.raises(FalhaTransformacao) as erro:
        linhas_contratos([linha(registro)], set(), (CNPJ_MATRIZ,), CNPJ_MATRIZ, date(2023, 1, 1))
    assert f"contratos {CNPJ_MATRIZ}-2-000001/2024 valor_global" in str(erro.value)


# --- outros tipos ----------------------------------------------------------------


def test_datas_no_formato_exato():
    assert converter("2024-03-01T10:00:00", "timestamp", "x") == "2024-03-01T10:00:00"
    assert converter("2024-03-01", "data", "x") == "2024-03-01"
    for valor, tipo in (
        ("2024-03-01", "timestamp"),
        ("2024-03-01T10:00:00", "data"),
        ("2024-03-01T10:00:00.5", "timestamp"),
        ("2024-02-30", "data"),
        ("01/03/2024", "data"),
    ):
        with pytest.raises(FalhaTransformacao):
            converter(valor, tipo, "x")


def test_inteiro_e_booleano_estritos():
    assert converter(2024, "inteiro", "x") == "2024"
    assert converter(False, "booleano", "x") == "false"
    for valor, tipo in ((True, "inteiro"), ("2024", "inteiro"), (2**31, "inteiro"), (0, "booleano")):
        with pytest.raises(FalhaTransformacao):
            converter(valor, tipo, "x")


# --- vazios --------------------------------------------------------------------


def test_texto_aparado_e_vazio_vira_nulo():
    assert converter("  67000.000001/2024-01 \n", "texto", "x") == "67000.000001/2024-01"
    assert converter("a  b", "texto", "x") == "a  b"
    assert converter("", "texto", "x") is None
    assert converter(" \t ", "texto", "x") is None
    assert converter(None, "texto", "x") is None


def test_nulo_nunca_e_preenchido():
    for tipo in ("inteiro", "booleano", "dinheiro", "dinheiro4", "timestamp", "data", "livre"):
        assert converter(None, tipo, "x") is None
    assert converter(0, "inteiro", "x") == "0"
    assert converter(False, "booleano", "x") == "false"
    assert converter(Decimal("0.0"), "dinheiro", "x") == "0.0"


def test_texto_com_tipo_errado_falha():
    with pytest.raises(FalhaTransformacao, match="esperado texto"):
        converter(120001, "texto", "x")


def test_linha_de_contratacao_normalizada():
    registro = contratacao_falsa(
        informacaoComplementar="   ", valorTotalHomologado=None, emendaParlamentar=None,
        fontesOrcamentarias=[
            {"codigo": 1, "nome": " Tesouro ", "descricao": "", "dataInclusao": "2026-06-01T00:00:00"}
        ],
    )
    [compra], [fonte] = linhas_contratacoes([linha(registro, "2026-11-08T00:00:00-03:00", "h1")])
    assert compra["informacao_complementar"] is None
    assert compra["valor_total_homologado"] is None
    assert compra["emenda_parlamentar"] is None
    assert compra["valor_total_estimado"] == "1000.5"
    assert compra["srp"] == "true"
    assert compra["amparo_legal_codigo"] == "1"
    assert compra["_hash"] == "h1"
    assert compra["_extraido_em"] == "2026-11-08T00:00:00"
    assert fonte["ordem"] == "1"
    assert fonte["fonte_nome"] == "Tesouro"
    assert fonte["fonte_descricao"] is None


def test_compra_sem_fonte_nao_gera_linha_de_fonte():
    _, fontes = linhas_contratacoes([linha(contratacao_falsa())])
    assert fontes == []


def test_bloco_nulo_deixa_as_colunas_nulas():
    [contrato] = linhas_contratos(
        [linha(contrato_falso())], set(), (CNPJ_MATRIZ,), CNPJ_MATRIZ, date(2023, 1, 1)
    )
    assert contrato["orgao_sub_rogado_cnpj"] is None
    assert contrato["unidade_sub_rogada_uf_sigla"] is None
    assert contrato["processo"] == "67000.000001/2024-01"


# --- CPF -----------------------------------------------------------------------


def test_cpf_valido():
    assert cpf_valido(CPF)
    assert not cpf_valido(CPF_INVALIDO)


def test_ni_fornecedor_de_pessoa_fisica_mascarado():
    assert mascarar_ni_fornecedor(CPF, "PF", "x") == MASCARA


def test_ni_fornecedor_de_pessoa_juridica_e_estrangeira_intacto():
    assert mascarar_ni_fornecedor("11222333000181", "PJ", "x") == "11222333000181"
    assert mascarar_ni_fornecedor("EX0000000", "PE", "x") == "EX0000000"


def test_pessoa_fisica_sem_11_digitos_falha():
    for ni in ("123.456.789-09", "1234567890", "11222333000181"):
        with pytest.raises(FalhaTransformacao, match="não há como mascarar"):
            mascarar_ni_fornecedor(ni, "PF", "x")


def test_contrato_de_pessoa_fisica_mascarado_no_campo_e_no_texto():
    registro = contrato_falso(
        tipoPessoa="PF", niFornecedor=f" {CPF} ",
        objetoContrato=f"Serviço prestado por pessoa física, CPF {CPF}",
        informacaoComplementar="CPF 123.456.789-09.",
    )
    [contrato] = linhas_contratos([linha(registro)], set(), (CNPJ_MATRIZ,), CNPJ_MATRIZ, date(2023, 1, 1))
    assert contrato["ni_fornecedor"] == MASCARA
    assert contrato["objeto_contrato"] == f"Serviço prestado por pessoa física, CPF {MASCARA}"
    assert contrato["informacao_complementar"] == f"CPF {MASCARA}."


def test_texto_livre_cpf_formatado_mascarado_mesmo_com_verificador_invalido():
    assert mascarar_texto("CPF 123.456.789-00") == f"CPF {MASCARA}"


def test_texto_livre_11_digitos_so_com_verificador_valido():
    assert mascarar_texto(f"CPF{CPF}.") == f"CPF{MASCARA}."
    assert mascarar_texto(f"protocolo {CPF_INVALIDO}") == f"protocolo {CPF_INVALIDO}"


def test_texto_livre_sequencia_maior_nao_e_cpf():
    assert mascarar_texto(f"processo 9{CPF}") == f"processo 9{CPF}"
    assert mascarar_texto(f"processo {CPF}0") == f"processo {CPF}0"
    assert mascarar_texto("1123.456.789-09") == "1123.456.789-09"


def test_texto_livre_varios_cpfs():
    assert mascarar_texto(f"{CPF} e 123.456.789-09") == f"{MASCARA} e {MASCARA}"


def test_texto_livre_da_contratacao_mascarado():
    registro = contratacao_falsa(justificativaPresencial=f"Responsável CPF {CPF}")
    [compra], _ = linhas_contratacoes([linha(registro)])
    assert compra["justificativa_presencial"] == f"Responsável CPF {MASCARA}"


# --- ligação com a compra --------------------------------------------------------

FILIAL = "00394429018824"
CNPJS = (CNPJ_MATRIZ, FILIAL)
INICIO = date(2023, 1, 1)


def ligar(referencia, compras=frozenset()):
    return classificar_ligacao(referencia, set(compras), CNPJS, CNPJ_MATRIZ, INICIO, "contratos k")


def test_ligacao_compra_encontrada():
    referencia = f"{FILIAL}-1-000010/2025"
    assert ligar(referencia, {referencia}) == "compra_encontrada"


def test_ligacao_compra_fab_anterior_ao_periodo():
    assert ligar(f"{CNPJ_MATRIZ}-1-000010/2022") == "compra_fab_anterior_ao_periodo"


def test_ligacao_compra_filial_fora_da_lista():
    assert ligar("00394429099999-1-000010/2024") == "compra_filial_fora_da_lista"


def test_ligacao_compra_outro_orgao():
    assert ligar("00489828000155-1-000010/2024") == "compra_outro_orgao"


def test_ligacao_compra_fab_nao_encontrada():
    assert ligar(f"{FILIAL}-1-000010/2023") == "compra_fab_nao_encontrada"
    assert ligar(f"{CNPJ_MATRIZ}-1-000010/2026") == "compra_fab_nao_encontrada"


def test_ligacao_referencia_fora_do_formato_falha():
    for referencia in (None, "", f"{CNPJ_MATRIZ}-2-000010/2024", f"{CNPJ_MATRIZ}-1-10/2024"):
        with pytest.raises(FalhaTransformacao, match="fora do formato"):
            ligar(referencia)


def test_ligacao_no_contrato():
    registro = contrato_falso(compra=f" {CNPJ_MATRIZ}-1-000001/2024 ")
    compras = {f"{CNPJ_MATRIZ}-1-000001/2024"}
    [contrato] = linhas_contratos([linha(registro)], compras, CNPJS, CNPJ_MATRIZ, INICIO)
    assert contrato["ligacao_compra"] == "compra_encontrada"
