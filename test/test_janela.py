"""Download, conferência e manifesto de uma janela, com respostas falsas e landing temporária."""

from datetime import date

import pytest
from conftest import VAZIO, ClienteFalso, ok

from pipeline import banco, landing
from pipeline.api import FalhaAPI, Resposta
from pipeline.ingestao import FalhaConferencia, carregar_janela, processar_janela
from pipeline.processamento import ClasseResposta, caminho_janela

INICIO, FIM = date(2026, 3, 1), date(2026, 3, 31)


def contratacoes(cfg):
    return next(e for e in cfg.endpoints if e.tabela == "contratacoes")


def contratos(cfg):
    return next(e for e in cfg.endpoints if e.tabela == "contratos")


def pasta(cfg, endpoint, modalidade):
    return caminho_janela(cfg.landing, endpoint.publicacao, cfg.cnpj, modalidade, INICIO, FIM)


def test_janela_vazia_recebe_manifesto_e_nao_e_consultada_na_retomada(cfg):
    endpoint = contratacoes(cfg)
    cliente = ClienteFalso([VAZIO])

    manifesto, baixada = processar_janela(cliente, cfg, endpoint, 13, INICIO, FIM, "e1", set())

    assert baixada
    assert cliente.chamadas == 1
    gravado = landing.ler_manifesto(pasta(cfg, endpoint, 13))
    assert gravado == manifesto
    assert (gravado["total_api"], gravado["total_salvo"], gravado["paginas"]) == (0, 0, 0)

    # Retomada: a janela vazia já concluída não gera nova chamada.
    cliente_retomada = ClienteFalso([])
    _, baixada = processar_janela(cliente_retomada, cfg, endpoint, 13, INICIO, FIM, "e2", {"e1"})
    assert not baixada
    assert cliente_retomada.chamadas == 0


def test_janela_com_duas_paginas(cfg):
    endpoint = contratacoes(cfg)
    cliente = ClienteFalso([ok("contratacoes_pagina_1.json"), ok("contratacoes_pagina_2.json")])

    manifesto, _ = processar_janela(cliente, cfg, endpoint, 6, INICIO, FIM, "e1", set())

    assert [p["pagina"] for p in cliente.parametros] == [1, 2]
    assert all(p["codigoModalidadeContratacao"] == 6 for p in cliente.parametros)
    assert (manifesto["total_api"], manifesto["total_salvo"], manifesto["paginas"]) == (3, 3, 2)
    p = pasta(cfg, endpoint, 6)
    assert sorted(f.name for f in p.iterdir()) == [
        "_manifesto.json", "pagina_001.json", "pagina_002.json"
    ]
    # A página é salva exatamente como recebida.
    assert (p / "pagina_001.json").read_bytes() == ok("contratacoes_pagina_1.json").corpo


def test_janela_ja_concluida_por_execucao_que_terminou_com_sucesso_e_baixada_de_novo(cfg):
    endpoint = contratos(cfg)
    processar_janela(ClienteFalso([ok("contratos_pagina_unica.json")]), cfg, endpoint, None,
                     INICIO, FIM, "e1", set())

    cliente = ClienteFalso([ok("contratos_pagina_unica.json")])
    manifesto, baixada = processar_janela(cliente, cfg, endpoint, None, INICIO, FIM, "e2", set())

    assert baixada and cliente.chamadas == 1
    assert manifesto["execucao_id"] == "e2"


def test_janela_incompleta_e_baixada_de_novo_na_retomada(cfg):
    endpoint = contratacoes(cfg)
    p = pasta(cfg, endpoint, 6)
    landing.salvar_pagina(p, 1, ok("contratacoes_pagina_1.json").corpo)  # sem manifesto

    cliente = ClienteFalso([ok("contratacoes_pagina_1.json"), ok("contratacoes_pagina_2.json")])
    _, baixada = processar_janela(cliente, cfg, endpoint, 6, INICIO, FIM, "e2", {"e1"})

    assert baixada and cliente.chamadas == 2
    assert landing.ler_manifesto(p) is not None


