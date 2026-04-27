import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from dateutil.relativedelta import relativedelta

from utils.style import inject_css, chart_layout, PALETTE, FONTE_COLORS, PRODUTO_COLORS, PLAN_COLORS
from utils.data import load_fechamentos, load_metas, load_ultima_atualizacao, fmt_brl, mes_fmt_ordered, last_val, prev_val, delta_str, no_data, fmt_mes_abrev_pt

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
df_raw["plan"] = df_raw["plan"].str.strip().str.title()

# ── Sidebar — Filtros ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filtros")

    _MESES_PT = {
        "January": "Janeiro", "February": "Fevereiro", "March": "Março",
        "April": "Abril", "May": "Maio", "June": "Junho",
        "July": "Julho", "August": "Agosto", "September": "Setembro",
        "October": "Outubro", "November": "Novembro", "December": "Dezembro",
    }
    meses_opcoes = {"Todos": None}
    for m in sorted(df_raw["mes"].unique()):
        ts = pd.Timestamp(m)
        label = f"{_MESES_PT.get(ts.strftime('%B'), ts.strftime('%B'))}/{ts.strftime('%y')}"
        meses_opcoes[label] = ts
    mes_sel_label = st.selectbox("Mês", options=list(meses_opcoes.keys()), index=0, key="mes_sel")
    mes_sel = meses_opcoes[mes_sel_label]

    vendedor_sel = st.multiselect(
        "Vendedor",
        options=sorted(df_raw["sales_owner"].dropna().unique().tolist()),
        placeholder="Todos", key="vend_sel",
    )
    sdr_sel = st.multiselect(
        "Pré-vendedor (SDR)",
        options=sorted(df_raw["sdr_owner"].dropna().unique().tolist()),
        placeholder="Todos", key="sdr_sel",
    )
    produto_sel = st.multiselect(
        "Produto",
        options=sorted(df_raw["products"].dropna().unique().tolist()),
        placeholder="Todos", key="prod_sel",
    )
    canal_sel = st.multiselect(
        "Canal",
        options=sorted(df_raw["channel"].dropna().unique().tolist()),
        placeholder="Todos", key="canal_sel",
    )
    plano_sel = st.multiselect(
        "Plano",
        options=sorted(df_raw["plan"].dropna().replace("", pd.NA).dropna().unique().tolist()),
        placeholder="Todos", key="plano_sel",
    )

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
    if vendedor_sel:
        d = d[d["sales_owner"].isin(vendedor_sel)]
    if sdr_sel:
        d = d[d["sdr_owner"].isin(sdr_sel)]
    if produto_sel:
        d = d[d["products"].isin(produto_sel)]
    if canal_sel:
        d = d[d["channel"].isin(canal_sel)]
    if plano_sel:
        d = d[d["plan"].isin(plano_sel)]
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
fonte_order = {
    "Form de Fechamentos \u00b7 Ajustado": 0,
    "Form de Upsell \u00b7 Ajustado":      0,
    "Upsell Painel":                  1,
    "Form de Upsell":                 1,
    "Form de Fechamentos":            2,
    "Sem Assinatura Superlógica":     2,
}
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
    .drop_duplicates(subset=["id"])
    .drop(columns="_rank")
)
_min_rank_hist = (
    df_hist.groupby(["mes", "tertiarygroup_id", "first_payment"])["_rank"]
    .min()
    .reset_index(name="_min_rank")
)
df_monetary_hist = (
    df_hist.merge(_min_rank_hist, on=["mes", "tertiarygroup_id", "first_payment"])
    .pipe(lambda x: x[x["_rank"] == x["_min_rank"]])
    .drop(columns=["_rank", "_min_rank"])
)
df_hist = df_hist.drop(columns="_rank")

# ── Header ───────────────────────────────────────────────────────────────────
ultima_atualizacao = load_ultima_atualizacao()
st.caption(f"Última atualização dos dados: {ultima_atualizacao}")
st.markdown("<h1>Fechamento <span>de Vendas</span></h1>", unsafe_allow_html=True)

# ── KPIs ─────────────────────────────────────────────────────────────────────
st.markdown("<h2>Visao Geral</h2>", unsafe_allow_html=True)

total_deals = df_unique["tertiarygroup_id"].nunique()
total_mrr   = df_monetary["value"].sum()
total_setup = df_monetary["setup"].sum()
total_fyv   = df_monetary.groupby("tertiarygroup_id")["fyv"].sum().sum()

