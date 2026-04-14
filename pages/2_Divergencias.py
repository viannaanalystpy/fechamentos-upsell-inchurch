# -*- coding: utf-8 -*-
"""
Aba de Divergências — compara Google Sheets vs BigQuery por mês.
Mostra diagnóstico explicativo do gap antes da tabela de detalhes.
"""
import streamlit as st
import pandas as pd
from google.cloud import bigquery

st.set_page_config(
    page_title="Divergências | InChurch",
    page_icon="📊",
    layout="wide",
)

from utils.style import inject_css
from utils.data import fmt_brl
from utils.auth import check_login

inject_css()
check_login()

with st.sidebar:
    st.divider()
    if st.button("Atualizar dados", use_container_width=True, key="refresh_div_btn"):
        st.cache_data.clear()
        st.rerun()

st.markdown("<h1>Divergências <span>Sheets vs BQ</span></h1>", unsafe_allow_html=True)

# ── Constantes ────────────────────────────────────────────────────────────────
PROJECT      = "business-intelligence-467516"
FILE_DEFAULT = None  # sem arquivo padrão no cloud — usar upload abaixo
THRESHOLD    = 3.00

MODULOS_PRECOS = {
    79.80, 69.90, 59.90, 44.90, 34.90, 29.90, 24.90, 19.90,
    99.90, 149.90, 189.90, 239.90, 299.90, 379.90, 479.90,
    300.00, 240.00, 180.00, 120.00, 80.00, 64.90,
}

def e_modulo(diff, tolerancia=0.50):
    val = abs(diff)
    if val < 0.05:
        return False
    for preco in MODULOS_PRECOS:
        multiplo = round(val / preco)
        if multiplo >= 1 and abs(val - multiplo * preco) <= tolerancia:
            return True
    return False

def email_to_name(val):
    if pd.isna(val) or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if "@" in s:
        return " ".join(p.capitalize() for p in s.split("@")[0].split("."))
    return s

def parse_brl(series):
    return pd.to_numeric(
        series.astype(str).str.replace(",", ".").str.strip(), errors="coerce"
    ).fillna(0)

def fmt_diff(v):
    if pd.isna(v) or v == 0:
        return "—"
    s = f"R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"+{s}" if v > 0 else f"-{s}"

def safe_id(v):
    try:
        return int(v)
    except Exception:
        return v

# ── CSV ───────────────────────────────────────────────────────────────────────
with st.expander("Fonte de dados — Registro de Assinatura", expanded=True):
    uploaded = st.file_uploader(
        "Enviar arquivo do Registro de Assinatura (xlsx ou csv)",
        type=["xlsx", "xlsm", "csv"],
    )
    if not uploaded:
        st.info("Faça upload do arquivo copiainchurch.xlsx para carregar as divergências.")

def load_sheets(file_obj=None):
    if file_obj is not None:
        name = file_obj.name.lower()
        if name.endswith((".xlsx", ".xlsm")):
            return pd.read_excel(file_obj)
        return pd.read_csv(file_obj)
    st.warning("Nenhum arquivo carregado. Faça upload do Registro de Assinatura acima.")
    st.stop()

with st.spinner("Carregando Sheets..."):
    df_raw_sheets = load_sheets(uploaded)

# ── Processar Sheets ──────────────────────────────────────────────────────────
df_s = df_raw_sheets.copy()
def parse_dates(series):
    """Lida com datas em formato MM/DD/YYYY e DD/MM/YYYY misturados."""
    parsed = pd.to_datetime(series, errors="coerce")           # tenta inferir
    # fallback para datas que ficaram NaT — tenta formato DD/MM/YYYY
    mask_nat = parsed.isna()
    if mask_nat.any():
        parsed[mask_nat] = pd.to_datetime(
            series[mask_nat], format="%d/%m/%Y", errors="coerce"
        )
    return parsed

