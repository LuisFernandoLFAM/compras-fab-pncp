"""Contrato de dados (spec: specs/transformacao.md, decisão 9): aviso para o novo, falha para o que some.

Caminhos: `campo` no primeiro nível, `bloco.campo` nos blocos e
`fontesOrcamentarias[].campo` nos elementos da lista de fontes.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from pipeline.refinamento import (
    COLUNAS_CONTRATACOES,
    COLUNAS_CONTRATOS,
    COLUNAS_FONTES,
    DESCARTADOS,
    LinhaRaw,
)

LISTA_FONTES = "fontesOrcamentarias"
# Conferidos só quando existem; os demais blocos são obrigatórios.
BLOCOS_OPCIONAIS = frozenset({"orgaoSubRogado", "unidadeSubRogada"})


@dataclass(frozen=True)
class Esperado:
    """Campos da tabela de/para (obrigatórios) e descartados de uma tabela da raw."""

    primeiro_nivel: frozenset[str]
    blocos: dict[str, frozenset[str]]
    fontes: frozenset[str]
    descartados: frozenset[str]


def esperado(tabela: str) -> Esperado:
    colunas = COLUNAS_CONTRATACOES if tabela == "contratacoes" else COLUNAS_CONTRATOS
    primeiro_nivel = {c.caminho[0] for c in colunas if c.caminho}
    blocos: dict[str, set[str]] = defaultdict(set)
    for c in colunas:
        if len(c.caminho) == 2:
            blocos[c.caminho[0]].add(c.caminho[1])
    fontes = set()
    if tabela == "contratacoes":
        primeiro_nivel.add(LISTA_FONTES)
        fontes = {c.caminho[0] for c in COLUNAS_FONTES if c.caminho}
    return Esperado(
        frozenset(primeiro_nivel),
        {nome: frozenset(campos) for nome, campos in blocos.items()},
        frozenset(fontes),
        frozenset(DESCARTADOS[tabela]),
    )


def tem_dado(valor) -> bool:
    """Dado que sobrevive à decisão 5: nulo, texto vazio e bloco ou lista vazios não contam."""
    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, (dict, list)):
        return bool(valor)
    return valor is not None


def campos_novos(registro: dict, esp: Esperado) -> set[str]:
    """Caminhos fora dos campos conhecidos; um bloco novo conta uma vez, sem descer nele."""
    novos = set()
    for chave, valor in registro.items():
        if chave not in esp.primeiro_nivel and chave not in esp.descartados:
            novos.add(chave)
        elif chave in esp.blocos and isinstance(valor, dict):
            novos |= {f"{chave}.{campo}" for campo in valor if campo not in esp.blocos[chave]}
        elif chave == LISTA_FONTES and isinstance(valor, list):
            for elemento in valor:
                if isinstance(elemento, dict):
                    novos |= {f"{LISTA_FONTES}[].{campo}" for campo in elemento if campo not in esp.fontes}
    return novos


def descartados_com_dado(registro: dict, esp: Esperado) -> set[str]:
    return {campo for campo in esp.descartados if tem_dado(registro.get(campo))}


def campos_ausentes(registro: dict, esp: Esperado) -> tuple[set[str], set[str]]:
    """Chaves ausentes no JSON: (da tabela de/para, descartadas). Chave com nulo não conta."""
    ausentes = {campo for campo in esp.primeiro_nivel if campo not in registro}
    for nome, campos in esp.blocos.items():
        if nome not in registro:
            continue  # já contado no primeiro nível
        conteudo = registro[nome]
        if conteudo is None and nome in BLOCOS_OPCIONAIS:
            continue
        if not isinstance(conteudo, dict):
            ausentes |= {f"{nome}.{campo}" for campo in campos}
            continue
        ausentes |= {f"{nome}.{campo}" for campo in campos if campo not in conteudo}
    lista = registro.get(LISTA_FONTES)
    if isinstance(lista, list):
        for elemento in lista:
            if isinstance(elemento, dict):
                ausentes |= {f"{LISTA_FONTES}[].{campo}" for campo in esp.fontes if campo not in elemento}
    return ausentes, {campo for campo in esp.descartados if campo not in registro}


@dataclass
class ResultadoContrato:
    avisos: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    registros_ultima_rodada: int = 0


def contar(linhas: list[LinhaRaw], achar) -> dict[str, int]:
    """Registros distintos (numeroControlePNCP) em que cada caminho aparece."""
    chaves: dict[str, set[str]] = defaultdict(set)
    for linha in linhas:
        for caminho in achar(linha.registro):
            chaves[caminho].add(linha.registro.get("numeroControlePNCP"))
    return {caminho: len(chaves[caminho]) for caminho in sorted(chaves)}


def conferir_contrato(
    tabela: str, todas: list[LinhaRaw], ultima_rodada: list[LinhaRaw]
) -> ResultadoContrato:
    """Campos novos e descartados com dado em toda a raw; ausentes só na última rodada."""
    esp = esperado(tabela)
    resultado = ResultadoContrato(
        registros_ultima_rodada=len({l.registro.get("numeroControlePNCP") for l in ultima_rodada})
    )
    for caminho, n in contar(todas, lambda r: campos_novos(r, esp)).items():
        resultado.avisos.append(f"{tabela}: campo novo {caminho} em {n} registros")
    for campo, n in contar(todas, lambda r: descartados_com_dado(r, esp)).items():
        resultado.avisos.append(f"{tabela}: campo descartado {campo} preenchido em {n} registros")
    for campo, n in contar(ultima_rodada, lambda r: campos_ausentes(r, esp)[1]).items():
        resultado.avisos.append(
            f"{tabela}: campo descartado {campo} ausente em {n} registros da última rodada"
        )
    for campo, n in contar(ultima_rodada, lambda r: campos_ausentes(r, esp)[0]).items():
        resultado.falhas.append(f"{tabela}: campo {campo} ausente em {n} registros da última rodada")
    return resultado
