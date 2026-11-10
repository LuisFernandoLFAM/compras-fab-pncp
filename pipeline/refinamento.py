"""Regras da transformação, sem banco (spec: specs/transformacao.md).

Versão vigente (decisão 1), de/para das colunas (decisão 3), tipos (decisão 4),
vazios (decisão 5), mascaramento de CPF (decisão 6) e ligação com a compra (decisão 8).
"""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

BRASILIA = timezone(timedelta(hours=-3))  # sem horário de verão desde 2019

TIPOS_SQL = {
    "texto": "VARCHAR",
    "livre": "VARCHAR",  # texto livre: CPF mascarado (decisão 6)
    "inteiro": "INTEGER",
    "booleano": "BOOLEAN",
    "dinheiro": "DECIMAL(18,2)",
    "dinheiro4": "DECIMAL(18,4)",
    "timestamp": "TIMESTAMP",
    "data": "DATE",
}
CASAS_DINHEIRO = {"dinheiro": 2, "dinheiro4": 4}
PRECISAO_DINHEIRO = 18  # DECIMAL(18,2): 16 dígitos inteiros; DECIMAL(18,4): 14
FORMATO_DATA = {
    "timestamp": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"),
    "data": re.compile(r"\d{4}-\d{2}-\d{2}"),
}
LIMITE_INTEIRO = 2**31  # INTEGER do DuckDB

LIGACOES = (
    "compra_encontrada",
    "compra_fab_anterior_ao_periodo",
    "compra_filial_fora_da_lista",
    "compra_outro_orgao",
    "compra_fab_nao_encontrada",
)
REFERENCIA_COMPRA = re.compile(r"(\d{14})-1-\d{6}/(\d{4})")

CPF_FORMATADO = re.compile(r"(?<!\d)(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?!\d)")
CPF_SEGUIDO = re.compile(r"(?<!\d)\d{11}(?!\d)")


class FalhaTransformacao(Exception):
    """Algo na raw impede montar a refined com segurança; a refined anterior fica intacta."""


# --- colunas (decisão 3) -------------------------------------------------------