df_s["Data 1° Pagamento"] = parse_dates(df_s["Data 1° Pagamento"])
df_s = df_s[df_s["Data 1° Pagamento"] >= "2025-05-01"].copy()
df_s["company_id"]   = pd.to_numeric(df_s["Company ID"], errors="coerce").astype("Int64")
df_s = df_s[df_s["company_id"].notna()].copy()
df_s["mrr_sheets"]   = parse_brl(df_s["Valor Mensalidade"])
df_s["setup_sheets"] = parse_brl(df_s["Valor Setup"])
df_s["vend_sheets"]  = df_s.get("SR Owner",      pd.Series(dtype=str)).fillna("").astype(str).str.strip()
df_s["sdr_sheets"]   = df_s.get("SDR Owner",     pd.Series(dtype=str)).fillna("").astype(str).str.strip()
df_s["prod_sheets"]  = df_s.get("Qual Produto",  pd.Series(dtype=str)).fillna("").astype(str).str.strip()
df_s["mes"]          = df_s["Data 1° Pagamento"].dt.to_period("M")

# ── Seletor de mês ────────────────────────────────────────────────────────────
meses_disponiveis = sorted(df_s["mes"].dropna().unique(), reverse=True)
meses_labels = {str(m): pd.Period(m).strftime("%B/%Y").capitalize() for m in meses_disponiveis}

col_mes, col_info_mes = st.columns([1, 3])
with col_mes:
    mes_sel_str = st.selectbox(
        "Mês de referência",
        options=list(meses_labels.keys()),
        format_func=lambda x: meses_labels[x],
    )
mes_sel = pd.Period(mes_sel_str)
mes_inicio = mes_sel.start_time.date()
mes_fim    = mes_sel.end_time.date()

# ── Filtrar Sheets pelo mês ───────────────────────────────────────────────────
df_s_mes = df_s[df_s["mes"] == mes_sel].copy()
df_sheets_mes = df_s_mes.groupby("company_id").agg(
    mrr_sheets=("mrr_sheets", "sum"),
    setup_sheets=("setup_sheets", "sum"),
    company_name=("Company Name", "first"),
    Data_1_Pagamento=("Data 1° Pagamento", "min"),
    vend_sheets=("vend_sheets", "first"),
    sdr_sheets=("sdr_sheets", "first"),
    prod_sheets=("prod_sheets", "first"),
).reset_index()

# ── BQ: todos os deals do mês (não só os IDs do Sheets) ──────────────────────
@st.cache_resource
def _bq_client():
    try:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return bigquery.Client(project=PROJECT, credentials=creds)
    except (KeyError, FileNotFoundError):
        return bigquery.Client(project=PROJECT)

@st.cache_data(ttl=1800, show_spinner=False)
def load_bq_mes(mes_inicio_str, mes_fim_str):
    client = _bq_client()
    query = f"""
    WITH ranked AS (
      SELECT
        CAST(tertiarygroup_id AS INT64) AS tid,
        company_name,
        fonte,
        CAST(value  AS FLOAT64) AS value,
        CAST(setup  AS FLOAT64) AS setup,
        sales_owner, sdr_owner, products,
        DATE(first_payment) AS first_payment,
        CASE fonte
          WHEN 'SPLGC'               THEN 0
          WHEN 'Fechamentos Backend' THEN 1
          WHEN 'HubSpot'             THEN 2
          WHEN 'Ajustes manuais'     THEN 3
          ELSE 99
        END AS rank
      FROM `{PROJECT}.Fechamento_vendas.Fechamentos_com_ajustes`
      WHERE DATE(first_payment) BETWEEN '{mes_inicio_str}' AND '{mes_fim_str}'
    ),
    mr AS (SELECT tid, MIN(rank) AS mr FROM ranked GROUP BY tid),
    dd AS (SELECT r.* FROM ranked r JOIN mr m ON r.tid=m.tid AND r.rank=m.mr)
    SELECT
      tid,
      MIN(company_name)            AS company_name,
      MIN(first_payment)           AS first_payment,
      ROUND(SUM(value), 2)         AS mrr_bq,
      ROUND(SUM(setup), 2)         AS setup_bq,
      MIN(sales_owner)             AS sales_owner,
      MIN(sdr_owner)               AS sdr_owner,
      MIN(products)                AS products,
      MIN(fonte)                   AS fonte
    FROM dd GROUP BY tid
    """
    df = client.query(query).to_dataframe()
    df["tid"] = df["tid"].astype("Int64")
    return df

