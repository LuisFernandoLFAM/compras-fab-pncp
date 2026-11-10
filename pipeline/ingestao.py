"""Etapa 1: ingestão do PNCP para a camada bruta (spec: specs/ingestao.md).

    uv run python -m pipeline.ingestao                    # completa na 1ª vez, incremental depois
    uv run python -m pipeline.ingestao --completa         # força a carga completa
    uv run python -m pipeline.ingestao --ate 2026-10-31   # define a data final
    uv run python -m pipeline.ingestao --reconstruir      # recria o banco a partir da landing, sem API

Cada CNPJ do config.toml (matriz e filiais) tem o próprio ponto de partida (decisão 12).
"""

import argparse
import logging
import sys
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline import banco, landing
from pipeline.api import ClienteAPI, FalhaAPI, agora
from pipeline.config import Config, Endpoint, carregar_config
from pipeline.processamento import (
    ClasseResposta,
    Historico,
    RespostaInvalida,
    caminho_janela,
    cnpj_das_execucoes,
    completar_execucoes_antigas,
    conferir_janela,
    escolher_modo,
    id_execucao,
    ids_retomaveis,
    janela_incremental,
    janela_ja_concluida,
    janelas_anuais,
    janelas_dos_anos,
    janelas_mensais,
    ler_pagina,
    linhas_da_resposta,
    montar_manifesto,
    montar_parametros,
    ordem_reconstrucao,
    ultimo_dados_ate,
)

log = logging.getLogger("ingestao")


class FalhaConferencia(Exception):
    """A janela não conferiu nem depois de baixada de novo (decisão 7)."""


class FalhaReconstrucao(Exception):
    """A landing tem algo que a reconstrução não sabe carregar."""


@dataclass
class Totais:
    linhas_novas: int = 0
    linhas_ja_existentes: int = 0


@dataclass
class Rodada:
    """Uma chamada do comando: um cliente da API compartilhado por todos os CNPJs."""

    cfg: Config
    id: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )
    _cliente: ClienteAPI | None = None

    @property
    def cliente(self) -> ClienteAPI:
        # Criado só quando algum CNPJ precisa da API.
        if self._cliente is None:
            self._cliente = ClienteAPI(self.cfg)
        return self._cliente


def descrever(cnpj: str, caminho_api: str, modalidade: int | None, inicio: date, fim: date) -> str:
    texto = f"CNPJ {cnpj}, endpoint {caminho_api}"
    if modalidade is not None:
        texto += f", modalidade {modalidade}"
    return texto + f", janela {inicio}_{fim}"


def caminho_do_modo(endpoint: Endpoint, modo: str) -> str:
    return endpoint.publicacao if modo == "completa" else endpoint.atualizacao


# --- download de janelas ----------------------------------------------------


def _baixar_paginas(
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, caminho_api: str, cnpj: str,
    modalidade: int | None, inicio: date, fim: date, pasta: Path,
) -> tuple[int, list[dict], list[dict]]:
    """Percorre as páginas de uma janela. Devolve (total da API, registros, extrações)."""
    registros: list[dict] = []
    extracoes: list[dict] = []
    total_api = 0
    total_paginas = 1
    numero = 1
    while numero <= total_paginas:
        contexto = f"{descrever(cnpj, caminho_api, modalidade, inicio, fim)}, página {numero}"
        parametros = montar_parametros(
            inicio=inicio, fim=fim, pagina=numero, tamanho_pagina=cfg.tamanho_pagina,
            filtro_cnpj=endpoint.filtro_cnpj, cnpj=cnpj,
            filtro_modalidade=endpoint.filtro_modalidade, modalidade=modalidade,
        )
        resposta = cliente.buscar(caminho_api, parametros, contexto)
        if resposta.classe is ClasseResposta.VAZIO:
            # Vazio na 1ª página é janela sem registros; numa página seguinte,
            # a contagem não vai fechar e a conferência trata.
            break
        try:
            pagina = ler_pagina(resposta.corpo)
        except RespostaInvalida as e:
            raise FalhaAPI(f"resposta inválida em {contexto}: {e}") from e
        arquivo = landing.salvar_pagina(pasta, numero, resposta.corpo)
        extracoes.append(
            {"pagina": numero, "arquivo": arquivo.name, "extraido_em": resposta.extraido_em}
        )
        if numero == 1:
            total_api = pagina["totalRegistros"]
            total_paginas = pagina["totalPaginas"]
        registros.extend(pagina["data"])
        numero += 1
    return total_api, registros, extracoes


