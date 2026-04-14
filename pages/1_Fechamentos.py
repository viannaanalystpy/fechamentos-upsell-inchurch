import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from dateutil.relativedelta import relativedelta

st.set_page_config(
    page_title="Fechamentos | InChurch",
    page_icon="📊",
    layout="wide",
)

st.session_state["_page_key"] = "fechamentos"

from utils.style import inject_css, chart_layout, PALETTE, FONTE_COLORS, PRODUTO_COLORS, PLAN_COLORS
from utils.data import load_fechamentos, load_metas, fmt_brl, mes_fmt_ordered, last_val, prev_val, delta_str, no_data
from utils.auth import check_login

inject_css()
check_login()

# ── Carregar dados ────────────────────────────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_raw  = load_fechamentos()
    df_meta = load_metas()

if df_raw.empty:
    no_data("Nenhum dado encontrado.")
    st.stop()

# Preenche nulos de atribuição comercial (SPLGC não tem vendedor/SDR/canal)
SEM_ATRIB = "Sem atribuição"
df_raw = df_raw.copy()
for col in ("sales_owner", "sdr_owner", "channel"):
    df_raw[col] = df_raw[col].fillna(SEM_ATRIB).replace("", SEM_ATRIB)

# ── Sidebar — Filtros ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filtros")

    meses_opcoes = {"Todos": None}
    for m in sorted(df_raw["mes"].unique()):
        label = pd.Timestamp(m).strftime("%B/%y").capitalize()
        meses_opcoes[label] = pd.Timestamp(m)
    mes_sel_label = st.selectbox("Mês", options=list(meses_opcoes.keys()), index=0, key="mes_sel")
    mes_sel = meses_opcoes[mes_sel_label]

    vendedores = ["Todos"] + sorted(df_raw["sales_owner"].dropna().unique().tolist())
    vendedor_sel = st.selectbox("Vendedor", vendedores, key="vend_sel")

    sdrs = ["Todos"] + sorted(df_raw["sdr_owner"].dropna().unique().tolist())
    sdr_sel = st.selectbox("Pré-vendedor (SDR)", sdrs, key="sdr_sel")

    produtos = ["Todos"] + sorted(df_raw["products"].dropna().unique().tolist())
    produto_sel = st.selectbox("Produto", produtos, key="prod_sel")

    canais = ["Todos"] + sorted(df_raw["channel"].dropna().unique().tolist())
    canal_sel = st.selectbox("Canal", canais, key="canal_sel")

    planos = ["Todos"] + sorted(df_raw["plan"].dropna().replace("", pd.NA).dropna().unique().tolist())
    plano_sel = st.selectbox("Plano", planos, key="plano_sel")

    st.divider()
    if st.button("Atualizar dados", use_container_width=True, key="refresh_btn"):
        st.cache_data.clear()
        st.rerun()

# ── Aplicar filtros ───────────────────────────────────────────────────────────
cutoff_12m = pd.Timestamp.today().normalize() - relativedelta(months=12)

def apply_filters(src, include_date_cutoff=False):
    d = src.copy()
    if mes_sel:
        d = d[d["mes"] == mes_sel]
    elif include_date_cutoff:
        d = d[d["mes"] >= cutoff_12m]
    if vendedor_sel != "Todos":
        d = d[d["sales_owner"] == vendedor_sel]
    if sdr_sel != "Todos":
        d = d[d["sdr_owner"] == sdr_sel]
    if produto_sel != "Todos":
        d = d[d["products"] == produto_sel]
    if canal_sel != "Todos":
        d = d[d["channel"] == canal_sel]
    if plano_sel != "Todos":
        d = d[d["plan"] == plano_sel]
    return d

# df = dados p/ gráficos (últimos 12 meses quando "Todos"); df_hist = histórico completo p/ tabela
df      = apply_filters(df_raw, include_date_cutoff=True)
df_hist = apply_filters(df_raw, include_date_cutoff=False)