with st.spinner("Consultando BigQuery..."):
    df_bq_mes = load_bq_mes(str(mes_inicio), str(mes_fim))

df_bq_mes["sales_owner_fmt"] = df_bq_mes["sales_owner"].apply(email_to_name)
df_bq_mes["sdr_owner_fmt"]   = df_bq_mes["sdr_owner"].apply(email_to_name)

# ── Join outer ────────────────────────────────────────────────────────────────
df = df_sheets_mes.merge(
    df_bq_mes, left_on="company_id", right_on="tid", how="outer"
)
df["mrr_bq"]      = df["mrr_bq"].fillna(0)
df["setup_bq"]    = df["setup_bq"].fillna(0)
df["mrr_sheets"]  = df["mrr_sheets"].fillna(0)
df["setup_sheets"]= df["setup_sheets"].fillna(0)
df["diff_mrr"]    = (df["mrr_bq"] - df["mrr_sheets"]).round(2)
df["diff_setup"]  = (df["setup_bq"] - df["setup_sheets"]).round(2)

# ── Classificar ───────────────────────────────────────────────────────────────
mask_ambos = df["tid"].notna() & df["company_id"].notna()

df["modulo_diff"] = df.apply(
    lambda r: e_modulo(r["diff_mrr"]) and abs(r["diff_setup"]) <= 0.05, axis=1
)
mask_sem_bq     = df["tid"].isna()                           # Sheets mas não no BQ
mask_sem_sheets = df["company_id"].isna()                    # BQ mas não no Sheets
mask_divergente = (
    mask_ambos & ~df["modulo_diff"]
    & ((df["diff_mrr"].abs() > THRESHOLD) | (df["diff_setup"].abs() > THRESHOLD))
)
mask_modulo  = mask_ambos & df["modulo_diff"] & (df["diff_mrr"].abs() > 0.05)
mask_prorata = (
    mask_ambos & ~mask_divergente & ~mask_modulo
    & ((df["diff_mrr"].abs() > 0.05) | (df["diff_setup"].abs() > 0.05))
)
mask_ok = mask_ambos & ~mask_divergente & ~mask_modulo & ~mask_prorata

# ── Totais ────────────────────────────────────────────────────────────────────
total_sheets = df["mrr_sheets"].sum()
total_bq     = df["mrr_bq"].sum()
gap_total    = round(total_bq - total_sheets, 2)

# Contribuições de cada causa para o gap
contrib_sem_sheets = df[mask_sem_sheets]["mrr_bq"].sum()       # BQ sem Sheets → inflam BQ
contrib_sem_bq     = df[mask_sem_bq]["mrr_sheets"].sum()       # Sheets sem BQ → deflam BQ
contrib_div_pos    = df[mask_divergente & (df["diff_mrr"] > 0)]["diff_mrr"].sum()
contrib_div_neg    = df[mask_divergente & (df["diff_mrr"] < 0)]["diff_mrr"].sum()
contrib_modulo     = df[mask_modulo]["diff_mrr"].sum()

# ── SEÇÃO 1: Diagnóstico do gap ───────────────────────────────────────────────
st.divider()
mes_label = mes_sel.strftime("%B/%Y").capitalize()
st.markdown(f"## Diagnóstico — {mes_label}")

