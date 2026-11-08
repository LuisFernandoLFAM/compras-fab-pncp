"""Etapa 1: ingestão do PNCP para a camada bruta (spec: specs/ingestao.md).

Fase 1: só a carga completa, pelos endpoints de publicação.

    uv run python -m pipeline.ingestao                    # completa na 1ª vez
    uv run python -m pipeline.ingestao --completa         # força a carga completa
    uv run python -m pipeline.ingestao --ate 2026-10-31   # define a data final
"""

import argparse
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline import banco, landing
from pipeline.api import ClienteAPI, FalhaAPI, agora
from pipeline.config import Config, Endpoint, carregar_config
from pipeline.processamento import (
    ClasseResposta,
    RespostaInvalida,
    caminho_janela,
    conferir_janela,
    ids_retomaveis,
    janela_ja_concluida,
    janelas_mensais,
    ler_pagina,
    linhas_da_resposta,
    montar_manifesto,
    montar_parametros,
)

log = logging.getLogger("ingestao")


class FalhaConferencia(Exception):
    """A janela não conferiu nem depois de baixada de novo (decisão 7)."""


@dataclass
class Totais:
    linhas_novas: int = 0
    linhas_ja_existentes: int = 0


def descrever(endpoint: Endpoint, modalidade: int | None, inicio: date, fim: date) -> str:
    texto = f"endpoint {endpoint.publicacao}"
    if modalidade is not None:
        texto += f", modalidade {modalidade}"
    return texto + f", janela {inicio}_{fim}"


def _baixar_paginas(
    cliente: ClienteAPI, cfg: Config, endpoint: Endpoint, modalidade: int | None,
    inicio: date, fim: date, pasta: Path,
) -> tuple[int, list[dict], list[dict]]:
    """Percorre as páginas de uma janela. Devolve (total da API, registros, extrações)."""
    registros: list[dict] = []
    extracoes: list[dict] = []
    total_api = 0
    total_paginas = 1
    numero = 1
    while numero <= total_paginas:
        contexto = f"{descrever(endpoint, modalidade, inicio, fim)}, página {numero}"
        parametros = montar_parametros(
            inicio=inicio, fim=fim, pagina=numero, tamanho_pagina=cfg.tamanho_pagina,
            filtro_cnpj=endpoint.filtro_cnpj, cnpj=cfg.cnpj,
            filtro_modalidade=endpoint.filtro_modalidade, modalidade=modalidade,
        )
        resposta = cliente.buscar(endpoint.publicacao, parametros, contexto)
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
) -> tuple[dict, bool]:
    """Garante a janela completa na landing. Devolve (manifesto, se foi baixada agora)."""
    pasta = caminho_janela(cfg.landing, endpoint.publicacao, cfg.cnpj, modalidade, inicio, fim)
    manifesto = landing.ler_manifesto(pasta)
    if janela_ja_concluida(manifesto, retomaveis):
        return manifesto, False

    for tentativa in (1, 2):
        landing.limpar_janela(pasta)
        total_api, registros, extracoes = _baixar_paginas(
            cliente, cfg, endpoint, modalidade, inicio, fim, pasta
        )
        problemas = conferir_janela(total_api, registros, endpoint.chave)
        if not problemas:
            manifesto = montar_manifesto(
                endpoint=endpoint.publicacao, cnpj=cfg.cnpj, modalidade=modalidade,
                inicio=inicio, fim=fim, total_api=total_api, total_salvo=len(registros),
                extracoes=extracoes, execucao_id=execucao_id, concluido_em=agora(),
            )
            landing.gravar_manifesto(pasta, manifesto)
            return manifesto, True
        log.warning(
            "conferência falhou (tentativa %d) em %s: %s",
            tentativa, descrever(endpoint, modalidade, inicio, fim), "; ".join(problemas),
        )
    raise FalhaConferencia(
        f"conferência falhou duas vezes em {descrever(endpoint, modalidade, inicio, fim)}: "
        + "; ".join(problemas)
    )