def processar_janela(
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, cnpj: str, modalidade: int | None,
    inicio: date, fim: date, execucao_id: str, retomaveis: set[str],
    caminho_api: str | None = None,
) -> tuple[dict, bool]:
    """Garante a janela completa na landing. Devolve (manifesto, se foi baixada agora).

    `caminho_api` é o endpoint consultado; por padrão, o de publicação.
    """
    caminho_api = caminho_api or endpoint.publicacao
    pasta = caminho_janela(cfg.landing, caminho_api, cnpj, modalidade, inicio, fim)
    manifesto = landing.ler_manifesto(pasta)
    if janela_ja_concluida(manifesto, retomaveis):
        return manifesto, False

    descricao = descrever(cnpj, caminho_api, modalidade, inicio, fim)
    for tentativa in (1, 2):
        landing.limpar_janela(pasta)
        total_api, registros, extracoes = _baixar_paginas(
            cliente, cfg, endpoint, caminho_api, cnpj, modalidade, inicio, fim, pasta
        )
        problemas = conferir_janela(total_api, registros, endpoint.chave)
        if not problemas:
            manifesto = montar_manifesto(
                endpoint=caminho_api, cnpj=cnpj, modalidade=modalidade,
                inicio=inicio, fim=fim, total_api=total_api, total_salvo=len(registros),
                extracoes=extracoes, execucao_id=execucao_id, concluido_em=agora(),
            )
            landing.gravar_manifesto(pasta, manifesto)
            return manifesto, True
        log.warning(
            "conferência falhou (tentativa %d) em %s: %s", tentativa, descricao, "; ".join(problemas)
        )
    raise FalhaConferencia(f"conferência falhou duas vezes em {descricao}: " + "; ".join(problemas))


def processar_sondagem(
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, cnpj: str, modalidade: int | None,
    inicio: date, fim: date, execucao_id: str, retomaveis: set[str],
) -> tuple[dict, bool]:
    """Sondagem anual (decisão 1): uma chamada, só o totalRegistros. Devolve (manifesto, baixada).

    A resposta fica na landing como prova, numa pasta `sondagem=...` que a carga
    da raw não lê. Se a sondagem falhar, o manifesto registra o erro e
    `total_api` fica vazio: o ano é consultado mês a mês, nunca pulado.
    """
    caminho_api = endpoint.publicacao
    pasta = caminho_janela(cfg.landing, caminho_api, cnpj, modalidade, inicio, fim, "sondagem")
    manifesto = landing.ler_manifesto(pasta)
    if janela_ja_concluida(manifesto, retomaveis):
        return manifesto, False

    landing.limpar_janela(pasta)
    contexto = f"sondagem, {descrever(cnpj, caminho_api, modalidade, inicio, fim)}"
    parametros = montar_parametros(
        inicio=inicio, fim=fim, pagina=1, tamanho_pagina=cfg.tamanho_pagina_sondagem,
        filtro_cnpj=endpoint.filtro_cnpj, cnpj=cnpj,
        filtro_modalidade=endpoint.filtro_modalidade, modalidade=modalidade,
    )
    total_api, total_salvo, extracoes, erro = 0, 0, [], None
    try:
        resposta = cliente.buscar(
            caminho_api, parametros, contexto,
            timeout=cfg.timeout_sondagem, novas_tentativas=cfg.novas_tentativas_sondagem,
        )
        if resposta.classe is not ClasseResposta.VAZIO:
            try:
                pagina = ler_pagina(resposta.corpo)
            except RespostaInvalida as e:
                raise FalhaAPI(f"resposta inválida em {contexto}: {e}") from e
            arquivo = landing.salvar_pagina(pasta, 1, resposta.corpo)
            extracoes = [{"pagina": 1, "arquivo": arquivo.name, "extraido_em": resposta.extraido_em}]
            total_api, total_salvo = pagina["totalRegistros"], len(pagina["data"])
    except FalhaAPI as e:
        # Só se perde o atalho: o ano desce mês a mês, e nenhum mês é pulado.
        log.warning("%s; o ano será consultado mês a mês", e)
        landing.limpar_janela(pasta)
        total_api, total_salvo, extracoes, erro = None, 0, [], str(e)
    manifesto = montar_manifesto(
        endpoint=caminho_api, cnpj=cnpj, modalidade=modalidade, inicio=inicio, fim=fim,
        total_api=total_api, total_salvo=total_salvo, extracoes=extracoes,
        execucao_id=execucao_id, concluido_em=agora(), tipo="sondagem",
    )
    if erro is not None:
        manifesto["consultado_sem_sondagem"] = True
        manifesto["erro"] = erro
    landing.gravar_manifesto(pasta, manifesto)
    return manifesto, True


