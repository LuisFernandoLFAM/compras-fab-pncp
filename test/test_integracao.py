"""Teste de integração com a API real do PNCP (decisão 10).

Fora da execução padrão. Para rodar: uv run pytest -m integracao

Confere que os registros publicados nos últimos 7 dias aparecem também no
endpoint de atualização, ou seja, que registros novos entram pelo incremental.
Não grava na landing nem abre o banco.
"""

from datetime import date, timedelta

import pytest

from pipeline.api import ClienteAPI
from pipeline.config import carregar_config
from pipeline.processamento import ClasseResposta, ler_pagina, montar_parametros

pytestmark = pytest.mark.integracao

MODALIDADE_PREGAO = 6


def chaves(cliente, cfg, endpoint, caminho_api, modalidade, inicio, fim) -> set[str]:
    encontradas = set()
    numero, total_paginas = 1, 1
    while numero <= total_paginas:
        parametros = montar_parametros(
            inicio=inicio, fim=fim, pagina=numero, tamanho_pagina=cfg.tamanho_pagina,
            filtro_cnpj=endpoint.filtro_cnpj, cnpj=cfg.cnpj,
            filtro_modalidade=endpoint.filtro_modalidade, modalidade=modalidade,
        )
        resposta = cliente.buscar(caminho_api, parametros, f"teste de integração, {caminho_api}")
        if resposta.classe is ClasseResposta.VAZIO:
            break
        pagina = ler_pagina(resposta.corpo)
        total_paginas = pagina["totalPaginas"]
        encontradas |= {r[endpoint.chave] for r in pagina["data"]}
        numero += 1
    return encontradas


@pytest.mark.parametrize("tabela", ["contratacoes", "contratos"])
def test_publicados_recentemente_aparecem_no_endpoint_de_atualizacao(tabela):
    cfg = carregar_config()
    cliente = ClienteAPI(cfg)
    endpoint = next(e for e in cfg.endpoints if e.tabela == tabela)
    modalidade = MODALIDADE_PREGAO if endpoint.filtro_modalidade else None
    fim = date.today() - timedelta(days=1)
    inicio = fim - timedelta(days=6)

    publicados = chaves(cliente, cfg, endpoint, endpoint.publicacao, modalidade, inicio, fim)
    if not publicados:
        pytest.skip(f"nenhuma publicação de {tabela} entre {inicio} e {fim}")
    atualizados = chaves(cliente, cfg, endpoint, endpoint.atualizacao, modalidade, inicio, fim)

    faltando = publicados - atualizados
    assert not faltando, f"{len(faltando)} de {len(publicados)} publicados fora da atualização: {sorted(faltando)[:5]}"
