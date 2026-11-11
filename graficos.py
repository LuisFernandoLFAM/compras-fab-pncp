"""Figuras, tabelas e notas de leitura do painel e do relatório (spec: specs/painel.md).

Monta a apresentação a partir dos DataFrames de painel.py, sem calcular nenhum número:
só rotula, formata e desenha. O painel (app.py) e o relatório (relatorio.py) usam as
mesmas funções, para os dois mostrarem os mesmos gráficos.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

COR = "#1f4e79"
COR_CLARA = "#9dbbd8"
CORES_SINAL = {"verde": "#2e7d32", "amarelo": "#f9a825", "vermelho": "#c62828"}
FAIXAS = {"ate_3_meses": "até 3 meses", "3_a_6_meses": "3 a 6 meses", "6_a_12_meses": "6 a 12 meses"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
# Caixa de detalhe explícita: sem isso, o tema escuro do Streamlit deixa o texto claro sobre fundo branco.
HOVERLABEL = {"bgcolor": "white", "bordercolor": "#888888", "font": {"color": "#222222"}}


# --- formatação ---------------------------------------------------------------------------


def numero(valor) -> str:
    if valor is None or pd.isna(valor):
        return "-"
    return f"{int(valor):,}".replace(",", ".")


def reais(valor) -> str:
    """Valor em reais, abreviado: R$ 11,5 bi, R$ 578,6 mi, R$ 25,9 mil."""
    if valor is None or pd.isna(valor):
        return "-"
    valor = float(valor)
    for limite, sufixo in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(valor) >= limite:
            return f"R$ {valor / limite:,.1f} {sufixo}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def percentual(valor) -> str:
    if valor is None or pd.isna(valor):
        return "-"
    return f"{float(valor) * 100:.1f}%".replace(".", ",")


def data(valor, com_hora: bool = False) -> str:
    if valor is None or pd.isna(valor):
        return "-"
    return pd.Timestamp(valor).strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


# --- cartões e topo -----------------------------------------------------------------------------


def cartoes(k: dict) -> list[dict]:
    """Os cinco cartões, na ordem do rascunho: título, número principal e rodapé."""
    referencia = data(k["data_referencia"])
    return [
        {
            "titulo": f"Compras em {k['ano_referencia']}",
            "valor": numero(k["compras_ano"]),
            "rodape": f"{reais(k['valor_estimado_ano'])} estimados; ano até {referencia}",
        },
        {
            "titulo": "Propostas abertas",
            "valor": numero(k["propostas_abertas"]),
            "rodape": f"{reais(k['valor_estimado_propostas_abertas'])} estimados; encerram depois de {referencia}",
        },
        {
            "titulo": "Contratos a vencer em 3 meses",
            "valor": numero(k["contratos_a_vencer_3_meses"]),
            "rodape": f"{reais(k['valor_a_vencer_3_meses'])}; vigência termina até 3 meses depois de {referencia}",
        },
        {
            "titulo": f"Desconto mediano em {k['ano_referencia']}",
            "valor": percentual(k["desconto_mediano_ano"]),
            "rodape": f"sobre {numero(k['compras_com_desconto_ano'])} compras; fora credenciamento, "
                      "estimado zero e homologado nulo ou zero",
        },
        {
            "titulo": "Concentração",
            "valor": f"{numero(k['fornecedores_80_por_cento'])} fornecedores",
            "rodape": f"fazem 80% do valor contratado, de {numero(k['fornecedores'])}",
        },
    ]


# --- notas de leitura (spec dos marts) ---------------------------------------------------------

NOTAS = {
    "quando_agir": [
        ("\"Proposta aberta\" e \"contrato a vencer\" são relativos à data de referência; se a ingestão "
         "parar, compras já encerradas continuam aparecendo."),
        "Contratos com vigência sem fim nunca aparecem como a vencer.",
        ("Incumbente pessoa física ou empresário individual (MEI) aparece como \"Pessoa física\" ou "
         "\"Empresário individual\", sem nome, objeto e tempo de casa."),
        "O segmento é heurístico (palavras-chave no objeto) e inclui capacitação: cursos, pós-graduações e MBAs.",
    ],
    "dinheiro": [
        "Compras com valor estimado zero contam como compra, mas ficam fora do ticket médio e do desconto.",
        "Homologado nulo fica fora da soma do homologado e do desconto; homologado zero fica fora do desconto.",
        "O mês da data de referência está incompleto (em cor clara) e não deve ser comparado com os outros.",
        "O prazo médio do credenciamento é longo (anos), porque o credenciamento fica aberto enquanto vigora.",
        ("Desconto: média simples e mediana; a mediana é menos afetada pelos extremos, como as compras "
         "homologadas acima do estimado."),
    ],
    "contra_quem": [
        "O valor contratado soma o valor global de todos os contratos do período, inclusive os sem compra encontrada.",
        ("Todos os contratos de pessoa física formam uma única linha, \"Pessoa física\", e todos os de "
         "empresário individual (MEI), outra, \"Empresário individual\"."),
        "O nome exibido é o do contrato mais recente do fornecedor.",
    ],
    "espaco": [
        ("\"Provavelmente sem resultado\" é inferido: o PNCP não informa se a compra foi deserta ou fracassada. "
         "Ficam de fora as revogadas, anuladas e suspensas."),
        ("A taxa só considera compras divulgadas, com disputa e propostas encerradas há mais de 90 dias, "
         "e o gráfico mostra só combinações com pelo menos 10 compras elegíveis."),
        "\"Nenhum contrato ligado\" olha só os contratos com compra encontrada.",
    ],
    "ti_e_dados": [
        "O segmento é uma classificação heurística por palavras-chave no objeto: haverá falsos positivos e negativos.",
        "\"ti\" inclui \"dados\".",
        "O segmento inclui capacitação em TI e dados, que mostra demanda de formação, e não só fornecimento de tecnologia.",
    ],
}

RODAPE = (
    "Fonte: PNCP - Portal Nacional de Contratações Públicas. Cobertura: matriz e 7 filiais do Comando da "
    "Aeronáutica; a lista de filiais pode estar incompleta, e as filiais só publicaram compras em 2024 e "
    "2025. Definições em specs/marts.md e specs/painel.md."
)


# --- tabelas ------------------------------------------------------------------------------------


def _rotular(df: pd.DataFrame, colunas: dict[str, tuple[str, callable]]) -> pd.DataFrame:
    """Escolhe, renomeia e formata as colunas para exibição; não muda nenhum número."""
    saida = pd.DataFrame(index=df.index)
    for coluna, (rotulo, formato) in colunas.items():
        saida[rotulo] = df[coluna].map(formato) if formato else df[coluna]
    return saida.reset_index(drop=True)


def _texto(valor) -> str:
    return "-" if valor is None or pd.isna(valor) else str(valor)


def tabela_propostas(df: pd.DataFrame) -> pd.DataFrame:
    return _rotular(df, {
        "unidade_nome": ("Unidade", None),
        "uf": ("UF", None),
        "modalidade_nome": ("Modalidade", None),
        "objeto_compra": ("Objeto", _texto),
        "valor_estimado": ("Valor estimado", reais),
        "data_encerramento_proposta": ("Encerra em", lambda v: data(v, com_hora=True)),
        "dias_para_encerrar": ("Dias", numero),
        "segmento": ("Segmento", None),
    })


def tabela_contratos(df: pd.DataFrame) -> pd.DataFrame:
    return _rotular(df, {
        "unidade_nome": ("Unidade", None),
        "objeto_contrato": ("Objeto", _texto),
        "valor_global": ("Valor", reais),
        "data_vigencia_fim": ("Fim da vigência", data),
        "faixa_vencimento": ("Faixa", FAIXAS.get),
        "fornecedor_nome": ("Incumbente", _texto),
        "cliente_desde": ("Cliente desde", data),
        "tempo_de_casa_anos": ("Tempo de casa (anos)", lambda v: "-" if pd.isna(v) else f"{v:.1f}".replace(".", ",")),
        "segmento": ("Segmento", None),
    })


def tabela_modalidades(df: pd.DataFrame) -> pd.DataFrame:
    return _rotular(df, {
        "modalidade_nome": ("Modalidade", None),
        "compras": ("Compras", numero),
        "valor_estimado": ("Valor estimado", reais),
        "ticket_medio": ("Ticket médio", reais),
        "faixa_estimado_zero": ("Estimado zero", numero),
        "faixa_ate_50_mil": ("Até 50 mil", numero),
        "faixa_50_mil_a_500_mil": ("50 a 500 mil", numero),
        "faixa_500_mil_a_5_milhoes": ("500 mil a 5 mi", numero),
        "faixa_acima_5_milhoes": ("Acima de 5 mi", numero),
        "prazo_medio_propostas_dias": ("Prazo das propostas (dias)", numero),
        "desconto_medio": ("Desconto médio", percentual),
        "desconto_mediano": ("Desconto mediano", percentual),
    })


def tabela_fornecedores_segmento(df: pd.DataFrame) -> pd.DataFrame:
    return _rotular(df, {
        "segmento": ("Segmento", None),
        "posicao": ("Posição", numero),
        "fornecedor_nome": ("Fornecedor", _texto),
        "contratos": ("Contratos", numero),
        "valor_contratado": ("Valor contratado", reais),
        "participacao_no_segmento": ("Participação", percentual),
    })


# --- gráficos -----------------------------------------------------------------------------------


def _layout(fig: go.Figure, titulo: str, altura: int = 420) -> go.Figure:
    fig.update_layout(
        title=titulo, height=altura, margin={"l": 10, "r": 10, "t": 50, "b": 10},
        plot_bgcolor="white", separators=",.", hoverlabel=HOVERLABEL,
    )
    fig.update_xaxes(gridcolor="#eeeeee")
    fig.update_yaxes(gridcolor="#eeeeee")
    return fig


def fig_compras_mensal(df: pd.DataFrame) -> go.Figure:
    rotulos = [f"{MESES[m - 1]}/{a}" for a, m in zip(df["ano"], df["mes"], strict=True)]
    fig = go.Figure(go.Bar(
        x=rotulos, y=df["valor_estimado"].astype(float),
        marker_color=[COR if completo else COR_CLARA for completo in df["mes_completo"]],
        customdata=df[["compras"]], hovertemplate="%{x}<br>R$ %{y:,.0f}<br>%{customdata[0]} compras<extra></extra>",
    ))
    fig.update_yaxes(title="Valor estimado (R$)")
    return _layout(fig, "Valor estimado das compras por mês de publicação")


def fig_sazonalidade(df: pd.DataFrame) -> go.Figure:
    grade = df.pivot(index="ano", columns="mes", values="participacao_compras_no_ano").reindex(columns=range(1, 13))
    fig = go.Figure(go.Heatmap(
        z=grade.values, x=MESES, y=[str(a) for a in grade.index], colorscale="Blues",
        hovertemplate="%{x}/%{y}: %{z:.1%} das compras do ano<extra></extra>", colorbar={"tickformat": ".0%"},
    ))
    return _layout(fig, "Sazonalidade: participação de cada mês nas compras do ano", altura=300)


def fig_unidades(df: pd.DataFrame, ano: int) -> go.Figure:
    df = df.iloc[::-1]
    fig = go.Figure(go.Bar(
        y=[f"{n} ({uf})" for n, uf in zip(df["unidade_nome"], df["uf"], strict=True)],
        x=df["valor_estimado"].astype(float), orientation="h", marker_color=COR,
        customdata=df[["compras"]], hovertemplate="%{y}<br>R$ %{x:,.0f}<br>%{customdata[0]} compras<extra></extra>",
    ))
    fig.update_xaxes(title="Valor estimado (R$)")
    return _layout(fig, f"Unidades com maior valor estimado em {ano}", altura=520)


def fig_categorias(df: pd.DataFrame, ano: int) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=df["categoria_processo_nome"], y=df["valor_contratado"].astype(float), marker_color=COR,
        customdata=df[["contratos"]], hovertemplate="%{x}<br>R$ %{y:,.0f}<br>%{customdata[0]} contratos<extra></extra>",
    ))
    fig.update_yaxes(title="Valor contratado (R$)")
    return _layout(fig, f"Valor contratado por categoria em {ano}")


def fig_pareto(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=df["fornecedor_nome"], y=df["valor_contratado"].astype(float), name="Valor contratado",
        marker_color=[COR if dentro else COR_CLARA for dentro in df["ate_80_por_cento"]],
        hovertemplate="%{x}<br>R$ %{y:,.0f}<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=df["fornecedor_nome"], y=df["participacao_acumulada"], name="Participação acumulada",
        mode="lines+markers", line={"color": "#c62828"}, hovertemplate="%{y:.1%}<extra></extra>",
    ), secondary_y=True)
    fig.add_hline(y=0.8, line_dash="dash", line_color="#888888", secondary_y=True,
                  annotation_text="80%", annotation_position="top left")
    fig.update_yaxes(title="Valor contratado (R$)", secondary_y=False)
    fig.update_yaxes(title="Acumulado", tickformat=".0%", range=[0, 1.05], secondary_y=True)
    fig.update_xaxes(tickangle=-45)
    fig.update_layout(legend={"orientation": "h", "y": 1.1})
    return _layout(fig, f"Pareto dos {len(df)} maiores fornecedores", altura=560)


def fig_sem_resultado(df: pd.DataFrame, ano: int) -> go.Figure:
    df = df.iloc[::-1]
    fig = go.Figure(go.Bar(
        y=[f"{u} · {m}" for u, m in zip(df["unidade_nome"], df["modalidade_nome"], strict=True)],
        x=df["taxa_provaveis_sem_resultado"], orientation="h", marker_color=COR,
        text=[f"{e} elegíveis" for e in df["compras_elegiveis"]], textposition="outside",
        customdata=df[["provaveis_sem_resultado"]],
        hovertemplate="%{y}<br>%{x:.1%} (%{customdata[0]} compras)<extra></extra>",
    ))
    fig.update_xaxes(title="Taxa de compras provavelmente sem resultado", tickformat=".0%")
    return _layout(fig, f"Onde as compras com disputa ficam provavelmente sem resultado ({ano})", altura=520)


def fig_dispensas(df: pd.DataFrame, ano: int) -> go.Figure:
    df = df.iloc[::-1]
    fig = go.Figure(go.Bar(
        y=[f"{n} ({uf})" for n, uf in zip(df["unidade_nome"], df["uf"], strict=True)],
        x=df["dispensas_com_disputa"], orientation="h", marker_color=COR,
        customdata=df[["participacao_com_disputa", "desconto_mediano"]],
        hovertemplate="%{y}<br>%{x} dispensas com disputa<br>%{customdata[0]:.0%} das dispensas"
                      "<br>desconto mediano %{customdata[1]:.1%}<extra></extra>",
    ))
    fig.update_xaxes(title="Dispensas com disputa")
    return _layout(fig, f"Unidades com mais dispensas com disputa em {ano}", altura=520)


def fig_ti_e_dados(df: pd.DataFrame, ano: int, segmento: str) -> go.Figure:
    fig = go.Figure([
        go.Bar(name="Compras (valor estimado)", x=df["unidade_nome"], y=df["valor_estimado"].astype(float),
               marker_color=COR, hovertemplate="%{x}<br>R$ %{y:,.0f}<extra></extra>"),
        go.Bar(name="Contratos (valor contratado)", x=df["unidade_nome"], y=df["valor_contratado"].astype(float),
               marker_color=COR_CLARA, hovertemplate="%{x}<br>R$ %{y:,.0f}<extra></extra>"),
    ])
    fig.update_layout(barmode="group", legend={"orientation": "h", "y": 1.1})
    fig.update_xaxes(tickangle=-45)
    fig.update_yaxes(title="R$")
    return _layout(fig, f"Segmento {segmento} por unidade em {ano}", altura=480)