def sondar(
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, cnpj: str, modalidade: int | None,
    inicio: date, ate: date, execucao_id: str, retomaveis: set[str],
) -> dict[int, int | None]:
    """Total de registros por ano no período, pela sondagem anual (None: sondagem falhou)."""
    totais = {}
    for ano_inicio, ano_fim in janelas_anuais(inicio, ate):
        manifesto, baixada = processar_sondagem(
            cliente, cfg, endpoint, cnpj, modalidade, ano_inicio, ano_fim, execucao_id, retomaveis
        )
        totais[ano_inicio.year] = manifesto["total_api"]
        log.info(
            "sondagem, %s: %s (%s)",
            descrever(cnpj, endpoint.publicacao, modalidade, ano_inicio, ano_fim),
            "sem sondagem, mês a mês" if manifesto["total_api"] is None
            else f"{manifesto['total_api']} registros",
            "baixada" if baixada else "retomada",
        )
    return totais


def carregar_janela(con, cfg: Config, endpoint: Endpoint, manifesto: dict) -> tuple[int, int]:
    """Lê as páginas da janela na landing e acrescenta as linhas na raw.

    `_execucao_id` é o da execução que extraiu a janela, lido do manifesto.
    """
    inicio = date.fromisoformat(manifesto["janela_inicio"])
    fim = date.fromisoformat(manifesto["janela_fim"])
    caminho_api = manifesto["endpoint"]
    pasta = caminho_janela(
        cfg.landing, caminho_api, manifesto["cnpj"], manifesto["modalidade"], inicio, fim
    )
    linhas = []
    for extracao in manifesto["extracoes"]:
        arquivo = pasta / extracao["arquivo"]
        linhas += linhas_da_resposta(
            ler_pagina(arquivo.read_bytes()),
            endpoint=caminho_api,
            modalidade=manifesto["modalidade"],
            inicio=inicio,
            fim=fim,
            numero_pagina=extracao["pagina"],
            arquivo_origem=arquivo.relative_to(cfg.raiz).as_posix(),
            extraido_em=extracao["extraido_em"],
            execucao_id=manifesto["execucao_id"],
        )
    return banco.inserir_linhas(con, endpoint.tabela, linhas)


