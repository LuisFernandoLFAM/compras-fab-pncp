"""Funções puras da ingestão (decisão 10).

Nada aqui faz chamada HTTP, lê arquivo ou abre banco: tudo é testável com
respostas falsas.
"""

import hashlib
import json
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path


class ClasseResposta(Enum):
    SUCESSO = "sucesso"
    VAZIO = "vazio"
    FALHA_TEMPORARIA = "falha_temporaria"
    FALHA_DEFINITIVA = "falha_definitiva"


class RespostaInvalida(Exception):
    """A API respondeu com sucesso, mas o corpo não tem o formato esperado."""


def janelas_mensais(inicio: date, fim: date) -> list[tuple[date, date]]:
    """Divide [inicio, fim] em janelas de no máximo um mês civil."""
    if fim < inicio:
        raise ValueError(f"data final {fim} anterior à inicial {inicio}")
    janelas = []
    atual = inicio
    while atual <= fim:
        proximo_mes = (atual.replace(day=1) + timedelta(days=32)).replace(day=1)
        janelas.append((atual, min(proximo_mes - timedelta(days=1), fim)))
        atual = proximo_mes
    return janelas


def montar_parametros(
    *,
    inicio: date,
    fim: date,
    pagina: int,
    tamanho_pagina: int,
    filtro_cnpj: str,
    cnpj: str,
    filtro_modalidade: str | None = None,
    modalidade: int | None = None,
) -> dict:
    parametros = {
        "dataInicial": inicio.strftime("%Y%m%d"),
        "dataFinal": fim.strftime("%Y%m%d"),
        filtro_cnpj: cnpj,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    if modalidade is not None:
        if filtro_modalidade is None:
            raise ValueError("modalidade informada para endpoint sem filtro de modalidade")
        parametros[filtro_modalidade] = modalidade
    return parametros


def classificar_status(codigo: int) -> ClasseResposta:
    """Decide o que fazer com um código HTTP. Erro nunca vira vazio (decisão 6)."""
    if codigo == 200:
        return ClasseResposta.SUCESSO
    if codigo == 204:
        return ClasseResposta.VAZIO
    if codigo == 429 or 500 <= codigo <= 599:
        return ClasseResposta.FALHA_TEMPORARIA
    return ClasseResposta.FALHA_DEFINITIVA


def espera_429(retry_after: str | None, padrao: float, agora: datetime) -> float:
    """Segundos de espera após um HTTP 429.

    Usa o cabeçalho Retry-After (em segundos ou como data HTTP) quando presente e
    válido; senão, a espera padrão da tentativa.
    """
    if retry_after is None:
        return padrao
    valor = retry_after.strip()
    if valor.isdigit():
        return float(valor)
    try:
        quando = parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return padrao
    if quando.tzinfo is None:
        return padrao
    return max(0.0, (quando - agora).total_seconds())


def ler_pagina(corpo: bytes) -> dict:
    """Interpreta o corpo de uma resposta 200 e confere os campos de paginação."""
    try:
        pagina = json.loads(corpo)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RespostaInvalida(f"corpo não é JSON válido: {e}") from e
    if not isinstance(pagina, dict):
        raise RespostaInvalida("corpo não é um objeto JSON")
    faltando = {"data", "totalRegistros", "totalPaginas"} - pagina.keys()
    if faltando:
        raise RespostaInvalida(f"campos ausentes na resposta: {sorted(faltando)}")
    if not isinstance(pagina["data"], list):
        raise RespostaInvalida("campo 'data' não é uma lista")
    return pagina


def nome_endpoint(caminho: str) -> str:
    """'/v1/contratacoes/publicacao' -> 'contratacoes_publicacao'."""
    partes = [p for p in caminho.strip("/").split("/") if p]
    if partes and partes[0] == "v1":
        partes = partes[1:]
    return "_".join(partes)


def caminho_janela(
    raiz: Path, endpoint: str, cnpj: str, modalidade: int | None, inicio: date, fim: date
) -> Path:
    pasta = raiz / nome_endpoint(endpoint) / f"cnpj={cnpj}"
    if modalidade is not None:
        pasta = pasta / f"modalidade={modalidade:02d}"
    return pasta / f"janela={inicio.isoformat()}_{fim.isoformat()}"


def nome_arquivo_pagina(pagina: int) -> str:
    return f"pagina_{pagina:03d}.json"


def texto_registro(registro: dict) -> str:
    """Texto guardado na coluna 'registro': ordem original das chaves."""
    return json.dumps(registro, ensure_ascii=False)


def hash_registro(registro: dict) -> str:
    """SHA-256 da forma canônica, para a mesma versão com chaves em outra ordem dar o mesmo hash."""
    canonico = json.dumps(registro, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def linhas_da_resposta(
    pagina: dict,
    *,
    endpoint: str,
    modalidade: int | None,
    inicio: date,
    fim: date,
    numero_pagina: int,
    arquivo_origem: str,
    extraido_em: str,
    execucao_id: str,
) -> list[dict]:
    """Uma linha da camada bruta por registro da página; todas as colunas em texto."""
    return [
        {
            "registro": texto_registro(registro),
            "_hash": hash_registro(registro),
            "_endpoint": endpoint,
            "_modalidade": None if modalidade is None else str(modalidade),
            "_janela_inicio": inicio.isoformat(),
            "_janela_fim": fim.isoformat(),
            "_pagina": str(numero_pagina),
            "_arquivo_origem": arquivo_origem,
            "_extraido_em": extraido_em,
            "_execucao_id": execucao_id,
        }
        for registro in pagina["data"]
    ]


def conferir_janela(total_informado: int, registros: list[dict], chave: str) -> list[str]:
    """Confere contagem e duplicatas de uma janela (decisão 7). Lista vazia = janela ok."""
    problemas = []
    if len(registros) != total_informado:
        problemas.append(
            f"contagem: API informou {total_informado}, foram salvos {len(registros)}"
        )
    sem_chave = sum(1 for r in registros if r.get(chave) is None)
    if sem_chave:
        problemas.append(f"{sem_chave} registro(s) sem a chave '{chave}'")
    distintas = len({r.get(chave) for r in registros if r.get(chave) is not None})
    if distintas != len(registros) - sem_chave:
        problemas.append(
            f"duplicatas: {len(registros) - sem_chave} registros e {distintas} chaves distintas"
        )
    return problemas


def montar_manifesto(
    *,
    endpoint: str,
    cnpj: str,
    modalidade: int | None,
    inicio: date,
    fim: date,
    total_api: int,
    total_salvo: int,
    extracoes: list[dict],
    execucao_id: str,
    concluido_em: str,
) -> dict:
    """Conteúdo do _manifesto.json. Janela vazia (HTTP 204) tem total 0 e zero páginas."""
    return {
        "endpoint": endpoint,
        "cnpj": cnpj,
        "modalidade": modalidade,
        "janela_inicio": inicio.isoformat(),
        "janela_fim": fim.isoformat(),
        "total_api": total_api,
        "total_salvo": total_salvo,
        "paginas": len(extracoes),
        "extracoes": extracoes,  # [{"pagina", "arquivo", "extraido_em"}]
        "execucao_id": execucao_id,
        "concluido_em": concluido_em,
    }


def ids_retomaveis(historico: list[tuple[str, str, str]]) -> set[str]:
    """Execuções cujas janelas concluídas podem ser aproveitadas numa retomada.

    `historico` são tuplas (execucao_id, modo, status) em ordem cronológica. São
    as cargas completas que falharam depois da última execução com sucesso; se a
    última execução terminou com sucesso, nada é aproveitado e a carga completa
    baixa tudo de novo.
    """
    ids: set[str] = set()
    for execucao_id, modo, status in historico:
        if status == "sucesso":
            ids = set()
        elif modo == "completa":
            ids.add(execucao_id)
    return ids


def janela_ja_concluida(manifesto: dict | None, retomaveis: set[str]) -> bool:
    return manifesto is not None and manifesto.get("execucao_id") in retomaveis
