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
        self.timeouts: list[float | None] = []

    @property
    def chamadas(self) -> int:
        return len(self.parametros)

    def buscar(
        self, endpoint: str, parametros: dict, contexto: str, timeout: float | None = None,
        novas_tentativas: int | None = None,
    ) -> Resposta:
        self.parametros.append(parametros)
        self.timeouts.append(timeout)
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


# --- registros falsos da camada bruta (transformação) ------------------------

CNPJ_MATRIZ = "00394429000100"


def contratacao_falsa(chave: str = f"{CNPJ_MATRIZ}-1-000001/2024", **campos) -> dict:
    """Contratação com todos os campos da spec, valores inventados."""
    registro = {
        "numeroControlePNCP": chave,
        "numeroCompra": "90001",
        "anoCompra": 2024,
        "sequencialCompra": 1,
        "processo": "67000.000001/2024-01",
        "objetoCompra": "Aquisição de material de expediente",
        "informacaoComplementar": "",
        "justificativaPresencial": None,
        "modalidadeId": 6,
        "modalidadeNome": "Pregão - Eletrônico",
        "modoDisputaId": 1,
        "modoDisputaNome": "Aberto",
        "tipoInstrumentoConvocatorioCodigo": 1,
        "tipoInstrumentoConvocatorioNome": "Edital",
        "situacaoCompraId": 1,
        "situacaoCompraNome": "Divulgada no PNCP",
        "srp": True,
        "emendaParlamentar": None,
        "amparoLegal": {"codigo": 1, "nome": "Lei 14.133/2021, Art. 28, I", "descricao": "pregão"},
        "valorTotalEstimado": 1000.5,
        "valorTotalHomologado": None,
        "dataInclusao": "2024-03-01T10:00:00",
        "dataPublicacaoPncp": "2024-03-01T10:00:00",
        "dataAtualizacao": "2024-03-02T10:00:00",
        "dataAtualizacaoGlobal": "2024-03-02T10:00:00",
        "dataAberturaProposta": "2024-03-05T08:00:00",
        "dataEncerramentoProposta": "2024-03-15T08:00:00",
        "linkSistemaOrigem": None,
        "linkProcessoEletronico": None,
        "usuarioNome": "Sistema de compras",
        "orgaoEntidade": {
            "cnpj": CNPJ_MATRIZ, "razaoSocial": "COMANDO DA AERONAUTICA", "esferaId": "F", "poderId": "E",
        },
        "unidadeOrgao": {
            "codigoUnidade": "120001", "nomeUnidade": "UNIDADE TESTE", "codigoIbge": "5300108",
            "municipioNome": "Brasília", "ufSigla": "DF", "ufNome": "Distrito Federal",
        },
        "orgaoSubRogado": None,
        "unidadeSubRogada": None,
        "fontesOrcamentarias": [],
    }
    registro.update(campos)
    return registro


def contrato_falso(
    chave: str = f"{CNPJ_MATRIZ}-2-000001/2024",
    compra: str = f"{CNPJ_MATRIZ}-1-000001/2024",
    **campos,
) -> dict:
    """Contrato com todos os campos da spec, valores inventados."""
    registro = {
        "numeroControlePNCP": chave,
        "numeroContratoEmpenho": "00001/2024",
        "anoContrato": 2024,
        "sequencialContrato": 1,
        "processo": " 67000.000001/2024-01 ",
        "numeroControlePncpCompra": compra,
        "numeroControlePncpAta": None,
        "objetoContrato": "Fornecimento de material de expediente",
        "informacaoComplementar": None,
        "tipoContrato": {"id": 1, "nome": "Contrato"},
        "categoriaProcesso": {"id": 2, "nome": "Compras"},
        "receita": False,
        "emendaParlamentar": None,
        "frutoAdesao": None,
        "temRemanejamento": None,
        "tipoPessoa": "PJ",
        "niFornecedor": "11222333000181",
        "nomeRazaoSocialFornecedor": "EMPRESA FICTICIA LTDA",
        "codigoPaisFornecedor": None,
        "valorInicial": 900.25,
        "valorGlobal": 900.25,
        "valorParcela": 75.0208,
        "valorAcumulado": None,
        "numeroParcelas": 12,
        "numeroRetificacao": 0,
        "dataAssinatura": "2024-04-01",
        "dataVigenciaInicio": "2024-04-01",
        "dataVigenciaFim": None,
        "dataPublicacaoPncp": "2024-04-02T09:00:00",
        "dataAtualizacao": "2024-04-02T09:00:00",
        "dataAtualizacaoGlobal": "2024-04-02T09:00:00",
        "usuarioNome": "Sistema de contratos",
        "orgaoEntidade": {
            "cnpj": CNPJ_MATRIZ, "razaoSocial": "COMANDO DA AERONAUTICA", "esferaId": "F", "poderId": "E",
        },
        "unidadeOrgao": {
            "codigoUnidade": "120001", "nomeUnidade": "UNIDADE TESTE", "codigoIbge": "5300108",
            "municipioNome": "Brasília", "ufSigla": "DF", "ufNome": "Distrito Federal",
        },
        "orgaoSubRogado": None,
        "unidadeSubRogada": None,
        "identificadorCipi": None,
        "urlCipi": None,
        "niFornecedorSubContratado": None,
        "nomeFornecedorSubContratado": None,
        "tipoPessoaSubContratada": None,
    }
    registro.update(campos)
    return registro