def test_conferencia_tenta_de_novo_uma_vez_e_depois_para(cfg):
    endpoint = contratacoes(cfg)
    # Só a página 1 chega; a página 2 vem vazia: 2 salvos contra 3 informados.
    cliente = ClienteFalso([ok("contratacoes_pagina_1.json"), VAZIO] * 2)

    with pytest.raises(FalhaConferencia, match="contagem"):
        processar_janela(cliente, cfg, endpoint, 6, INICIO, FIM, "e1", set())

    assert cliente.chamadas == 4
    assert landing.ler_manifesto(pasta(cfg, endpoint, 6)) is None


def test_conferencia_se_recupera_na_segunda_tentativa(cfg):
    endpoint = contratacoes(cfg)
    cliente = ClienteFalso([
        ok("contratacoes_pagina_1.json"), VAZIO,
        ok("contratacoes_pagina_1.json"), ok("contratacoes_pagina_2.json"),
    ])
    manifesto, _ = processar_janela(cliente, cfg, endpoint, 6, INICIO, FIM, "e1", set())
    assert manifesto["total_salvo"] == 3


def test_duplicata_impede_o_manifesto(cfg):
    endpoint = contratacoes(cfg)
    cliente = ClienteFalso([ok("contratacoes_duplicata.json")] * 2)
    with pytest.raises(FalhaConferencia, match="duplicatas"):
        processar_janela(cliente, cfg, endpoint, 8, INICIO, FIM, "e1", set())


def test_corpo_invalido_vira_falha_e_nao_zero(cfg):
    endpoint = contratos(cfg)
    cliente = ClienteFalso([Resposta(ClasseResposta.SUCESSO, b"<html>manutencao</html>", "t")])
    with pytest.raises(FalhaAPI, match="resposta inválida"):
        processar_janela(cliente, cfg, endpoint, None, INICIO, FIM, "e1", set())
    assert landing.ler_manifesto(pasta(cfg, endpoint, None)) is None


def test_carga_na_raw_e_idempotente(cfg):
    # Banco em memória: os testes nunca abrem o banco do projeto.
    con = banco.conectar(":memory:")
    banco.criar_tabelas(con, ["contratacoes", "contratos"])
    endpoint = contratacoes(cfg)
    cliente = ClienteFalso([ok("contratacoes_pagina_1.json"), ok("contratacoes_pagina_2.json")])
    manifesto, _ = processar_janela(cliente, cfg, endpoint, 6, INICIO, FIM, "e1", set())

    assert carregar_janela(con, cfg, endpoint, manifesto, "e1") == (3, 0)
    assert carregar_janela(con, cfg, endpoint, manifesto, "e2") == (0, 3)

    origem, extraido_em = con.execute(
        "SELECT _arquivo_origem, _extraido_em FROM raw.contratacoes WHERE _pagina = '2'"
    ).fetchone()
    assert origem.endswith("modalidade=06/janela=2026-03-01_2026-03-31/pagina_002.json")
    assert not origem.startswith("/") and ":" not in origem
    assert extraido_em == "2026-11-07T10:00:00-03:00"


def test_mesma_versao_com_chaves_em_outra_ordem_nao_vira_linha_nova():
    from pipeline.processamento import hash_registro, texto_registro

    con = banco.conectar(":memory:")
    banco.criar_tabelas(con, ["contratos"])

    def linha(registro):
        return {
            "registro": texto_registro(registro), "_hash": hash_registro(registro),
            "_endpoint": "/v1/contratos", "_modalidade": None, "_janela_inicio": "2026-03-01",
            "_janela_fim": "2026-03-31", "_pagina": "1", "_arquivo_origem": "a.json",
            "_extraido_em": "t", "_execucao_id": "e",
        }

    assert banco.inserir_linhas(con, "contratos", [linha({"a": 1, "b": 2})]) == (1, 0)
    assert banco.inserir_linhas(con, "contratos", [linha({"b": 2, "a": 1})]) == (0, 1)
    assert banco.inserir_linhas(con, "contratos", [linha({"a": 1, "b": 3})]) == (1, 0)