# Linha de resumo
gap_color = "#ff6b6b" if gap_total > 0 else "#6eda2c" if gap_total < 0 else "#a0a0a0"
gap_sinal = "a mais" if gap_total > 0 else "a menos"
if abs(gap_total) < 0.05:
    st.success(f"**Streamlit e Sheets estão alinhados para {mes_label}.**")
else:
    st.markdown(
        f"<div style='background:#1e1e1e;border-left:4px solid {gap_color};"
        f"padding:16px 20px;border-radius:6px;margin-bottom:16px'>"
        f"<span style='font-size:1.1rem'>O Streamlit mostra </span>"
        f"<span style='font-size:1.3rem;font-weight:700;color:{gap_color}'>{fmt_diff(gap_total)}</span>"
        f"<span style='font-size:1.1rem'> {gap_sinal} que o Sheets em {mes_label}.</span><br>"
        f"<span style='color:#a0a0a0;font-size:0.9rem'>"
        f"Sheets: {fmt_brl(total_sheets, 2)} &nbsp;|&nbsp; BQ: {fmt_brl(total_bq, 2)}"
        f"</span></div>",
        unsafe_allow_html=True,
    )

# Causas
causas = []

if abs(contrib_sem_sheets) > 0.05:
    n = mask_sem_sheets.sum()
    ids_lista = sorted([safe_id(r["tid"]) for _, r in df[mask_sem_sheets].iterrows()])
    causas.append({
        "icone": "📋",
        "titulo": f"{n} deal(s) no SPLGC não cadastrado(s) no Sheets",
        "valor": contrib_sem_sheets,
        "sinal": "+",
        "cor": "#ff6b6b",
        "detalhe": f"IDs: {', '.join(str(i) for i in ids_lista)} — o comercial ainda não registrou na planilha.",
    })

if abs(contrib_sem_bq) > 0.05:
    n = mask_sem_bq.sum()
    ids_lista = sorted([safe_id(r["company_id"]) for _, r in df[mask_sem_bq].iterrows()])
    causas.append({
        "icone": "❌",
        "titulo": f"{n} deal(s) no Sheets não encontrado(s) no BQ",
        "valor": -contrib_sem_bq,
        "sinal": "-",
        "cor": "#ffd166",
        "detalhe": f"IDs: {', '.join(str(i) for i in ids_lista)} — pipeline não capturou esses deals.",
    })

if abs(contrib_div_pos) > 0.05:
    n = (mask_divergente & (df["diff_mrr"] > 0)).sum()
    causas.append({
        "icone": "⬆️",
        "titulo": f"{n} deal(s) com MRR maior no BQ que no Sheets",
        "valor": contrib_div_pos,
        "sinal": "+",
        "cor": "#ff6b6b",
        "detalhe": "BQ tem valor superior ao registrado pelo comercial — ver detalhes abaixo.",
    })

if abs(contrib_div_neg) > 0.05:
    n = (mask_divergente & (df["diff_mrr"] < 0)).sum()
    causas.append({
        "icone": "⬇️",
        "titulo": f"{n} deal(s) com MRR menor no BQ que no Sheets",
        "valor": contrib_div_neg,
        "sinal": "-",
        "cor": "#ffd166",
        "detalhe": "BQ tem valor inferior ao registrado pelo comercial — ver detalhes abaixo.",
    })

if abs(contrib_modulo) > 0.05:
    n = mask_modulo.sum()
    causas.append({
        "icone": "🔧",
        "titulo": f"{n} deal(s) com módulo adicional no BQ (Kids, Journey, etc.)",
        "valor": contrib_modulo,
        "sinal": "+" if contrib_modulo > 0 else "-",
        "cor": "#a0a0a0",
        "detalhe": "SPLGC cobra módulos que o Sheets não registra — geralmente correto.",
    })

