"""Etapa 4: relatório HTML autocontido com os gráficos do painel (spec: specs/painel.md, decisão 5).

    uv run python relatorio.py   # gera docs/relatorio.html

Foto dos indicadores no ano da data de referência, sem filtro de segmento. O JavaScript
do Plotly vai embutido uma vez; o arquivo abre sem internet.
"""

import html
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

import graficos as g
import painel
from pipeline.config import RAIZ_PROJETO

DESTINO = RAIZ_PROJETO / "docs" / "relatorio.html"

ESTILO = """
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0 auto; max-width: 1200px;
       padding: 24px; color: #222; }
header { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
header h1 { margin: 0 0 4px; }
.saude { text-align: right; line-height: 1.6; }
.cartoes { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 24px 0; }
.cartao { border: 1px solid #ddd; border-radius: 8px; padding: 12px; }
.cartao .titulo { font-size: 0.85em; color: #555; }
.cartao .valor { font-size: 1.8em; font-weight: 600; margin: 4px 0; }
.cartao .rodape { font-size: 0.75em; color: #666; }
h2 { border-bottom: 2px solid #1f4e79; padding-bottom: 4px; margin-top: 40px; }
table { border-collapse: collapse; width: 100%; font-size: 0.8em; margin: 8px 0 16px; }
th, td { border-bottom: 1px solid #eee; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #f4f6f9; }
.notas { background: #f8f8f8; border-left: 3px solid #9dbbd8; padding: 8px 16px; font-size: 0.85em; }
.duas { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
footer { margin-top: 40px; font-size: 0.8em; color: #666; }
"""


class Pagina:
    """Junta os pedaços do HTML; o primeiro gráfico leva o JavaScript do Plotly."""

    def __init__(self):
        self.partes: list[str] = []
        self.plotly_incluido = False

    def add(self, trecho: str) -> None:
        self.partes.append(trecho)

    def grafico(self, fig: go.Figure) -> str:
        trecho = fig.to_html(full_html=False, include_plotlyjs=not self.plotly_incluido)
        self.plotly_incluido = True
        return trecho

    def tabela(self, df: pd.DataFrame) -> str:
        return df.to_html(index=False, escape=True, border=0)

    def notas(self, chave: str) -> str:
        itens = "".join(f"<li>{html.escape(n)}</li>" for n in g.NOTAS[chave])
        return f"<div class='notas'><strong>Notas de leitura</strong><ul>{itens}</ul></div>"


def topo(k: dict, hoje: date | None) -> str:
    """Título e saúde do dado."""
    dias, cor = painel.sinal_da_extracao(pd.Timestamp(k["extraido_em"]).to_pydatetime(), hoje)
    return (
        "<header><div><h1>Compras da FAB no PNCP</h1>"
        "<div>Para o time de licitações de uma empresa que quer vender para a Força Aérea Brasileira.</div>"
        f"<div><strong>Foto dos indicadores com dados até {g.data(k['data_referencia'])}.</strong></div></div>"
        "<div class='saude'>"
        f"<span style='color:{g.CORES_SINAL[cor]};font-size:1.4em'>●</span> "
        f"<strong>Dados extraídos em</strong> {g.data(k['extraido_em'], com_hora=True)} "
        f"(há {dias} dias na geração do relatório)<br>"
        f"<strong>Publicação mais recente:</strong> {g.data(k['publicacao_mais_recente'], com_hora=True)}<br>"
        f"<strong>Dados até</strong> {g.data(k['data_referencia'])}</div></header>"
    )


def cartoes(k: dict) -> str:
    return "<div class='cartoes'>" + "".join(
        f"<div class='cartao'><div class='titulo'>{html.escape(c['titulo'])}</div>"
        f"<div class='valor'>{html.escape(c['valor'])}</div><div class='rodape'>{html.escape(c['rodape'])}</div></div>"
        for c in g.cartoes(k)
    ) + "</div>"