def carregar_janela(
    con, cfg: Config, endpoint: Endpoint, manifesto: dict, execucao_id: str
) -> tuple[int, int]:
    """Lê as páginas da janela na landing e acrescenta as linhas na raw."""
    inicio = date.fromisoformat(manifesto["janela_inicio"])
    fim = date.fromisoformat(manifesto["janela_fim"])
    pasta = caminho_janela(
        cfg.landing, endpoint.publicacao, cfg.cnpj, manifesto["modalidade"], inicio, fim
    )
    linhas = []
    for extracao in manifesto["extracoes"]:
        arquivo = pasta / extracao["arquivo"]
        linhas += linhas_da_resposta(
            ler_pagina(arquivo.read_bytes()),
            endpoint=endpoint.publicacao,
            modalidade=manifesto["modalidade"],
            inicio=inicio,
            fim=fim,
            numero_pagina=extracao["pagina"],
            arquivo_origem=arquivo.relative_to(cfg.raiz).as_posix(),
            extraido_em=extracao["extraido_em"],
            execucao_id=execucao_id,
        )
    return banco.inserir_linhas(con, endpoint.tabela, linhas)


def carga_completa(
    con, cliente: ClienteAPI, cfg: Config, ate: date, execucao_id: str,
    retomaveis: set[str], totais: Totais,
) -> None:
    janelas = janelas_mensais(cfg.data_inicial, ate)
    for endpoint in cfg.endpoints:
        modalidades = cfg.modalidades if endpoint.filtro_modalidade else (None,)
        for modalidade in modalidades:
            for inicio, fim in janelas:
                manifesto, baixada = processar_janela(
                    cliente, cfg, endpoint, modalidade, inicio, fim, execucao_id, retomaveis
                )
                novas, existentes = carregar_janela(con, cfg, endpoint, manifesto, execucao_id)
                totais.linhas_novas += novas
                totais.linhas_ja_existentes += existentes
                log.info(
                    "%s: %d registros (%s), %d linhas novas",
                    descrever(endpoint, modalidade, inicio, fim),
                    manifesto["total_salvo"], "baixada" if baixada else "retomada", novas,
                )


def ler_argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingestão do PNCP para a camada bruta.")
    parser.add_argument("--completa", action="store_true", help="força a carga completa")
    parser.add_argument(
        "--ate", type=date.fromisoformat, help="data final dos dados (AAAA-MM-DD); padrão: ontem"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = ler_argumentos(argv)
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
        historico = banco.historico_execucoes(con)
        if not args.completa and any(status == "sucesso" for _, _, status in historico):
            log.error("incremental ainda não implementado (fase 2); use --completa")
            return 2

        retomaveis = ids_retomaveis(historico)
        if retomaveis:
            log.info("retomando a carga completa interrompida: janelas com manifesto serão aproveitadas")

        execucao_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        banco.abrir_execucao(con, execucao_id, "completa", datetime.now().astimezone(), ate)
        log.info("execução %s: carga completa de %s até %s", execucao_id, cfg.data_inicial, ate)

        cliente = ClienteAPI(cfg)
        totais = Totais()
        status, mensagem, codigo = "sucesso", None, 0
        try:
            carga_completa(con, cliente, cfg, ate, execucao_id, retomaveis, totais)
        except (FalhaAPI, FalhaConferencia) as e:
            status, mensagem, codigo = "falha", str(e), 1
        except KeyboardInterrupt:
            status, mensagem, codigo = "falha", "interrompida pelo usuário", 130
        except Exception as e:
            status, mensagem, codigo = "falha", f"{type(e).__name__}: {e}", 1
            log.exception("erro inesperado")
        finally:
            banco.fechar_execucao(
                con, execucao_id, status=status, chamadas_api=cliente.chamadas,
                linhas_novas=totais.linhas_novas,
                linhas_ja_existentes=totais.linhas_ja_existentes,
                mb_landing=landing.tamanho_mb(cfg.landing), mensagem_erro=mensagem,
            )

        if status == "sucesso":
            log.info(
                "sucesso: %d chamadas, %d linhas novas, %d já existentes",
                cliente.chamadas, totais.linhas_novas, totais.linhas_ja_existentes,
            )
        else:
            log.error("falha: %s", mensagem)
            log.error("as janelas concluídas ficam na landing; rode de novo com --completa para retomar")
        return codigo
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