if causas:
    for c in causas:
        st.markdown(
            f"<div style='background:#1a1a1a;border:1px solid #2a2a2a;"
            f"padding:12px 16px;border-radius:6px;margin-bottom:8px;"
            f"display:flex;align-items:flex-start;gap:12px'>"
            f"<span style='font-size:1.3rem'>{c['icone']}</span>"
            f"<div style='flex:1'>"
            f"<div style='font-weight:600'>{c['titulo']}</div>"
            f"<div style='color:#a0a0a0;font-size:0.85rem;margin-top:2px'>{c['detalhe']}</div>"
            f"</div>"
            f"<div style='font-weight:700;color:{c['cor']};white-space:nowrap;font-size:1.05rem'>"
            f"{c['sinal']}{fmt_brl(abs(c['valor']), 2)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
elif abs(gap_total) >= 0.05:
    st.info("Gap causado apenas por pro-rata / arredondamento (≤ R$3 por deal).")

# ── SEÇÃO 2: KPIs ─────────────────────────────────────────────────────────────
st.divider()
n_ok   = mask_ok.sum()
n_div  = mask_divergente.sum()
n_mod  = mask_modulo.sum()
n_pr   = mask_prorata.sum()
n_ausb = mask_sem_bq.sum()
n_auss = mask_sem_sheets.sum()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("✅ Batem", n_ok)
k2.metric("⚠️ Divergência", n_div)
k3.metric("🔧 Módulo extra", n_mod)
k4.metric("〰️ Pro-rata", n_pr)
k5.metric("❌ Só no Sheets", n_ausb)
k6.metric("📋 Só no BQ", n_auss)

# ── SEÇÃO 3: Tabela de detalhes ───────────────────────────────────────────────
st.divider()
st.markdown("### Detalhes por deal")

cat_options = {}
if n_div:  cat_options[f"⚠️ Divergências reais ({n_div})"]        = "divergente"
if n_auss: cat_options[f"📋 Só no BQ — não cadastrado ({n_auss})"] = "sem_sheets"
if n_ausb: cat_options[f"❌ Só no Sheets — ausente no BQ ({n_ausb})"] = "sem_bq"
if n_mod:  cat_options[f"🔧 Módulos adicionais ({n_mod})"]          = "modulo"
if n_pr:   cat_options[f"〰️ Pro-rata / arredondamento ({n_pr})"]    = "prorata"
if n_ok:   cat_options[f"✅ Valores corretos ({n_ok})"]             = "ok"

if not cat_options:
    st.success("Nenhuma divergência encontrada para este mês!")
    st.stop()

cat_sel = st.selectbox("Categoria", options=list(cat_options.keys()), index=0)
cat_key = cat_options[cat_sel]

MASK_MAP = {
    "divergente":  mask_divergente,
    "modulo":      mask_modulo,
    "prorata":     mask_prorata,
    "ok":          mask_ok,
    "sem_bq":      mask_sem_bq,
    "sem_sheets":  mask_sem_sheets,
}
df_view = df[MASK_MAP[cat_key]].copy()

if df_view.empty:
    st.success("Nenhum registro nesta categoria.")
    st.stop()

# Atribuição textual
def diff_text(a, b):
    a, b = str(a).strip(), str(b).strip()
    if a == b or (a in ("", "nan") and b in ("", "nan")):
        return ""
    if a in ("", "nan"): return f"BQ: {b}"
    if b in ("", "nan"): return f"Sheets: {a}"
    return f"Sheets: {a} → BQ: {b}"

df_view["diff_vend"] = df_view.apply(lambda r: diff_text(r.get("vend_sheets",""), r.get("sales_owner_fmt","")), axis=1)
df_view["diff_sdr"]  = df_view.apply(lambda r: diff_text(r.get("sdr_sheets",""),  r.get("sdr_owner_fmt","")),   axis=1)
df_view["diff_prod"] = df_view.apply(lambda r: diff_text(r.get("prod_sheets",""), r.get("products","")),         axis=1)

rows = []
for _, r in df_view.sort_values("diff_mrr", key=abs, ascending=False).iterrows():
    cid  = r.get("company_id")
    tid  = r.get("tid")
    nome_sh = r.get("company_name_x") or r.get("company_name") or ""
    nome_bq = r.get("company_name_y") or r.get("company_name") or ""
    nome = (nome_sh if str(nome_sh) not in ("nan","","None") else nome_bq) or "—"
    dt   = r.get("Data_1_Pagamento") or r.get("first_payment")
    try:
        dt_str = pd.Timestamp(dt).strftime("%d/%m/%Y")
    except Exception:
        dt_str = "—"
    rows.append({
        "ID":           safe_id(cid) if pd.notna(cid) else safe_id(tid),
        "Igreja":       str(nome)[:50],
        "1º Pgto":      dt_str,
        "MRR Sheets":   fmt_brl(r["mrr_sheets"],  decimals=2),
        "MRR BQ":       fmt_brl(r["mrr_bq"],      decimals=2),
        "Δ MRR":        fmt_diff(r["diff_mrr"]),
        "Setup Sheets": fmt_brl(r["setup_sheets"], decimals=2),
        "Setup BQ":     fmt_brl(r["setup_bq"],     decimals=2),
        "Δ Setup":      fmt_diff(r["diff_setup"]),
        "Vendedor":     r.get("diff_vend") or "✅",
        "SDR":          r.get("diff_sdr")  or "✅",
        "Produto":      r.get("diff_prod") or "✅",
        "Fonte BQ":     r.get("fonte", "—"),
    })

df_display = pd.DataFrame(rows)

def highlight_row(row):
    styles = [""] * len(row)
    cols   = list(row.index)
    for col in ("Δ MRR", "Δ Setup"):
        if col in cols and row[col] != "—":
            styles[cols.index(col)] = "color: #ff6b6b; font-weight: bold"
    for col in ("Vendedor", "SDR", "Produto"):
        if col in cols and row[col] not in ("✅", "", "—"):
            styles[cols.index(col)] = "color: #ffd166; font-weight: 500"
    return styles

st.dataframe(
    df_display.style.apply(highlight_row, axis=1),
    use_container_width=True,
    hide_index=True,
    height=min(38 * len(df_display) + 60, 600),
)

# Expanders para divergências reais
if cat_key == "divergente":
    st.markdown("#### Detalhes")
    for _, r in df_view.sort_values("diff_mrr", key=abs, ascending=False).iterrows():
        cid  = r.get("company_id")
        nome_sh = r.get("company_name_x") or r.get("company_name") or "—"
        nome_bq = r.get("company_name_y") or ""
        nome = str(nome_sh) if str(nome_sh) not in ("nan","","None") else str(nome_bq)
        with st.expander(f"ID {safe_id(cid)} — {nome}"):
            c1, c2, c3 = st.columns(3)
            c1.metric("MRR Sheets", fmt_brl(r["mrr_sheets"], decimals=2))
            c1.metric("MRR BQ",     fmt_brl(r["mrr_bq"],     decimals=2))
            c1.metric("Δ MRR",      fmt_diff(r["diff_mrr"]))
            c2.metric("Setup Sheets", fmt_brl(r["setup_sheets"], decimals=2))
            c2.metric("Setup BQ",     fmt_brl(r["setup_bq"],     decimals=2))
            c2.metric("Δ Setup",      fmt_diff(r["diff_setup"]))
            c3.markdown(f"**Vendedor**  \n{r.get('diff_vend') or '✅ Igual'}")
            c3.markdown(f"**SDR**  \n{r.get('diff_sdr') or '✅ Igual'}")
            c3.markdown(f"**Produto**  \n{r.get('diff_prod') or '✅ Igual'}")
            c3.markdown(f"**Fonte BQ:** `{r.get('fonte', '—')}`")
