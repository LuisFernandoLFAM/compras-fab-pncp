"""Etapa 4: painel em Streamlit (spec: specs/painel.md).

    uv run streamlit run app.py

Layout em Z: topo (título e saúde do dado), cartões, filtros e cinco seções. Os números
vêm prontos dos marts (painel.py); a tela só desenha (graficos.py).
"""

import duckdb
import streamlit as st

import graficos as g
import painel

st.set_page_config(page_title="Compras da FAB no PNCP", layout="wide")


@st.cache_data(show_spinner="Lendo os marts...")
def consultar(nome: str, *args):
    return getattr(painel, nome)(*args)


def notas(chave: str) -> None:
    with st.expander("Notas de leitura"):
        for nota in g.NOTAS[chave]:
            st.markdown(f"- {nota}")


def tabela(df) -> None:
    st.dataframe(df, hide_index=True, use_container_width=True)


# --- topo ---------------------------------------------------------------------------------

try:
    k = consultar("kpis")
except duckdb.Error as e:
    st.error(
        "Não foi possível ler os marts. Rode `uv run python -m pipeline` e confira se ele não está "
        f"gravando no banco agora.\n\n{e}"
    )
    st.stop()

esquerda, direita = st.columns([3, 2])
with esquerda:
    st.title("Compras da FAB no PNCP")
    st.caption("Para o time de licitações de uma empresa que quer vender para a Força Aérea Brasileira.")
with direita:
    dias, cor = painel.sinal_da_extracao(k["extraido_em"].to_pydatetime())
    st.markdown(
        f"<span style='color:{g.CORES_SINAL[cor]};font-size:1.4em'>●</span> "
        f"**Dados extraídos em** {g.data(k['extraido_em'], com_hora=True)} (há {dias} dias)<br>"
        f"**Publicação mais recente:** {g.data(k['publicacao_mais_recente'], com_hora=True)}<br>"
        f"**Dados até** {g.data(k['data_referencia'])}",
        unsafe_allow_html=True,
    )
    if st.button("Recarregar dados"):
        st.cache_data.clear()
        st.rerun()

# --- cartões ---------------------------------------------------------------------------------

for coluna, cartao in zip(st.columns(5), g.cartoes(k), strict=True):
    with coluna:
        st.metric(cartao["titulo"], cartao["valor"])
        st.caption(cartao["rodape"])

# --- filtros ---------------------------------------------------------------------------------

filtro_ano, filtro_segmento, _ = st.columns([1, 1, 3])
with filtro_ano:
    ano = st.selectbox("Ano", consultar("anos"), help="Vale para os gráficos que têm ano.")
with filtro_segmento:
    segmento = st.selectbox(
        "Segmento", list(painel.SEGMENTOS), help="Vale para \"Quando agir\"; ti inclui dados."
    )

# --- 1. Quando agir -----------------------------------------------------------------------------

st.header("Quando agir")
st.subheader("Propostas abertas")
tabela(g.tabela_propostas(consultar("propostas_abertas", segmento)))
st.subheader("Contratos a vencer")
faixas = st.multiselect(
    "Faixa de vencimento", list(g.FAIXAS), default=list(g.FAIXAS), format_func=g.FAIXAS.get
)
tabela(g.tabela_contratos(consultar("contratos_a_vencer", segmento, faixas)))
notas("quando_agir")

# --- 2. Onde está o dinheiro ----------------------------------------------------------------------

st.header("Onde está o dinheiro")
mensal = consultar("compras_mensal")
st.plotly_chart(g.fig_compras_mensal(mensal), use_container_width=True)
st.plotly_chart(g.fig_sazonalidade(mensal), use_container_width=True)
unidades, categorias = st.columns(2)
with unidades:
    st.plotly_chart(g.fig_unidades(consultar("compras_por_unidade", ano), ano), use_container_width=True)
with categorias:
    st.plotly_chart(g.fig_categorias(consultar("contratos_por_categoria", ano), ano), use_container_width=True)
st.subheader(f"Compras por modalidade em {ano}")
tabela(g.tabela_modalidades(consultar("compras_por_modalidade", ano)))
notas("dinheiro")

# --- 3. Contra quem -----------------------------------------------------------------------------

st.header("Contra quem")
resumo = consultar("fornecedores_resumo")
st.markdown(
    f"**{g.numero(resumo['fornecedores_80_por_cento'])} de {g.numero(resumo['fornecedores'])} fornecedores** "
    "fazem 80% do valor contratado."
)
st.plotly_chart(g.fig_pareto(consultar("fornecedores")), use_container_width=True)
notas("contra_quem")

# --- 4. Onde há espaço ----------------------------------------------------------------------------

st.header("Onde há espaço")
sem_resultado, dispensas = st.columns(2)
with sem_resultado:
    st.plotly_chart(g.fig_sem_resultado(consultar("compras_sem_resultado", ano), ano), use_container_width=True)
with dispensas:
    st.plotly_chart(g.fig_dispensas(consultar("dispensas_com_disputa", ano), ano), use_container_width=True)
notas("espaco")

# --- 5. TI e dados --------------------------------------------------------------------------------

st.header("TI e dados")
segmento_ti = st.radio("Segmento", ["ti", "dados"], horizontal=True, key="segmento_ti")
st.plotly_chart(
    g.fig_ti_e_dados(consultar("ti_e_dados", ano, segmento_ti), ano, segmento_ti), use_container_width=True
)
st.subheader("Principais fornecedores")
tabela(g.tabela_fornecedores_segmento(consultar("ti_e_dados_fornecedores")))
notas("ti_e_dados")

st.divider()
st.caption(g.RODAPE)
