"""Etapa 4: consultas do painel (spec: specs/painel.md).

Só faz SELECT nos marts: cada função devolve um DataFrame pronto para desenhar.
Nenhuma consulta lê ni_fornecedor nem fornecedor_id (decisão 6 da spec do painel).
A única conta fora dos marts é a idade da extração, que depende do dia (decisão 2).
"""

import os
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import carregar_config

LIMITES_IDADE_DIAS = (7, 30)  # verde até 7 dias, amarelo até 30, vermelho acima
SEGMENTOS = {"todos": ["dados", "ti", "outros"], "ti": ["dados", "ti"], "dados": ["dados"]}
UNIDADES_NO_GRAFICO = 15
FORNECEDORES_NO_PARETO = 30
MINIMO_ELEGIVEIS = 10  # corte do gráfico de compras provavelmente sem resultado


def banco_padrao() -> Path:
    """Banco do config.toml; a variável PAINEL_BANCO aponta para outro (testes)."""
    return Path(os.environ.get("PAINEL_BANCO") or carregar_config().banco)


def ler(sql: str, parametros: list | None = None, banco: Path | None = None) -> pd.DataFrame:
    """Abre o banco só para leitura, executa a consulta e fecha a conexão."""
    con = duckdb.connect(str(banco or banco_padrao()), read_only=True)
    try:
        return con.execute(sql, parametros or []).df()
    finally:
        con.close()


# --- topo e cartões --------------------------------------------------------------------


def kpis(banco: Path | None = None) -> dict:
    [linha] = ler("SELECT * FROM marts.kpis", banco=banco).to_dict("records")
    return linha


def sinal_da_extracao(extraido_em: datetime, hoje: date | None = None) -> tuple[int, str]:
    """(dias desde a extração, cor do sinal): a exceção da decisão 2, porque depende do dia."""
    dias = ((hoje or date.today()) - extraido_em.date()).days
    verde, amarelo = LIMITES_IDADE_DIAS
    if dias <= verde:
        return dias, "verde"
    if dias <= amarelo:
        return dias, "amarelo"
    return dias, "vermelho"


def anos(banco: Path | None = None) -> list[int]:
    return ler("SELECT DISTINCT ano FROM marts.compras_mensal ORDER BY ano DESC", banco=banco)["ano"].tolist()


# --- Quando agir --------------------------------------------------------------------------


def propostas_abertas(segmento: str = "todos", banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT unidade_nome, uf, modalidade_nome, objeto_compra, valor_estimado,
               data_encerramento_proposta, dias_para_encerrar, segmento, link_sistema_origem
        FROM marts.propostas_abertas
        WHERE list_contains(?, segmento)
        ORDER BY data_encerramento_proposta, numero_controle_pncp
        """,
        [SEGMENTOS[segmento]], banco,
    )


def contratos_a_vencer(
    segmento: str = "todos", faixas: list[str] | None = None, banco: Path | None = None
) -> pd.DataFrame:
    faixas = faixas or ["ate_3_meses", "3_a_6_meses", "6_a_12_meses"]
    return ler(
        """
        SELECT unidade_nome, uf, objeto_contrato, valor_global, data_vigencia_fim, dias_para_vencer,
               faixa_vencimento, fornecedor_nome, tipo_pessoa, cliente_desde, tempo_de_casa_anos,
               contratos_do_fornecedor_na_unidade, segmento
        FROM marts.contratos_a_vencer
        WHERE list_contains(?, segmento) AND list_contains(?, faixa_vencimento)
        ORDER BY data_vigencia_fim, numero_controle_pncp
        """,
        [SEGMENTOS[segmento], faixas], banco,
    )


# --- Onde está o dinheiro -------------------------------------------------------------------


def compras_mensal(banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT ano, mes, mes_completo, compras, valor_estimado, valor_homologado, contratos,
               valor_contratado, participacao_compras_no_ano, participacao_valor_no_ano
        FROM marts.compras_mensal ORDER BY ano, mes
        """,
        banco=banco,
    )