def carregar_periodo(
    con, cliente: ClienteAPI, cfg: Config, cnpj: str, modo: str, inicio: date, ate: date,
    execucao_id: str, retomaveis: set[str], totais: Totais,
) -> None:
    """Carga completa ou incremental de um CNPJ: endpoints, modalidades e janelas mensais.

    Na carga completa, a sondagem anual decide quais anos descem mês a mês.
    """
    mensais = janelas_mensais(inicio, ate)
    for endpoint in cfg.endpoints:
        caminho_api = caminho_do_modo(endpoint, modo)
        modalidades = cfg.modalidades if endpoint.filtro_modalidade else (None,)
        for modalidade in modalidades:
            janelas, sondados = mensais, {}
            if modo == "completa":
                sondados = sondar(
                    cliente, cfg, endpoint, cnpj, modalidade, inicio, ate, execucao_id, retomaveis
                )
                # Total vazio (sondagem que falhou) conta como ano com dado.
                janelas = janelas_dos_anos(
                    mensais, {ano for ano, total in sondados.items() if total is None or total}
                )
            por_ano: Counter[int] = Counter()
            for janela_inicio, janela_fim in janelas:
                manifesto, baixada = processar_janela(
                    cliente, cfg, endpoint, cnpj, modalidade, janela_inicio, janela_fim,
                    execucao_id, retomaveis, caminho_api,
                )
                por_ano[janela_inicio.year] += manifesto["total_api"]
                novas, existentes = carregar_janela(con, cfg, endpoint, manifesto)
                totais.linhas_novas += novas
                totais.linhas_ja_existentes += existentes
                log.info(
                    "%s: %d registros (%s), %d linhas novas",
                    descrever(cnpj, caminho_api, modalidade, janela_inicio, janela_fim),
                    manifesto["total_salvo"], "baixada" if baixada else "retomada", novas,
                )
            for ano, total in sondados.items():
                if total and por_ano[ano] != total:
                    # O dado é vivo: a diferença não para a execução (decisão 1).
                    log.warning(
                        "CNPJ %s, endpoint %s, modalidade %s, ano %d: sondagem informou %d, meses somam %d",
                        cnpj, caminho_api, modalidade, ano, total, por_ano[ano],
                    )


# --- execuções antigas, reconstrução e espelho (decisões 11 e 12) ------------


def completar_antigas(cfg: Config, execucoes: list[dict]) -> list[dict]:
    """Preenche cnpj e rodada_id das execuções anteriores à lista de CNPJs, pelos manifestos."""
    if all(e.get("cnpj") for e in execucoes):
        return execucoes
    manifestos, _ = landing.listar_janelas(cfg.landing)
    completas, sem_manifesto = completar_execucoes_antigas(
        execucoes, cnpj_das_execucoes(manifestos), cfg.matriz
    )
    for execucao_id in sem_manifesto:
        log.warning(
            "execução antiga %s sem manifesto na landing: atribuída à matriz %s",
            execucao_id, cfg.matriz,
        )
    return completas


def migrar_execucoes_antigas(con, cfg: Config) -> None:
    """Preenche no banco o cnpj e a rodada_id das execuções que não os têm."""
    antigas = [e for e in banco.ler_execucoes(con) if not e["cnpj"]]
    if not antigas:
        return
    for execucao in completar_antigas(cfg, antigas):
        banco.preencher_execucao_antiga(
            con, execucao["execucao_id"], execucao["cnpj"], execucao["rodada_id"]
        )
    log.info("migração: %d execução(ões) antiga(s) receberam cnpj e rodada_id", len(antigas))


def historico_do_espelho(execucoes: list[dict], cnpj: str) -> Historico:
    return [
        (
            e["execucao_id"],
            e["modo"],
            e["status"],
            date.fromisoformat(e["dados_ate"]) if e["dados_ate"] else None,
        )
        for e in execucoes
        if e["cnpj"] == cnpj
    ]


def espelhar(con, cfg: Config, execucao_id: str) -> None:
    landing.acrescentar_execucao(cfg.landing, banco.ler_execucoes(con, execucao_id)[0])


def sincronizar_espelho(con, cfg: Config) -> None:
    """Acrescenta ao espelho as execuções do banco que faltam nele ou estão desatualizadas."""
    no_espelho = {e["execucao_id"]: e for e in landing.ler_execucoes(cfg.landing)}
    for execucao in banco.ler_execucoes(con):
        if no_espelho.get(execucao["execucao_id"]) != execucao:
            landing.acrescentar_execucao(cfg.landing, execucao)


