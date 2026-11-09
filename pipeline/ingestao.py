"""Etapa 1: ingestão do PNCP para a camada bruta (spec: specs/ingestao.md).

    uv run python -m pipeline.ingestao                    # completa na 1ª vez, incremental depois
    uv run python -m pipeline.ingestao --completa         # força a carga completa
    uv run python -m pipeline.ingestao --ate 2026-10-31   # define a data final
    uv run python -m pipeline.ingestao --reconstruir      # recria o banco a partir da landing, sem API
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
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
    conferir_janela,
    escolher_modo,
    ids_retomaveis,
    janela_incremental,
    janela_ja_concluida,
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


def descrever(caminho_api: str, modalidade: int | None, inicio: date, fim: date) -> str:
    texto = f"endpoint {caminho_api}"
    if modalidade is not None:
        texto += f", modalidade {modalidade}"
    return texto + f", janela {inicio}_{fim}"


def caminho_do_modo(endpoint: Endpoint, modo: str) -> str:
    return endpoint.publicacao if modo == "completa" else endpoint.atualizacao


# --- download de janelas ----------------------------------------------------


def _baixar_paginas(
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, caminho_api: str,
    modalidade: int | None, inicio: date, fim: date, pasta: Path,
) -> tuple[int, list[dict], list[dict]]:
    """Percorre as páginas de uma janela. Devolve (total da API, registros, extrações)."""
    registros: list[dict] = []
    extracoes: list[dict] = []
    total_api = 0
    total_paginas = 1
    numero = 1
    while numero <= total_paginas:
        contexto = f"{descrever(caminho_api, modalidade, inicio, fim)}, página {numero}"
        parametros = montar_parametros(
            inicio=inicio, fim=fim, pagina=numero, tamanho_pagina=cfg.tamanho_pagina,
            filtro_cnpj=endpoint.filtro_cnpj, cnpj=cfg.cnpj,
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
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, modalidade: int | None,
    inicio: date, fim: date, execucao_id: str, retomaveis: set[str],
    caminho_api: str | None = None,
) -> tuple[dict, bool]:
    """Garante a janela completa na landing. Devolve (manifesto, se foi baixada agora).

    `caminho_api` é o endpoint consultado; por padrão, o de publicação.
    """
    caminho_api = caminho_api or endpoint.publicacao
    pasta = caminho_janela(cfg.landing, caminho_api, cfg.cnpj, modalidade, inicio, fim)
    manifesto = landing.ler_manifesto(pasta)
    if janela_ja_concluida(manifesto, retomaveis):
        return manifesto, False

    descricao = descrever(caminho_api, modalidade, inicio, fim)
    for tentativa in (1, 2):
        landing.limpar_janela(pasta)
        total_api, registros, extracoes = _baixar_paginas(
            cliente, cfg, endpoint, caminho_api, modalidade, inicio, fim, pasta
        )
        problemas = conferir_janela(total_api, registros, endpoint.chave)
        if not problemas:
            manifesto = montar_manifesto(
                endpoint=caminho_api, cnpj=cfg.cnpj, modalidade=modalidade,
                inicio=inicio, fim=fim, total_api=total_api, total_salvo=len(registros),
                extracoes=extracoes, execucao_id=execucao_id, concluido_em=agora(),
            )
            landing.gravar_manifesto(pasta, manifesto)
            return manifesto, True
        log.warning(
            "conferência falhou (tentativa %d) em %s: %s", tentativa, descricao, "; ".join(problemas)
        )
    raise FalhaConferencia(f"conferência falhou duas vezes em {descricao}: " + "; ".join(problemas))


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
    con, cliente: ClienteAPI, cfg: Config, modo: str, inicio: date, ate: date,
    execucao_id: str, retomaveis: set[str], totais: Totais,
) -> None:
    """Carga completa ou incremental: percorre endpoints, modalidades e janelas mensais."""
    janelas = janelas_mensais(inicio, ate)
    for endpoint in cfg.endpoints:
        caminho_api = caminho_do_modo(endpoint, modo)
        modalidades = cfg.modalidades if endpoint.filtro_modalidade else (None,)
        for modalidade in modalidades:
            for janela_inicio, janela_fim in janelas:
                manifesto, baixada = processar_janela(
                    cliente, cfg, endpoint, modalidade, janela_inicio, janela_fim,
                    execucao_id, retomaveis, caminho_api,
                )
                novas, existentes = carregar_janela(con, cfg, endpoint, manifesto)
                totais.linhas_novas += novas
                totais.linhas_ja_existentes += existentes
                log.info(
                    "%s: %d registros (%s), %d linhas novas",
                    descrever(caminho_api, modalidade, janela_inicio, janela_fim),
                    manifesto["total_salvo"], "baixada" if baixada else "retomada", novas,
                )


# --- reconstrução e espelho das execuções (decisão 11) ----------------------


def historico_do_espelho(execucoes: list[dict]) -> Historico:
    return [
        (
            e["execucao_id"],
            e["modo"],
            e["status"],
            date.fromisoformat(e["dados_ate"]) if e["dados_ate"] else None,
        )
        for e in execucoes
    ]


def espelhar(con, cfg: Config, execucao_id: str) -> None:
    landing.acrescentar_execucao(cfg.landing, banco.ler_execucoes(con, execucao_id)[0])


def sincronizar_espelho(con, cfg: Config) -> None:
    """Acrescenta ao espelho as execuções do banco que faltam nele ou estão desatualizadas."""
    no_espelho = {e["execucao_id"]: e for e in landing.ler_execucoes(cfg.landing)}
    for execucao in banco.ler_execucoes(con):
        if no_espelho.get(execucao["execucao_id"]) != execucao:
            landing.acrescentar_execucao(cfg.landing, execucao)


def reconstruir_raw(con, cfg: Config, totais: Totais) -> None:
    """Recarrega raw.contratacoes e raw.contratos a partir das janelas com manifesto."""
    por_caminho = {}
    for endpoint in cfg.endpoints:
        por_caminho[endpoint.publicacao] = endpoint
        por_caminho[endpoint.atualizacao] = endpoint

    manifestos, incompletas = landing.listar_janelas(cfg.landing)
    for pasta in incompletas:
        log.warning("janela sem manifesto ignorada: %s", pasta.relative_to(cfg.raiz).as_posix())
    outros_cnpj = [m for m in manifestos if m["cnpj"] != cfg.cnpj]
    if outros_cnpj:
        log.warning("%d janela(s) de outro CNPJ ignoradas", len(outros_cnpj))
    manifestos = [m for m in manifestos if m["cnpj"] == cfg.cnpj]
    desconhecidos = {m["endpoint"] for m in manifestos} - por_caminho.keys()
    if desconhecidos:
        raise FalhaReconstrucao(f"endpoints da landing fora do config.toml: {sorted(desconhecidos)}")

    banco.esvaziar_raw(con, [e.tabela for e in cfg.endpoints])
    for manifesto in ordem_reconstrucao(manifestos):
        novas, existentes = carregar_janela(con, cfg, por_caminho[manifesto["endpoint"]], manifesto)
        totais.linhas_novas += novas
        totais.linhas_ja_existentes += existentes
    log.info(
        "reconstrução: %d janelas, %s",
        len(manifestos),
        ", ".join(f"{e.tabela} {banco.contar_linhas(con, e.tabela)}" for e in cfg.endpoints),
    )


def reconstruir(con, cfg: Config, totais: Totais) -> None:
    """Recria raw.execucoes (do espelho) e a raw (da landing) numa única transação."""
    con.begin()
    try:
        banco.substituir_execucoes(con, landing.ler_execucoes(cfg.landing))
        reconstruir_raw(con, cfg, totais)
        con.commit()
    except BaseException:
        con.rollback()
        raise


# --- execução ---------------------------------------------------------------


def executar(
    con, cfg: Config, modo: str, dados_ate: date | None,
    trabalho: Callable[[str, Totais], None], cliente: ClienteAPI | None = None,
) -> int:
    """Registra a execução (banco e espelho), roda o trabalho e fecha o registro."""
    execucao_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    banco.abrir_execucao(con, execucao_id, modo, datetime.now().astimezone(), dados_ate)
    espelhar(con, cfg, execucao_id)
    log.info("execução %s: modo %s", execucao_id, modo)

    totais = Totais()
    status, mensagem, codigo = "sucesso", None, 0
    try:
        trabalho(execucao_id, totais)
    except (FalhaAPI, FalhaConferencia, FalhaReconstrucao) as e:
        status, mensagem, codigo = "falha", str(e), 1
    except KeyboardInterrupt:
        status, mensagem, codigo = "falha", "interrompida pelo usuário", 130
    except Exception as e:
        status, mensagem, codigo = "falha", f"{type(e).__name__}: {e}", 1
        log.exception("erro inesperado")
    finally:
        chamadas = cliente.chamadas if cliente else 0
        banco.fechar_execucao(
            con, execucao_id, status=status, dados_ate=dados_ate, chamadas_api=chamadas,
            linhas_novas=totais.linhas_novas, linhas_ja_existentes=totais.linhas_ja_existentes,
            mb_landing=landing.tamanho_mb(cfg.landing), mensagem_erro=mensagem,
        )
        espelhar(con, cfg, execucao_id)

    if status == "sucesso":
        log.info(
            "sucesso: %d chamadas, %d linhas novas, %d já existentes",
            chamadas, totais.linhas_novas, totais.linhas_ja_existentes,
        )
    else:
        log.error("falha: %s", mensagem)
        if modo != "reconstrucao":
            log.error("as janelas concluídas ficam na landing; rode de novo para retomar")
    return codigo


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
        sincronizar_espelho(con, cfg)

        if args.reconstruir:
            historico = historico_do_espelho(landing.ler_execucoes(cfg.landing))
            return executar(
                con, cfg, "reconstrucao", ultimo_dados_ate(historico),
                lambda _, totais: reconstruir(con, cfg, totais),
            )

        historico = banco.historico_execucoes(con)
        modo = escolher_modo(historico, args.completa, reconstruir=False)
        retomaveis = ids_retomaveis(historico)
        if retomaveis:
            log.info("retomando execução interrompida: janelas com manifesto serão aproveitadas")

        if modo == "completa":
            inicio = cfg.data_inicial
        else:
            periodo = janela_incremental(historico, ate)
            if periodo is None:
                anterior = ultimo_dados_ate(historico)
                log.info("nada a consultar: os dados já vão até %s", anterior)
                return executar(con, cfg, "incremental", anterior, lambda *_: None)
            inicio = periodo[0]

        log.info("%s de %s até %s", modo, inicio, ate)
        cliente = ClienteAPI(cfg)
        return executar(
            con, cfg, modo, ate,
            lambda execucao_id, totais: carregar_periodo(
                con, cliente, cfg, modo, inicio, ate, execucao_id, retomaveis, totais
            ),
            cliente,
        )
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