def compras_por_unidade(ano: int, banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT unidade_nome, uf, municipio, compras, valor_estimado, valor_homologado,
               revogadas, anuladas, provaveis_sem_resultado
        FROM marts.compras_por_unidade
        WHERE ano = ?
        ORDER BY valor_estimado DESC, unidade_codigo
        LIMIT ?
        """,
        [ano, UNIDADES_NO_GRAFICO], banco,
    )


def compras_por_modalidade(ano: int, banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT modalidade_nome, compras, valor_estimado, ticket_medio, faixa_estimado_zero,
               faixa_ate_50_mil, faixa_50_mil_a_500_mil, faixa_500_mil_a_5_milhoes, faixa_acima_5_milhoes,
               prazo_medio_propostas_dias, desconto_medio, desconto_mediano, compras_com_desconto
        FROM marts.compras_por_modalidade
        WHERE ano = ?
        ORDER BY compras DESC, modalidade_id
        """,
        [ano], banco,
    )


def contratos_por_categoria(ano: int, banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT categoria_processo_nome, contratos, valor_contratado, ticket_medio
        FROM marts.contratos_por_categoria
        WHERE ano = ?
        ORDER BY valor_contratado DESC, categoria_processo_id
        """,
        [ano], banco,
    )


# --- Contra quem ------------------------------------------------------------------------------


def fornecedores(banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT posicao, fornecedor_nome, tipo_pessoa, contratos, valor_contratado, participacao,
               participacao_acumulada, ate_80_por_cento
        FROM marts.fornecedores
        WHERE posicao <= ?
        ORDER BY posicao
        """,
        [FORNECEDORES_NO_PARETO], banco,
    )


def fornecedores_resumo(banco: Path | None = None) -> dict:
    [linha] = ler("SELECT * FROM marts.fornecedores_resumo", banco=banco).to_dict("records")
    return linha


# --- Onde há espaço ---------------------------------------------------------------------------


def compras_sem_resultado(ano: int, banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT unidade_nome, modalidade_nome, compras_elegiveis, provaveis_sem_resultado,
               taxa_provaveis_sem_resultado, valor_estimado_provaveis_sem_resultado
        FROM marts.compras_sem_resultado
        WHERE ano = ? AND compras_elegiveis >= ?
        ORDER BY taxa_provaveis_sem_resultado DESC, compras_elegiveis DESC, unidade_codigo, modalidade_id
        LIMIT ?
        """,
        [ano, MINIMO_ELEGIVEIS, UNIDADES_NO_GRAFICO], banco,
    )


def dispensas_com_disputa(ano: int, banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT unidade_nome, uf, dispensas, dispensas_com_disputa, participacao_com_disputa,
               valor_estimado, valor_homologado, desconto_mediano
        FROM marts.dispensas_com_disputa
        WHERE ano = ? AND dispensas_com_disputa > 0
        ORDER BY dispensas_com_disputa DESC, unidade_codigo
        LIMIT ?
        """,
        [ano, UNIDADES_NO_GRAFICO], banco,
    )


# --- TI e dados -------------------------------------------------------------------------------


def ti_e_dados(ano: int, segmento: str = "ti", banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT unidade_nome, uf, compras, valor_estimado, valor_homologado, propostas_abertas,
               valor_estimado_propostas_abertas, contratos, valor_contratado
        FROM marts.ti_e_dados
        WHERE ano = ? AND segmento = ?
        ORDER BY valor_estimado DESC, valor_contratado DESC, unidade_codigo
        """,
        [ano, segmento], banco,
    )


def ti_e_dados_fornecedores(banco: Path | None = None) -> pd.DataFrame:
    return ler(
        """
        SELECT segmento, posicao, fornecedor_nome, tipo_pessoa, contratos, valor_contratado,
               participacao_no_segmento
        FROM marts.ti_e_dados_fornecedores
        ORDER BY segmento DESC, posicao
        """,
        banco=banco,
    )