if df.empty and df_hist.empty:
    st.markdown("<h1>Fechamento <span>de Vendas</span></h1>", unsafe_allow_html=True)
    no_data("Nenhum dado para os filtros selecionados.")
    st.stop()

df = df if not df.empty else df_hist

# ── Deduplicação ─────────────────────────────────────────────────────────────
fonte_order = {"SPLGC": 0, "Fechamentos Backend": 1, "HubSpot": 2, "Ajustes manuais": 3}
df["_rank"] = df["fonte"].map(fonte_order).fillna(99)

# df_unique: 1 linha por deal (para contagem e tabela)
df_unique = (
    df.sort_values("_rank")
    .drop_duplicates(subset=["mes", "tertiarygroup_id"])
    .drop(columns="_rank")
)

# df_monetary: todas as linhas da fonte de maior prioridade por deal
# (preserva multi-produto, exclui fontes duplicadas de menor prioridade)
_min_rank = (
    df.groupby(["mes", "tertiarygroup_id"])["_rank"]
    .min()
    .reset_index(name="_min_rank")
)
df_monetary = (
    df.merge(_min_rank, on=["mes", "tertiarygroup_id"])
    .pipe(lambda x: x[x["_rank"] == x["_min_rank"]])
    .drop(columns=["_rank", "_min_rank"])
)

df = df.drop(columns="_rank")

# Deduplicação para tabela histórica
df_hist["_rank"] = df_hist["fonte"].map(fonte_order).fillna(99)
df_unique_hist = (
    df_hist.sort_values("_rank")
    .drop_duplicates(subset=["mes", "tertiarygroup_id"])
    .drop(columns="_rank")
)
_min_rank_hist = (
    df_hist.groupby(["mes", "tertiarygroup_id"])["_rank"]
    .min()
    .reset_index(name="_min_rank")
)
df_monetary_hist = (
    df_hist.merge(_min_rank_hist, on=["mes", "tertiarygroup_id"])
    .pipe(lambda x: x[x["_rank"] == x["_min_rank"]])
    .drop(columns=["_rank", "_min_rank"])
)
df_hist = df_hist.drop(columns="_rank")

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown("<h1>Fechamento <span>de Vendas</span></h1>", unsafe_allow_html=True)

# ── KPIs ─────────────────────────────────────────────────────────────────────
st.markdown("<h2>Visao Geral</h2>", unsafe_allow_html=True)

total_deals = df_unique["tertiarygroup_id"].nunique()
total_mrr   = df_monetary["value"].sum()
total_setup = df_monetary["setup"].sum()
total_fyv   = df_monetary.groupby("tertiarygroup_id")["fyv"].sum().sum()

df_mes_kpi = df_unique.groupby("mes").agg(
    deals=("tertiarygroup_id", "nunique"),
).reset_index()
df_mrr_kpi = df_monetary.groupby("mes").agg(mrr=("value", "sum"), fyv_sum=("fyv", "sum")).reset_index()
df_mes_kpi = df_mes_kpi.merge(df_mrr_kpi, on="mes", how="left")

k1, k2, k3, k4 = st.columns(4)
with k1:
    curr = last_val(df_mes_kpi, "deals"); prev = prev_val(df_mes_kpi, "deals")
    st.metric("Total de Deals", f"{total_deals:,}", delta=delta_str(curr, prev))
with k2:
    curr = last_val(df_mes_kpi, "mrr"); prev = prev_val(df_mes_kpi, "mrr")
    st.metric("MRR Total", fmt_brl(total_mrr), delta=delta_str(curr, prev, suffix=" vs mês ant."))
with k3:
    st.metric("Setup Total", fmt_brl(total_setup))
with k4:
    curr = last_val(df_mes_kpi, "fyv_sum"); prev = prev_val(df_mes_kpi, "fyv_sum")
    st.metric("FYV Total", fmt_brl(total_fyv), delta=delta_str(curr, prev, suffix=" vs mês ant."))

st.divider()

