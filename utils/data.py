import pandas as pd
import streamlit as st
from google.cloud import bigquery
from pathlib import Path

PROJECT = "business-intelligence-467516"
DATASET = "Fechamento_vendas"
TABELA  = "Fechamentos_com_ajustes"

# Caminho relativo ao pacote utils/ → sobe um nível para raiz do projeto
_BASE = Path(__file__).parent.parent
METAS_CSV = str(_BASE / "data" / "metas.csv")

MESES_PT = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
    'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
}


@st.cache_resource
def _bq_client() -> bigquery.Client:
    try:
        # Streamlit Cloud: usa service account do st.secrets
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return bigquery.Client(project=PROJECT, credentials=creds)
    except (KeyError, FileNotFoundError):
        # Local: usa Application Default Credentials (gcloud auth)
        return bigquery.Client(project=PROJECT)


@st.cache_data(ttl=3600)
def load_fechamentos() -> pd.DataFrame:
    client = _bq_client()
    query = f"""
        SELECT
            f.id,
            f.hubspot_deal,
            f.tertiarygroup_id,
            f.superlogica_id,
            f.fonte,
            f.products,
            f.plan,
            f.sales_owner,
            f.sdr_owner,
            f.channel,
            CAST(f.value AS FLOAT64)            AS value,
            CAST(f.setup AS FLOAT64)            AS setup,
            CAST(f.first_setup_value AS FLOAT64) AS first_setup_value,
            DATE(f.first_payment)               AS first_payment,
            COALESCE(f.company_name, c.st_nome_sac) AS company_name,
            f.upsell,
            f.new_deal,
            DATE_TRUNC(DATE(f.first_payment), MONTH) AS mes,
            (aj.id IS NOT NULL) AS from_ajuste
        FROM `{PROJECT}.{DATASET}.{TABELA}` f
        LEFT JOIN `{PROJECT}.Splgc.splgc-clientes-inchurch` c
          ON CAST(f.superlogica_id AS STRING) = CAST(c.id_sacado_sac AS STRING)
        LEFT JOIN `{PROJECT}.{DATASET}.ajustes_fechamentos` aj
          ON f.id = aj.id
        WHERE f.first_payment >= '2026-01-01'
        ORDER BY first_payment
    """
    df = client.query(query).to_dataframe()
    if not df.empty:
        df["mes"]               = pd.to_datetime(df["mes"])
        df["first_payment"]     = pd.to_datetime(df["first_payment"])
        df["value"]             = pd.to_numeric(df["value"], errors="coerce").fillna(0)
        df["setup"]             = pd.to_numeric(df["setup"], errors="coerce").fillna(0)
        df["first_setup_value"] = pd.to_numeric(df["first_setup_value"], errors="coerce").fillna(0)
        # FYV calculado em Python para evitar arredondamento do BQ
        df["fyv"]               = df["value"] * 12 + df["setup"]
        df["receita_total"]     = df["value"] + df["setup"]

        # Remove prefixo de deal HubSpot do nome da igreja (ex: "S1490-T26167// Igreja X" → "Igreja X")
        df["company_name"] = df["company_name"].str.replace(
            r'^[A-Z0-9\-]+//\s*', '', regex=True
        )

        # Converte email para nome legível (ex: thalles.borges@inchurch.com.br → Thalles Borges)
        def email_to_name(val):
            if pd.isna(val) or val == "":
                return val
            if "@" in str(val):
                return " ".join(p.capitalize() for p in str(val).split("@")[0].split("."))
            return val

        df["sales_owner"] = df["sales_owner"].apply(email_to_name)
        df["sdr_owner"]   = df["sdr_owner"].apply(email_to_name)

        # Conferência inválida: campos obrigatórios ausentes
        problemas = []
        for _, row in df.iterrows():
            erros = []
            if pd.isna(row["plan"]) or row["plan"] == "":
                erros.append("Plano ausente")
            if pd.isna(row["sales_owner"]) or row["sales_owner"] == "":
                erros.append("Vendedor ausente")
            if (
                not pd.isna(row["setup"]) and row["setup"] > 0
                and not pd.isna(row["first_setup_value"])
                and row["first_setup_value"] > 0
                and row["first_setup_value"] < row["setup"] * 0.10
            ):
                erros.append("Setup < 10%")
            problemas.append("; ".join(erros) if erros else "")
        df["conferencia_invalida"] = problemas

        # Propagar alertas: se qualquer linha de um church/mês tem alerta,
        # mostrar também na linha de prioridade (evita perder alertas do backend
        # quando um ajuste manual sem first_setup_value ganha a deduplicação)
        def _merge_erros(series):
            todos = set()
            for s in series:
                if s:
                    todos.update(e.strip() for e in s.split(";") if e.strip())
            return "; ".join(sorted(todos))

        invalido_map = (
            df.groupby(["tertiarygroup_id", "mes"])["conferencia_invalida"]
            .apply(_merge_erros)
            .to_dict()
        )
        df["conferencia_invalida"] = df.apply(
            lambda r: invalido_map.get((r["tertiarygroup_id"], r["mes"]), ""), axis=1
        )

    return df


@st.cache_data(ttl=86400)
def load_metas() -> pd.DataFrame:
    def parse_mes(s):
        try:
            partes = str(s).lower().split('/')
            mes_num = MESES_PT.get(partes[0].strip())
            ano = int(partes[1].strip())
            ano = 2000 + ano if ano < 100 else ano
            if mes_num:
                return pd.Timestamp(year=ano, month=mes_num, day=1)
        except Exception:
            pass
        return pd.NaT

    def parse_valor(s):
        try:
            return float(str(s).replace('.', '').replace(',', '.'))
        except Exception:
            return 0.0

    df = pd.read_csv(METAS_CSV)
    df = df[df["Cargo"].str.contains("Gestor", case=False, na=False)].copy()
    df["mes"]        = df["Mês"].apply(parse_mes)
    df["meta_valor"] = df["Meta 1"].apply(parse_valor)
    df = df.dropna(subset=["mes"])
    return df.groupby("mes")["meta_valor"].sum().reset_index(name="meta")


# ---------- helpers ----------

@st.cache_data(ttl=3600)
def load_ultima_atualizacao() -> str:
    try:
        from datetime import timezone, timedelta
        client = _bq_client()
        table = client.get_table(f"{PROJECT}.{DATASET}.{TABELA}")
        ts = table.modified.astimezone(timezone(timedelta(hours=-3)))
        return ts.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "—"


def fmt_brl(value, decimals=0) -> str:
    s = f"{value:,.{decimals}f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def last_val(df, col, date_col="mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-1] if len(ordered) >= 1 else None


def prev_val(df, col, date_col="mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-2] if len(ordered) >= 2 else None


def delta_str(curr, prev, fmt="+,.0f", suffix="") -> str | None:
    if curr is None or prev is None:
        return None
    diff = curr - prev
    try:
        return f"{diff:{fmt}}{suffix}"
    except Exception:
        return f"{diff:+.2f}{suffix}"


def mes_fmt_ordered(df, date_col="mes"):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


def no_data(label="Dados nao disponiveis"):
    st.info(label)