# Delta calculado sobre df_raw sem filtro de mês (para que mês selecionado vs anterior funcione)
_raw_rank = df_raw.copy()
_raw_rank["_rank"] = _raw_rank["fonte"].map(fonte_order).fillna(99)
_raw_min = _raw_rank.groupby(["mes", "tertiarygroup_id"])["_rank"].min().reset_index(name="_min_rank")
_df_raw_monetary = (
    _raw_rank.merge(_raw_min, on=["mes", "tertiarygroup_id"])
    .pipe(lambda x: x[x["_rank"] == x["_min_rank"]])
)
_kpi_full = _df_raw_monetary.groupby("mes").agg(mrr=("value", "sum"), fyv_sum=("fyv", "sum")).reset_index()
_kpi_full_unique = (
    _raw_rank.drop_duplicates(subset=["mes", "tertiarygroup_id"])
    .groupby("mes").agg(deals=("tertiarygroup_id", "nunique")).reset_index()
)
_kpi_full = _kpi_full.merge(_kpi_full_unique, on="mes", how="left")

# Delta só aparece quando um mês específico está selecionado
_last_mes = mes_sel  # None quando "Todos"
_prev_mes = None
if _last_mes is not None:
    meses_anteriores = _kpi_full[_kpi_full["mes"] < _last_mes]["mes"]
    _prev_mes = meses_anteriores.max() if not meses_anteriores.empty else None

def _kpi_val(col, mes):
    if mes is None: return None
    row = _kpi_full[_kpi_full["mes"] == mes]
    return row[col].iloc[0] if not row.empty else None

_mes_label = f" vs {fmt_mes_abrev_pt(_prev_mes)}" if _prev_mes is not None else ""

k1, k2, k3, k4 = st.columns(4)
with k1:
    curr = _kpi_val("deals", _last_mes); prev = _kpi_val("deals", _prev_mes)
    st.metric("Total de Deals", f"{total_deals:,}", delta=delta_str(curr, prev, suffix=_mes_label))
with k2:
    curr = _kpi_val("mrr", _last_mes); prev = _kpi_val("mrr", _prev_mes)
    st.metric("MRR Total", fmt_brl(total_mrr, decimals=2), delta=delta_str(curr, prev, suffix=_mes_label))
with k3:
    st.metric("Setup Total", fmt_brl(total_setup, decimals=2))
with k4:
    curr = _kpi_val("fyv_sum", _last_mes); prev = _kpi_val("fyv_sum", _prev_mes)
    st.metric("FYV Total", fmt_brl(total_fyv, decimals=2), delta=delta_str(curr, prev, suffix=_mes_label))

st.divider()

# ── Gráfico 1: FYV por mês vs Meta ───────────────────────────────────────────
st.markdown("<h2>FYV por Mes vs Meta</h2>", unsafe_allow_html=True)

df_fyv_mes = (
    df_monetary.groupby("mes")["fyv"]
    .sum()
    .reset_index(name="fyv")
)
df_fyv_mes, x_order = mes_fmt_ordered(df_fyv_mes)

# Mescla com metas
df_meta_plot = df_meta.copy()
df_meta_plot["mes_fmt"] = df_meta_plot["mes"].apply(fmt_mes_abrev_pt)