def snake_case(nome: str) -> str:
    """'numeroControlePNCP' -> 'numero_controle_pncp'."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", nome).lower()


@dataclass(frozen=True)
class Coluna:
    nome: str
    caminho: tuple[str, ...]  # campo no JSON; dois níveis nos blocos aninhados
    tipo: str  # chave de TIPOS_SQL

    @property
    def tipo_sql(self) -> str:
        return TIPOS_SQL[self.tipo]


def campos(*pares: tuple[str, str]) -> list[Coluna]:
    return [Coluna(snake_case(campo), (campo,), tipo) for campo, tipo in pares]


def bloco(nome: str, prefixo: str, *pares: tuple[str, str]) -> list[Coluna]:
    return [Coluna(prefixo + snake_case(campo), (nome, campo), tipo) for campo, tipo in pares]


ORGAO = (("cnpj", "texto"), ("razaoSocial", "texto"), ("esferaId", "texto"), ("poderId", "texto"))
UNIDADE = (
    ("codigoUnidade", "texto"),
    ("nomeUnidade", "texto"),
    ("codigoIbge", "texto"),
    ("municipioNome", "texto"),
    ("ufSigla", "texto"),
    ("ufNome", "texto"),
)

COLUNAS_CONTRATACOES = [
    *campos(
        ("numeroControlePNCP", "texto"),
        ("numeroCompra", "texto"),
        ("anoCompra", "inteiro"),
        ("sequencialCompra", "inteiro"),
        ("processo", "texto"),
        ("objetoCompra", "livre"),
        ("informacaoComplementar", "livre"),
        ("justificativaPresencial", "livre"),
        ("modalidadeId", "inteiro"),
        ("modalidadeNome", "texto"),
        ("modoDisputaId", "inteiro"),
        ("modoDisputaNome", "texto"),
        ("tipoInstrumentoConvocatorioCodigo", "inteiro"),
        ("tipoInstrumentoConvocatorioNome", "texto"),
        ("situacaoCompraId", "inteiro"),
        ("situacaoCompraNome", "texto"),
        ("srp", "booleano"),
        ("emendaParlamentar", "booleano"),
    ),
    *bloco(
        "amparoLegal", "amparo_legal_",
        ("codigo", "inteiro"), ("nome", "texto"), ("descricao", "texto"),
    ),
    *campos(
        ("valorTotalEstimado", "dinheiro"),
        ("valorTotalHomologado", "dinheiro"),
        ("dataInclusao", "timestamp"),
        ("dataPublicacaoPncp", "timestamp"),
        ("dataAtualizacao", "timestamp"),
        ("dataAtualizacaoGlobal", "timestamp"),
        ("dataAberturaProposta", "timestamp"),
        ("dataEncerramentoProposta", "timestamp"),
        ("linkSistemaOrigem", "texto"),
        ("linkProcessoEletronico", "texto"),
        ("usuarioNome", "texto"),
    ),
    *bloco("orgaoEntidade", "orgao_", *ORGAO),
    *bloco("unidadeOrgao", "unidade_", *UNIDADE),
]

# A chave e a ordem vêm de fora do elemento da lista.
COLUNAS_FONTES = [
    Coluna("numero_controle_pncp", (), "texto"),
    Coluna("ordem", (), "inteiro"),
    *[
        Coluna("fonte_" + snake_case(campo), (campo,), tipo)
        for campo, tipo in (
            ("codigo", "inteiro"), ("nome", "texto"), ("descricao", "texto"),
            ("dataInclusao", "timestamp"),
        )
    ],
]

COLUNAS_CONTRATOS = [
    *campos(
        ("numeroControlePNCP", "texto"),
        ("numeroContratoEmpenho", "texto"),
        ("anoContrato", "inteiro"),
        ("sequencialContrato", "inteiro"),
        ("processo", "texto"),
        ("numeroControlePncpCompra", "texto"),
        ("numeroControlePncpAta", "texto"),
        ("objetoContrato", "livre"),
        ("informacaoComplementar", "livre"),
    ),
    *bloco("tipoContrato", "tipo_contrato_", ("id", "inteiro"), ("nome", "texto")),
    *bloco("categoriaProcesso", "categoria_processo_", ("id", "inteiro"), ("nome", "texto")),
    *campos(
        ("receita", "booleano"),
        ("emendaParlamentar", "booleano"),
        ("frutoAdesao", "booleano"),
        ("temRemanejamento", "booleano"),
        ("tipoPessoa", "texto"),
        ("niFornecedor", "texto"),
        ("nomeRazaoSocialFornecedor", "texto"),
        ("codigoPaisFornecedor", "texto"),
        ("valorInicial", "dinheiro"),
        ("valorGlobal", "dinheiro"),
        ("valorParcela", "dinheiro4"),
        ("valorAcumulado", "dinheiro"),
        ("numeroParcelas", "inteiro"),
        ("numeroRetificacao", "inteiro"),
        ("dataAssinatura", "data"),
        ("dataVigenciaInicio", "data"),
        ("dataVigenciaFim", "data"),
        ("dataPublicacaoPncp", "timestamp"),
        ("dataAtualizacao", "timestamp"),
        ("dataAtualizacaoGlobal", "timestamp"),
        ("usuarioNome", "texto"),
    ),
    *bloco("orgaoEntidade", "orgao_", *ORGAO),
    *bloco("unidadeOrgao", "unidade_", *UNIDADE),
    *bloco("orgaoSubRogado", "orgao_sub_rogado_", *ORGAO),
    *bloco("unidadeSubRogada", "unidade_sub_rogada_", *UNIDADE),
    Coluna("ligacao_compra", (), "texto"),  # calculada (decisão 8)
]

COLUNAS_RASTRO = [
    Coluna("_hash", (), "texto"),
    Coluna("_extraido_em", (), "timestamp"),
    Coluna("_execucao_id", (), "texto"),
]


# --- versão vigente (decisão 1) ---------------------------------------------------


@dataclass(frozen=True)
class LinhaRaw:
    registro: dict
    hash: str
    extraido_em: str  # texto com fuso, como gravado pela ingestão
    execucao_id: str


def ler_registro(texto: str) -> dict:
    """Números com casas decimais viram Decimal, sem passar por ponto flutuante."""
    return json.loads(texto, parse_float=Decimal)


def instante(texto: str, contexto: str) -> datetime:
    try:
        quando = datetime.fromisoformat(texto)
    except (TypeError, ValueError) as e:
        raise FalhaTransformacao(f"{contexto}: data com hora inválida {texto!r}") from e
    if quando.tzinfo is None:
        raise FalhaTransformacao(f"{contexto}: data sem fuso {texto!r}")
    return quando


def extraido_em_brasilia(texto: str, contexto: str) -> str:
    """_extraido_em no horário de Brasília, sem o fuso (tipo TIMESTAMP da refined)."""
    return instante(texto, contexto).astimezone(BRASILIA).replace(tzinfo=None).isoformat()


def escolher_vigentes(linhas: list[LinhaRaw], tabela: str) -> list[LinhaRaw]:
    """Uma linha por numeroControlePNCP: a de maior data de atualização, olhando as duas datas.

    Empate na data: vale o _extraido_em mais recente. Empate também nele: falha.
    Devolve as linhas ordenadas pela chave.
    """
    grupos: dict[str, list[tuple[datetime, datetime, LinhaRaw]]] = {}
    for linha in linhas:
        chave = linha.registro.get("numeroControlePNCP")
        if not isinstance(chave, str) or not chave.strip():
            raise FalhaTransformacao(f"{tabela}: registro sem numeroControlePNCP (hash {linha.hash})")
        contexto = f"{tabela} {chave}"
        datas = [
            converter(linha.registro.get(campo), "timestamp", f"{contexto} {campo}")
            for campo in ("dataAtualizacaoGlobal", "dataAtualizacao")
        ]
        datas = [datetime.fromisoformat(d) for d in datas if d is not None]
        if not datas:
            raise FalhaTransformacao(f"{contexto}: sem data de atualização")
        extraido = instante(linha.extraido_em, f"{contexto} _extraido_em")
        grupos.setdefault(chave, []).append((max(datas), extraido, linha))

    vigentes = []
    for chave in sorted(grupos):
        versoes = sorted(grupos[chave], key=lambda v: (v[0], v[1]), reverse=True)
        if len(versoes) > 1 and versoes[0][:2] == versoes[1][:2]:
            raise FalhaTransformacao(
                f"{tabela} {chave}: duas versões com a mesma data de atualização e o mesmo "
                f"_extraido_em ({versoes[0][2].hash}, {versoes[1][2].hash})"
            )
        vigentes.append(versoes[0][2])
    return vigentes


# --- tipos e vazios (decisões 4 e 5) ----------------------------------------------------


def converter_dinheiro(valor, casas: int, contexto: str) -> Decimal | None:
    """Valor exato do número do JSON; falha em vez de arredondar."""
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, Decimal)):
        raise FalhaTransformacao(f"{contexto}: dinheiro não numérico {valor!r}")
    valor = Decimal(valor)
    if not valor.is_finite():
        raise FalhaTransformacao(f"{contexto}: dinheiro não finito {valor!r}")
    expoente = valor.normalize().as_tuple().exponent
    if -expoente > casas:
        raise FalhaTransformacao(
            f"{contexto}: {valor} tem mais de {casas} casas decimais; nada é arredondado"
        )
    inteiros = PRECISAO_DINHEIRO - casas
    if len(str(abs(int(valor)))) > inteiros:
        raise FalhaTransformacao(f"{contexto}: {valor} tem mais de {inteiros} dígitos na parte inteira")
    return valor


def normalizar_texto(valor, contexto: str) -> str | None:
    """Apara as pontas; vazio, ou só espaços, vira nulo."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise FalhaTransformacao(f"{contexto}: esperado texto, veio {valor!r}")
    return valor.strip() or None