def quando_agir(p: Pagina, banco: Path | None) -> None:
    p.add("<h2>Quando agir</h2><h3>Propostas abertas</h3>")
    p.add(p.tabela(g.tabela_propostas(painel.propostas_abertas(banco=banco))))
    p.add("<h3>Contratos a vencer</h3>")
    p.add(p.tabela(g.tabela_contratos(painel.contratos_a_vencer(banco=banco))))
    p.add(p.notas("quando_agir"))


def onde_esta_o_dinheiro(p: Pagina, ano: int, banco: Path | None) -> None:
    mensal = painel.compras_mensal(banco)
    p.add("<h2>Onde está o dinheiro</h2>")
    p.add(p.grafico(g.fig_compras_mensal(mensal)))
    p.add(p.grafico(g.fig_sazonalidade(mensal)))
    p.add("<div class='duas'><div>" + p.grafico(g.fig_unidades(painel.compras_por_unidade(ano, banco), ano))
          + "</div><div>" + p.grafico(g.fig_categorias(painel.contratos_por_categoria(ano, banco), ano))
          + "</div></div>")
    p.add(f"<h3>Compras por modalidade em {ano}</h3>")
    p.add(p.tabela(g.tabela_modalidades(painel.compras_por_modalidade(ano, banco))))
    p.add(p.notas("dinheiro"))


def contra_quem(p: Pagina, banco: Path | None) -> None:
    resumo = painel.fornecedores_resumo(banco)
    p.add("<h2>Contra quem</h2>")
    p.add(f"<p><strong>{g.numero(resumo['fornecedores_80_por_cento'])} de {g.numero(resumo['fornecedores'])} "
          "fornecedores</strong> fazem 80% do valor contratado.</p>")
    p.add(p.grafico(g.fig_pareto(painel.fornecedores(banco))))
    p.add(p.notas("contra_quem"))


def onde_ha_espaco(p: Pagina, ano: int, banco: Path | None) -> None:
    p.add("<h2>Onde há espaço</h2>")
    p.add("<div class='duas'><div>" + p.grafico(g.fig_sem_resultado(painel.compras_sem_resultado(ano, banco), ano))
          + "</div><div>" + p.grafico(g.fig_dispensas(painel.dispensas_com_disputa(ano, banco), ano))
          + "</div></div>")
    p.add(p.notas("espaco"))


def ti_e_dados(p: Pagina, ano: int, banco: Path | None) -> None:
    p.add("<h2>TI e dados</h2>")
    for segmento in ("ti", "dados"):
        p.add(p.grafico(g.fig_ti_e_dados(painel.ti_e_dados(ano, segmento, banco), ano, segmento)))
    p.add("<h3>Principais fornecedores</h3>")
    p.add(p.tabela(g.tabela_fornecedores_segmento(painel.ti_e_dados_fornecedores(banco))))
    p.add(p.notas("ti_e_dados"))


def montar(banco: Path | None = None, hoje: date | None = None) -> str:
    k = painel.kpis(banco)
    ano = int(k["ano_referencia"])
    p = Pagina()
    p.add(topo(k, hoje))
    p.add(cartoes(k))
    p.add(f"<p>Gráficos por ano mostram {ano}, o ano da data de referência; tabelas sem filtro de segmento.</p>")
    # As seções na ordem do painel; o primeiro gráfico leva o JavaScript do Plotly.
    quando_agir(p, banco)
    onde_esta_o_dinheiro(p, ano, banco)
    contra_quem(p, banco)
    onde_ha_espaco(p, ano, banco)
    ti_e_dados(p, ano, banco)
    p.add(f"<footer>{html.escape(g.RODAPE)}</footer>")
    return (
        "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Compras da FAB no PNCP: dados até {g.data(k['data_referencia'])}</title>"
        f"<style>{ESTILO}</style></head><body>" + "\n".join(p.partes) + "</body></html>"
    )


def gerar(banco: Path | None = None, destino: Path = DESTINO, hoje: date | None = None) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar(banco, hoje), encoding="utf-8")
    return destino


def main() -> int:
    comeco = time.perf_counter()
    destino = gerar()
    print(f"relatório gravado em {destino} em {time.perf_counter() - comeco:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