def reconstruir_raw(con, cfg: Config, totais: dict[str, Totais]) -> None:
    """Recarrega raw.contratacoes e raw.contratos a partir das janelas com manifesto."""
    por_caminho = {}
    for endpoint in cfg.endpoints:
        por_caminho[endpoint.publicacao] = endpoint
        por_caminho[endpoint.atualizacao] = endpoint

    manifestos, incompletas = landing.listar_janelas(cfg.landing)
    for pasta in incompletas:
        log.warning("janela sem manifesto ignorada: %s", pasta.relative_to(cfg.raiz).as_posix())
    outros_cnpj = [m for m in manifestos if m["cnpj"] not in totais]
    if outros_cnpj:
        log.warning("%d janela(s) de CNPJ fora do config.toml ignoradas", len(outros_cnpj))
    manifestos = [m for m in manifestos if m["cnpj"] in totais]
    desconhecidos = {m["endpoint"] for m in manifestos} - por_caminho.keys()
    if desconhecidos:
        raise FalhaReconstrucao(f"endpoints da landing fora do config.toml: {sorted(desconhecidos)}")

    banco.esvaziar_raw(con, [e.tabela for e in cfg.endpoints])
    for manifesto in ordem_reconstrucao(manifestos):
        novas, existentes = carregar_janela(con, cfg, por_caminho[manifesto["endpoint"]], manifesto)
        totais[manifesto["cnpj"]].linhas_novas += novas
        totais[manifesto["cnpj"]].linhas_ja_existentes += existentes
    log.info(
        "reconstrução: %d janelas, %s",
        len(manifestos),
        ", ".join(f"{e.tabela} {banco.contar_linhas(con, e.tabela)}" for e in cfg.endpoints),
    )


def reconstruir(con, cfg: Config, totais: dict[str, Totais]) -> None:
    """Recria raw.execucoes (do espelho) e a raw (da landing) numa única transação."""
    con.begin()
    try:
        banco.substituir_execucoes(con, completar_antigas(cfg, landing.ler_execucoes(cfg.landing)))
        reconstruir_raw(con, cfg, totais)
        con.commit()
    except BaseException:
        con.rollback()
        raise


# --- execução ---------------------------------------------------------------


def executar(
    con, cfg: Config, rodada: Rodada, modo: str, dados_ate: dict[str, date | None],
    trabalho: Callable[[dict[str, str], dict[str, Totais]], None], usa_api: bool = False,
) -> int:
    """Registra as execuções dos CNPJs (banco e espelho), roda o trabalho e fecha os registros.

    `dados_ate` traz um CNPJ nos modos com API e todos na reconstrução. O
    trabalho recebe o execucao_id e os totais de cada CNPJ.
    """
    ids = {cnpj: id_execucao(rodada.id, cnpj) for cnpj in dados_ate}
    inicio = datetime.now().astimezone()
    for cnpj, execucao_id in ids.items():
        banco.abrir_execucao(con, execucao_id, modo, inicio, dados_ate[cnpj], cnpj, rodada.id)
        espelhar(con, cfg, execucao_id)
        log.info("execução %s: CNPJ %s, modo %s", execucao_id, cnpj, modo)

    totais = {cnpj: Totais() for cnpj in ids}
    chamadas_antes = rodada.cliente.chamadas if usa_api else 0
    status, mensagem, codigo = "sucesso", None, 0
    try:
        trabalho(ids, totais)
    except (FalhaAPI, FalhaConferencia, FalhaReconstrucao) as e:
        status, mensagem, codigo = "falha", str(e), 1
    except KeyboardInterrupt:
        status, mensagem, codigo = "falha", "interrompida pelo usuário", 130
    except Exception as e:
        status, mensagem, codigo = "falha", f"{type(e).__name__}: {e}", 1
        log.exception("erro inesperado")
    finally:
        # Só os modos com API chamam a API, e eles têm um CNPJ por execução.
        chamadas = rodada.cliente.chamadas - chamadas_antes if usa_api else 0
        mb_landing = landing.tamanho_mb(cfg.landing)
        for cnpj, execucao_id in ids.items():
            banco.fechar_execucao(
                con, execucao_id, status=status, dados_ate=dados_ate[cnpj], chamadas_api=chamadas,
                linhas_novas=totais[cnpj].linhas_novas,
                linhas_ja_existentes=totais[cnpj].linhas_ja_existentes,
                mb_landing=mb_landing, mensagem_erro=mensagem,
            )
            espelhar(con, cfg, execucao_id)

    if status == "sucesso":
        novas = sum(t.linhas_novas for t in totais.values())
        existentes = sum(t.linhas_ja_existentes for t in totais.values())
        log.info(
            "sucesso (%s): %d chamadas, %d linhas novas, %d já existentes",
            ", ".join(ids), chamadas, novas, existentes,
        )
    else:
        log.error("falha (%s): %s", ", ".join(ids), mensagem)
        if modo != "reconstrucao":
            log.error("as janelas concluídas ficam na landing; rode de novo para retomar")
    return codigo