# ── Gráfico 1: FYV por mês vs Meta ───────────────────────────────────────────
st.markdown("<h2>FYV por Mes vs Meta</h2>", unsafe_allow_html=True)

df_fyv_mes = (
    df_unique.groupby("mes")["fyv"]
    .sum()
    .reset_index(name="fyv")
)
df_fyv_mes, x_order = mes_fmt_ordered(df_fyv_mes)

# Mescla com metas
df_meta_plot = df_meta.copy()
df_meta_plot["mes_fmt"] = df_meta_plot["mes"].dt.strftime("%b/%y").str.capitalize()

fig1 = go.Figure()
fig1.add_bar(
    x=df_fyv_mes["mes_fmt"], y=df_fyv_mes["fyv"],
    name="FYV Realizado",
    marker_color=PALETTE[0],
    text=df_fyv_mes["fyv"].apply(lambda v: fmt_brl(v)),
    textposition="outside",
    textfont=dict(size=10, color="#a0a0a0"),
    hovertemplate="<b>FYV</b><br>R$ %{y:,.0f}<extra></extra>",
)
# Linha de meta (só plota meses que existem no período filtrado)
meta_no_periodo = df_meta_plot[df_meta_plot["mes_fmt"].isin(x_order)]
if not meta_no_periodo.empty:
    fig1.add_scatter(
        x=meta_no_periodo["mes_fmt"], y=meta_no_periodo["meta"],
        name="Meta",
        mode="lines+markers",
        line=dict(color="#ffffff", width=2, dash="dot"),
        marker=dict(size=7),
        hovertemplate="<b>Meta</b><br>R$ %{y:,.0f}<extra></extra>",
    )
fig1.update_layout(
    barmode="group",
    xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
)
chart_layout(fig1, height=380, legend_bottom=True)
fig1.update_yaxes(showgrid=False)
st.plotly_chart(fig1, use_container_width=True)

st.divider()

# ── Gráfico 2: MRR por mês ───────────────────────────────────────────────────
st.markdown("<h2>MRR por Mes</h2>", unsafe_allow_html=True)

df_mrr_mes = df_monetary.groupby("mes")["value"].sum().reset_index(name="mrr")
df_mrr_mes, x_order2 = mes_fmt_ordered(df_mrr_mes)

fig2 = go.Figure()
fig2.add_bar(
    x=df_mrr_mes["mes_fmt"], y=df_mrr_mes["mrr"],
    name="MRR",
    marker_color=PALETTE[0],
    text=df_mrr_mes["mrr"].apply(lambda v: fmt_brl(v)),
    textposition="outside",
    textfont=dict(size=10, color="#a0a0a0"),
    hovertemplate="<b>MRR</b><br>R$ %{y:,.2f}<extra></extra>",
)
fig2.update_layout(
    xaxis=dict(categoryorder="array", categoryarray=x_order2, type="category"),
)
chart_layout(fig2, height=360)
fig2.update_yaxes(showgrid=False)
st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Gráfico 3: Pizza por Plano + Mini Tabela ─────────────────────────────────
st.markdown("<h2>Distribuicao por Plano</h2>", unsafe_allow_html=True)

df_plano = (
    df_unique[df_unique["plan"].notna() & (df_unique["plan"] != "")]
    .groupby("plan")
    .agg(deals=("tertiarygroup_id", "nunique"))
    .reset_index()
    .sort_values("deals", ascending=False)
)
df_plano_mrr = (
    df_monetary[df_monetary["plan"].notna() & (df_monetary["plan"] != "")]
    .groupby("plan")["value"]
    .sum()
    .reset_index(name="mrr")
)
df_plano = df_plano.merge(df_plano_mrr, on="plan", how="left")

# Cores de fundo por fatia
plano_colors = [
    PLAN_COLORS.get(str(p).lower(), PLAN_COLORS["outros"])
    for p in df_plano["plan"]
]