fig1 = go.Figure()
fig1.add_bar(
    x=df_fyv_mes["mes_fmt"], y=df_fyv_mes["fyv"],
    name="FYV Realizado",
    marker_color=PALETTE[0],
    text=df_fyv_mes["fyv"].apply(lambda v: fmt_brl(v, decimals=2)),
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
    text=df_mrr_mes["mrr"].apply(lambda v: fmt_brl(v, decimals=2)),
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
# Mapeia fonte + upsell → origem legível
def _origem(row):
    # str() para lidar com numpy.bool_ / pyarrow scalars (is True falha nesses tipos)
    upsell = str(row.get("upsell")) == 'True'
    from_ajuste = str(row.get("from_ajuste")) == 'True'
    fonte = row.get("fonte", "")
    f = str(fonte).lower() if not (pd.isna(fonte) if fonte is not None else True) else ""

    if upsell:
        label = "Upsell Painel" if "painel" in f else "Form de Upsell"
    else:
        label = "Form de Fechamentos"

    if from_ajuste:
        label += " · Ajustado"

    return label

# Cada linha usa seus próprios valores (sem agregar por church+data)
df_tabela = df_unique_hist[[
    "first_payment", "company_name", "tertiarygroup_id",
    "sales_owner", "sdr_owner", "products",
    "fonte", "conferencia_invalida",
    "value", "setup", "fyv", "upsell", "from_ajuste",
]].copy()
df_tabela = df_tabela.rename(columns={
    "value": "mrr",
    "setup": "setup_total",
    "fyv": "fyv_total",
})
df_tabela["fonte"] = df_tabela.apply(_origem, axis=1)
df_tabela = df_tabela[[
    "first_payment", "company_name", "tertiarygroup_id",
    "mrr", "setup_total", "fyv_total",
    "sales_owner", "sdr_owner", "products", "fonte",
    "conferencia_invalida",
]].copy()

df_tabela = df_tabela.rename(columns={
    "first_payment": "Data 1º Pgto",
    "company_name": "Igreja",
    "tertiarygroup_id": "Cód. Local",
    "mrr": "MRR",
    "setup_total": "Setup",
    "fyv_total": "FYV",
    "sales_owner": "Vendedor",
    "sdr_owner": "SDR",
    "products": "Produto",
    "fonte": "Origem",
    "conferencia_invalida": "Conferência Inválida",
})

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
    height=600,
    column_config={
        "Data 1º Pgto":         st.column_config.TextColumn(width="small"),
        "Igreja":               st.column_config.TextColumn(width="large"),
        "Cód. Local":           st.column_config.TextColumn(width="small"),
        "MRR":                  st.column_config.TextColumn(width="small"),
        "Setup":                st.column_config.TextColumn(width="small"),
        "FYV":                  st.column_config.TextColumn(width="small"),
        "Vendedor":             st.column_config.TextColumn(width="medium"),
        "SDR":                  st.column_config.TextColumn(width="medium"),
        "Produto":              st.column_config.TextColumn(width="medium"),
        "Origem":               st.column_config.TextColumn(width="medium"),
        "Conferência Inválida": st.column_config.TextColumn(width="large"),
    },
)

invalidos = df_tabela[df_tabela["Conferência Inválida"] != ""]
if not invalidos.empty:
    st.warning(f"{len(invalidos)} registro(s) com conferência inválida.")

with st.expander("Legenda — Origem", expanded=False):
    st.markdown("""
- **Form de Fechamentos** — cliente novo captado pelo processo comercial.
- **Upsell Painel** — cliente existente que fez upgrade pelo painel InChurch.
- **Form de Upsell** — cliente existente que solicitou upgrade via formulário.
- **· Ajustado** — dados corrigidos ou inseridos manualmente na planilha de ajustes.
""")

with st.expander("Legenda — Conferência Inválida", expanded=False):
    st.markdown("""
**Campos obrigatórios ausentes:**
- **Plano ausente** — o campo `plan` não foi preenchido. Sem plano não é possível calcular preço esperado nem classificar o deal.
- **Vendedor ausente** — o campo `sales_owner` não foi preenchido (exceto para upsells vindos do painel, que não têm vendedor atribuído). Sem vendedor não é possível computar comissão.
- **Sem Assinatura Superlógica** — o deal não está registrado como assinatura ativa no Superlógica. Normalmente indica que o vendedor não cadastrou os produtos após o fechamento.

**Preço fora de tabela (afeta comissão):**
- **Mensalidade fora de tabela** — o `value` (MRR) não bate com o esperado pela tabela de preços (plano-base + módulos). Considera se o deal contratou setup separadamente (cliente que paga setup ganha mensalidade com desconto). Aplica para **LITE** e **BASIC** (PRO tem mensalidade negociada).
- **Setup fora de range** — o `setup` (total contratado) está fora do intervalo mínimo–máximo aceitável para a faixa de membros + plano + produto. Aplica para **LITE** e **PRO**.
- **Setup < 10%** — o `first_setup_value` é menor que 10% do `setup` total. Cliente pagou entrada abaixo do mínimo aceito.

**Divergência entre sistemas:**
- **Divergência HubSpot** — o deal consta na tabela `hubspot_validacao` como divergente entre o que foi preenchido no HubSpot pelo vendedor e o que foi capturado pelo backend.

_Uma linha pode ter múltiplas flags separadas por `;`._
""")