def converter(valor, tipo: str, contexto: str) -> str | None:
    """Valor do JSON em texto pronto para o CAST no tipo SQL da coluna; nulo continua nulo."""
    if tipo in ("texto", "livre"):
        texto = normalizar_texto(valor, contexto)
        return mascarar_texto(texto) if tipo == "livre" and texto is not None else texto
    if valor is None:
        return None
    if tipo in CASAS_DINHEIRO:
        return str(converter_dinheiro(valor, CASAS_DINHEIRO[tipo], contexto))
    if tipo == "inteiro":
        if isinstance(valor, bool) or not isinstance(valor, int) or abs(valor) >= LIMITE_INTEIRO:
            raise FalhaTransformacao(f"{contexto}: esperado inteiro, veio {valor!r}")
        return str(valor)
    if tipo == "booleano":
        if not isinstance(valor, bool):
            raise FalhaTransformacao(f"{contexto}: esperado booleano, veio {valor!r}")
        return "true" if valor else "false"
    if tipo in FORMATO_DATA:
        if not isinstance(valor, str) or not FORMATO_DATA[tipo].fullmatch(valor):
            raise FalhaTransformacao(f"{contexto}: data fora do formato {valor!r}")
        try:
            (datetime if tipo == "timestamp" else date).fromisoformat(valor)
        except ValueError as e:
            raise FalhaTransformacao(f"{contexto}: data inexistente {valor!r}") from e
        return valor
    raise ValueError(f"tipo desconhecido: {tipo}")


def valor_no_caminho(registro: dict, caminho: tuple[str, ...], contexto: str):
    """Campo do JSON; o campo de um bloco nulo é nulo."""
    if len(caminho) == 1:
        return registro.get(caminho[0])
    nome, campo = caminho
    conteudo = registro.get(nome)
    if conteudo is None:
        return None
    if not isinstance(conteudo, dict):
        raise FalhaTransformacao(f"{contexto}: o bloco {nome} não é um objeto")
    return conteudo.get(campo)


# --- CPF (decisão 6) ---------------------------------------------------------------


def cpf_valido(digitos: str) -> bool:
    numeros = [int(d) for d in digitos]
    for posicao in (9, 10):
        soma = sum(n * (posicao + 1 - i) for i, n in enumerate(numeros[:posicao]))
        if (soma * 10) % 11 % 10 != numeros[posicao]:
            return False
    return True