def ingerir_cnpj(con, cfg: Config, rodada: Rodada, cnpj: str, completa: bool, ate: date) -> int:
    """Carga completa ou incremental de um CNPJ, conforme o histórico dele (decisão 12)."""
    historico = banco.historico_execucoes(con, cnpj)
    modo = escolher_modo(historico, completa, reconstruir=False)
    retomaveis = ids_retomaveis(historico)
    if retomaveis:
        log.info("CNPJ %s: retomando execução interrompida, janelas com manifesto serão aproveitadas", cnpj)

    if modo == "completa":
        inicio = cfg.data_inicial
    else:
        periodo = janela_incremental(historico, ate)
        if periodo is None:
            anterior = ultimo_dados_ate(historico)
            log.info("CNPJ %s: nada a consultar, os dados já vão até %s", cnpj, anterior)
            return executar(con, cfg, rodada, "incremental", {cnpj: anterior}, lambda *_: None)
        inicio = periodo[0]

    log.info("CNPJ %s: %s de %s até %s", cnpj, modo, inicio, ate)
    return executar(
        con, cfg, rodada, modo, {cnpj: ate},
        lambda ids, totais: carregar_periodo(
            con, rodada.cliente, cfg, cnpj, modo, inicio, ate, ids[cnpj], retomaveis, totais[cnpj]
        ),
        usa_api=True,
    )


def ler_argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingestão do PNCP para a camada bruta.")
    parser.add_argument("--completa", action="store_true", help="força a carga completa")
    parser.add_argument(
        "--ate", type=date.fromisoformat, help="data final dos dados (AAAA-MM-DD); padrão: ontem"
    )
    parser.add_argument(
        "--reconstruir", action="store_true",
        help="recria o banco a partir da landing, sem chamar a API",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = ler_argumentos(argv)
    if args.reconstruir and (args.completa or args.ate):
        log.error("--reconstruir não pode ser combinado com --completa nem com --ate")
        return 2
    cfg = carregar_config()

    ontem = date.today() - timedelta(days=1)
    ate = args.ate or ontem
    if ate > ontem:
        log.error("--ate %s: a data final não pode passar de ontem (%s)", ate, ontem)
        return 2
    if ate < cfg.data_inicial:
        log.error("--ate %s é anterior à data inicial %s", ate, cfg.data_inicial)
        return 2

    con = banco.conectar(cfg.banco)
    try:
        banco.criar_tabelas(con, [e.tabela for e in cfg.endpoints])
        migrar_execucoes_antigas(con, cfg)
        sincronizar_espelho(con, cfg)
        rodada = Rodada(cfg)

        if args.reconstruir:
            execucoes = completar_antigas(cfg, landing.ler_execucoes(cfg.landing))
            dados_ate = {
                cnpj: ultimo_dados_ate(historico_do_espelho(execucoes, cnpj)) for cnpj in cfg.cnpjs
            }
            return executar(
                con, cfg, rodada, "reconstrucao", dados_ate,
                lambda _, totais: reconstruir(con, cfg, totais),
            )

        for posicao, cnpj in enumerate(cfg.cnpjs):
            codigo = ingerir_cnpj(con, cfg, rodada, cnpj, args.completa, ate)
            if codigo:
                seguintes = cfg.cnpjs[posicao + 1:]
                if seguintes:
                    log.error("rodada interrompida; não rodaram: %s", ", ".join(seguintes))
                return codigo
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