fig3 = go.Figure()
fig3.add_pie(
    labels=df_plano["plan"],
    values=df_plano["deals"],
    marker=dict(colors=plano_colors, line=dict(color="#000000", width=2)),
    textinfo="label+percent",
    textposition="outside",
    outsidetextfont=dict(size=11, family="Outfit, sans-serif", color="#cccccc"),
    hovertemplate="<b>%{label}</b><br>%{value} deals (%{percent})<extra></extra>",
    hole=0.45,
)
chart_layout(fig3, height=360)
fig3.update_layout(showlegend=False)

col_pizza, col_tabela = st.columns([1.2, 0.8])
with col_pizza:
    st.plotly_chart(fig3, use_container_width=True)
with col_tabela:
    st.markdown("<br>", unsafe_allow_html=True)
    df_plano_display = df_plano.copy()
    df_plano_display["MRR Total"] = df_plano_display["mrr"].apply(lambda v: fmt_brl(v, decimals=2))
    df_plano_display = df_plano_display.rename(columns={"plan": "Plano", "deals": "Deals"})
    st.dataframe(
        df_plano_display[["Plano", "Deals", "MRR Total"]],
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(df_plano_display) + 38, 360),
    )

st.divider()

# ── Tabela Detalhada ──────────────────────────────────────────────────────────
st.markdown("<h2>Tabela de Fechamentos</h2>", unsafe_allow_html=True)

# Tabela usa histórico completo (sem filtro de 12 meses)
df_rev = df_monetary_hist.groupby("tertiarygroup_id").agg(
    mrr=("value", "sum"),
    setup_total=("setup", "sum"),
).reset_index()

# Mapeia fonte → origem legível (3 categorias)
def _origem(fonte):
    if pd.isna(fonte) or fonte == "":
        return "Fechamento"
    f = str(fonte).lower()
    if "painel" in f:
        return "Upsell Painel"
    if "form" in f:
        return "Upsell Formulário"
    return "Fechamento"

# Seleciona apenas as colunas necessárias de df_unique_hist antes do merge
df_tabela = df_unique_hist[[
    "first_payment", "company_name", "tertiarygroup_id",
    "fyv", "sales_owner", "sdr_owner", "products",
    "fonte", "conferencia_invalida",
]].merge(df_rev, on="tertiarygroup_id", how="left")
df_tabela = df_tabela[[
    "first_payment", "company_name", "tertiarygroup_id",
    "mrr", "setup_total", "fyv",
    "sales_owner", "sdr_owner", "products", "fonte",
    "conferencia_invalida",
]].copy()
df_tabela["fonte"] = df_tabela["fonte"].apply(_origem)

df_tabela.columns = [
    "Data 1º Pgto", "Igreja", "Cód. Local",
    "MRR", "Setup", "FYV",
    "Vendedor", "SDR", "Produto", "Origem",
    "Conferência Inválida",
]

df_tabela = df_tabela.sort_values("Data 1º Pgto", ascending=False)
df_tabela["Data 1º Pgto"] = pd.to_datetime(df_tabela["Data 1º Pgto"]).dt.strftime("%d/%m/%Y")
df_tabela["MRR"]   = df_tabela["MRR"].apply(lambda v: fmt_brl(v, decimals=2))
df_tabela["Setup"] = df_tabela["Setup"].apply(lambda v: fmt_brl(v, decimals=2))
df_tabela["FYV"]   = df_tabela["FYV"].apply(lambda v: fmt_brl(v, decimals=2))

# Highlight linhas com conferência inválida
def highlight_invalido(row):
    if row["Conferência Inválida"]:
        return ["background-color: rgba(255,80,80,0.12)"] * len(row)
    return [""] * len(row)

st.dataframe(
    df_tabela.style.apply(highlight_invalido, axis=1),
    use_container_width=True,
    hide_index=True,
    height=500,
)

invalidos = df_tabela[df_tabela["Conferência Inválida"] != ""]
if not invalidos.empty:
    st.warning(f"{len(invalidos)} registro(s) com conferência inválida.")