def mascara_cpf(digitos: str) -> str:
    """Padrão dos portais de transparência: só os 6 dígitos do meio."""
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


def mascarar_texto(texto: str) -> str:
    """Mascara o CPF formatado e a sequência de 11 dígitos com dígito verificador válido."""
    texto = CPF_FORMATADO.sub(lambda m: mascara_cpf("".join(m.groups())), texto)
    return CPF_SEGUIDO.sub(
        lambda m: mascara_cpf(m.group()) if cpf_valido(m.group()) else m.group(), texto
    )


def mascarar_ni_fornecedor(ni: str | None, tipo_pessoa: str | None, contexto: str) -> str | None:
    if tipo_pessoa != "PF" or ni is None:
        return ni
    if len(ni) != 11 or not ni.isdigit():
        raise FalhaTransformacao(
            f"{contexto} ni_fornecedor: pessoa física sem os 11 dígitos do CPF; não há como mascarar"
        )
    return mascara_cpf(ni)


# --- ligação com a compra (decisão 8) ------------------------------------------------


def classificar_ligacao(
    referencia: str | None, compras: set[str], cnpjs: tuple[str, ...], matriz: str,
    data_inicial: date, contexto: str,
) -> str:
    if referencia in compras:
        return "compra_encontrada"
    partes = REFERENCIA_COMPRA.fullmatch(referencia or "")
    if partes is None:
        raise FalhaTransformacao(
            f"{contexto} numero_controle_pncp_compra: referência fora do formato {referencia!r}"
        )
    cnpj, ano = partes.group(1), int(partes.group(2))
    if cnpj in cnpjs:
        if ano < data_inicial.year:
            return "compra_fab_anterior_ao_periodo"
        return "compra_fab_nao_encontrada"
    if cnpj[:8] == matriz[:8]:
        return "compra_filial_fora_da_lista"
    return "compra_outro_orgao"


# --- linhas da refined ------------------------------------------------------------------


def rastro(linha: LinhaRaw, contexto: str) -> dict[str, str]:
    return {
        "_hash": linha.hash,
        "_extraido_em": extraido_em_brasilia(linha.extraido_em, f"{contexto} _extraido_em"),
        "_execucao_id": linha.execucao_id,
    }


def converter_colunas(colunas: list[Coluna], registro: dict, contexto: str) -> dict[str, str | None]:
    return {
        c.nome: converter(valor_no_caminho(registro, c.caminho, contexto), c.tipo, f"{contexto} {c.nome}")
        for c in colunas
        if c.caminho
    }


def linhas_contratacoes(vigentes: list[LinhaRaw]) -> tuple[list[dict], list[dict]]:
    """Linhas de refined.contratacoes e de refined.contratacoes_fontes."""
    contratacoes, fontes = [], []
    for linha in vigentes:
        chave = linha.registro["numeroControlePNCP"].strip()
        contexto = f"contratacoes {chave}"
        contratacoes.append(
            converter_colunas(COLUNAS_CONTRATACOES, linha.registro, contexto) | rastro(linha, contexto)
        )
        lista = linha.registro.get("fontesOrcamentarias") or []
        if not isinstance(lista, list):
            raise FalhaTransformacao(f"{contexto}: fontesOrcamentarias não é uma lista")
        for ordem, fonte in enumerate(lista, start=1):
            if not isinstance(fonte, dict):
                raise FalhaTransformacao(f"{contexto}: fonte orçamentária {ordem} não é um objeto")
            contexto_fonte = f"contratacoes_fontes {chave} ordem {ordem}"
            fontes.append(
                {"numero_controle_pncp": chave, "ordem": str(ordem)}
                | converter_colunas(COLUNAS_FONTES, fonte, contexto_fonte)
                | rastro(linha, contexto_fonte)
            )
    return contratacoes, fontes


def linhas_contratos(
    vigentes: list[LinhaRaw], compras: set[str], cnpjs: tuple[str, ...], matriz: str,
    data_inicial: date,
) -> list[dict]:
    """Linhas de refined.contratos, com o CPF mascarado e a ligação com a compra."""
    contratos = []
    for linha in vigentes:
        chave = linha.registro["numeroControlePNCP"].strip()
        contexto = f"contratos {chave}"
        valores = converter_colunas(COLUNAS_CONTRATOS, linha.registro, contexto)
        valores["ni_fornecedor"] = mascarar_ni_fornecedor(
            valores["ni_fornecedor"], valores["tipo_pessoa"], contexto
        )
        valores["ligacao_compra"] = classificar_ligacao(
            valores["numero_controle_pncp_compra"], compras, cnpjs, matriz, data_inicial, contexto
        )
        contratos.append(valores | rastro(linha, contexto))
    return contratos
