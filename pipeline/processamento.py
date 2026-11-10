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


def janelas_anuais(inicio: date, fim: date) -> list[tuple[date, date]]:
    """Divide [inicio, fim] em anos civis, recortados nas pontas (sondagem, decisão 1)."""
    if fim < inicio:
        raise ValueError(f"data final {fim} anterior à inicial {inicio}")
    return [
        (max(inicio, date(ano, 1, 1)), min(fim, date(ano, 12, 31)))
        for ano in range(inicio.year, fim.year + 1)
    ]


def janelas_dos_anos(janelas: list[tuple[date, date]], anos: set[int]) -> list[tuple[date, date]]:
    """Mantém só as janelas mensais dos anos em que a sondagem encontrou registros."""
    return [(inicio, fim) for inicio, fim in janelas if inicio.year in anos]


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
    raiz: Path, endpoint: str, cnpj: str, modalidade: int | None, inicio: date, fim: date,
    tipo: str = "janela",
) -> Path:
    """Pasta de uma janela mensal (`janela=...`) ou de uma sondagem anual (`sondagem=...`)."""
    pasta = raiz / nome_endpoint(endpoint) / f"cnpj={cnpj}"
    if modalidade is not None:
        pasta = pasta / f"modalidade={modalidade:02d}"
    return pasta / f"{tipo}={inicio.isoformat()}_{fim.isoformat()}"


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
    tipo: str = "janela",
) -> dict:
    """Conteúdo do _manifesto.json. Janela vazia (HTTP 204) tem total 0 e zero páginas.

    `tipo` é "janela" (mês carregado na raw) ou "sondagem" (ano, só o total).
    """
    return {
        "tipo": tipo,
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


# Histórico de execuções: tuplas (execucao_id, modo, status, dados_ate) em ordem
# cronológica, como em raw.execucoes.
Historico = list[tuple[str, str, str, date | None]]

MODOS_COM_API = ("completa", "incremental")


def id_execucao(rodada_id: str, cnpj: str) -> str:
    return f"{rodada_id}-{cnpj}"


def cnpj_das_execucoes(manifestos: list[dict]) -> dict[str, set[str]]:
    """CNPJs de cada execução, pelos manifestos que ela gravou na landing."""
    cnpjs: dict[str, set[str]] = {}
    for manifesto in manifestos:
        cnpjs.setdefault(manifesto["execucao_id"], set()).add(manifesto["cnpj"])
    return cnpjs


def completar_execucoes_antigas(
    execucoes: list[dict], cnpj_por_execucao: dict[str, set[str]], matriz: str
) -> tuple[list[dict], list[str]]:
    """Preenche `cnpj` e `rodada_id` das execuções anteriores à lista de CNPJs.

    O CNPJ vem dos manifestos da execução; sem manifesto, fica a matriz.
    Devolve (execuções completas, ids que ficaram com a matriz por falta de manifesto).
    """
    completas, sem_manifesto = [], []
    for execucao in execucoes:
        if execucao.get("cnpj"):
            completas.append(execucao)
            continue
        execucao_id = execucao["execucao_id"]
        cnpjs = cnpj_por_execucao.get(execucao_id, set())
        if len(cnpjs) > 1:
            raise ValueError(f"execução antiga {execucao_id} com manifestos de vários CNPJs: {sorted(cnpjs)}")
        if cnpjs:
            [cnpj] = cnpjs
        else:
            cnpj = matriz
            sem_manifesto.append(execucao_id)
        completas.append({**execucao, "cnpj": cnpj, "rodada_id": execucao.get("rodada_id") or execucao_id})
    return completas, sem_manifesto


def ids_retomaveis(historico: Historico) -> set[str]:
    """Execuções cujas janelas concluídas podem ser aproveitadas numa retomada.

    São as cargas completas e incrementais que falharam depois da última carga
    completa ou incremental com sucesso. Depois de um sucesso, nada é
    aproveitado. A reconstrução não mexe na landing e é ignorada.
    """
    ids: set[str] = set()
    for execucao_id, modo, status, _ in historico:
        if modo not in MODOS_COM_API:
            continue
        if status == "sucesso":
            ids = set()
        else:
            ids.add(execucao_id)
    return ids


def janela_ja_concluida(manifesto: dict | None, retomaveis: set[str]) -> bool:
    return manifesto is not None and manifesto.get("execucao_id") in retomaveis


def ultimo_dados_ate(historico: Historico) -> date | None:
    """`dados_ate` da última execução com sucesso que o tenha preenchido."""
    for _, _, status, dados_ate in reversed(historico):
        if status == "sucesso" and dados_ate is not None:
            return dados_ate
    return None


def escolher_modo(historico: Historico, completa: bool, reconstruir: bool) -> str:
    if reconstruir:
        return "reconstrucao"
    if completa or ultimo_dados_ate(historico) is None:
        return "completa"
    return "incremental"


def janela_incremental(historico: Historico, ate: date) -> tuple[date, date] | None:
    """Período do incremental: do dia seguinte ao último `dados_ate` até `ate`.

    Devolve None quando não há nada a consultar (início depois do fim).
    """
    anterior = ultimo_dados_ate(historico)
    if anterior is None:
        raise ValueError("incremental sem execução anterior com sucesso")
    inicio = anterior + timedelta(days=1)
    return None if inicio > ate else (inicio, ate)


def ordem_reconstrucao(manifestos: list[dict]) -> list[dict]:
    """Ordena as janelas pela ordem em que foram extraídas."""
    return sorted(
        manifestos,
        key=lambda m: (
            datetime.fromisoformat(m["concluido_em"]),
            m["endpoint"],
            m["modalidade"] or 0,
            m["janela_inicio"],
        ),
    )
