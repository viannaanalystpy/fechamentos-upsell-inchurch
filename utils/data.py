import unicodedata

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

MESES_ABREV_PT = {
    1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez',
}


def fmt_mes_abrev_pt(ts) -> str:
    """Retorna mês abreviado em PT-BR no formato 'Abr/26'."""
    ts = pd.Timestamp(ts)
    return f"{MESES_ABREV_PT[ts.month]}/{ts.strftime('%y')}"


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


@st.cache_data(ttl=300)
def load_precos_tables() -> dict:
    """Carrega tabelas de referência de preço pra validações de conferência.

    Retorna dict com:
      - 'produtos': {(plano, produto, faixa, filha, upsell, setup): valor}
         - Em caso de duplicata (Lite 1-100 new tem 2 valores), pega MIN (bate com doc oficial)
      - 'modulos': {(faixa, modulo): valor}
      - 'setup_range': {(plano, produto, faixa): (minimo, maximo)}
      - 'hubspot_divergencias': set de tertiarygroup_id (STRING)
    """
    client = _bq_client()

    # precos_produtos — dedup via MIN pra contornar duplicatas na planilha origem
    df_prod = client.query(f"""
        SELECT plano, produto, faixa_membros, filha, upsell, setup, MIN(valor) AS valor
        FROM `{PROJECT}.{DATASET}.precos_produtos`
        GROUP BY plano, produto, faixa_membros, filha, upsell, setup
    """).to_dataframe()
    produtos = {
        (r.plano, r.produto, r.faixa_membros, bool(r.filha), bool(r.upsell), bool(r.setup)): float(r.valor)
        for r in df_prod.itertuples(index=False) if pd.notna(r.valor)
    }

    df_mod = client.query(f"""
        SELECT DISTINCT faixa_membros, modulo, valor
        FROM `{PROJECT}.{DATASET}.precos_modulos`
    """).to_dataframe()
    modulos = {
        (r.faixa_membros if pd.notna(r.faixa_membros) else None, r.modulo): float(r.valor)
        for r in df_mod.itertuples(index=False) if pd.notna(r.valor)
    }

    df_setup = client.query(f"""
        SELECT plano, produto, faixa_membros, minimo, maximo
        FROM `{PROJECT}.{DATASET}.precos_setup`
    """).to_dataframe()
    setup_range = {
        (r.plano, r.produto, r.faixa_membros): (float(r.minimo), float(r.maximo))
        for r in df_setup.itertuples(index=False) if pd.notna(r.minimo) and pd.notna(r.maximo)
    }

    df_hub = client.query(f"""
        SELECT DISTINCT CAST(tertiarygroup_id AS STRING) AS tg
        FROM `{PROJECT}.{DATASET}.hubspot_validacao`
        WHERE hubspot_status IN ('divergente', 'não está na hubspot')
    """).to_dataframe()
    hubspot_divergencias = set(df_hub["tg"].tolist()) if not df_hub.empty else set()

    return {
        "produtos": produtos,
        "modulos": modulos,
        "setup_range": setup_range,
        "hubspot_divergencias": hubspot_divergencias,
    }


def _derivar_produto_base(products_str) -> str | None:
    """Mapeia a coluna `products` do deal para o produto-base da tabela de preços.
    Retorna 'app + site' se tem ambos, 'app ou site' se tem só um, senão None.
    """
    if pd.isna(products_str) or not products_str:
        return None
    tokens = [t.strip().lower() for t in str(products_str).split(",")]
    tem_app = "app" in tokens
    tem_site = "site" in tokens
    if tem_app and tem_site:
        return "app + site"
    if tem_app or tem_site:
        return "app ou site"
    return None


def _extrair_modulos(products_str) -> list[str]:
    """Extrai tokens de módulo (kids, journey, smart_store) da coluna `products`."""
    if pd.isna(products_str) or not products_str:
        return []
    tokens = [t.strip().lower() for t in str(products_str).split(",")]
    return [t for t in tokens if t in ("kids", "journey", "smart_store")]


def _plano_lookup(plan: str) -> tuple[str, bool] | None:
    """Mapeia o plan do deal para (plano_na_tabela, flag_filha). None se não aplicável."""
    if pd.isna(plan) or not plan:
        return None
    p = str(plan).strip()
    if p == "Igreja Filha":
        return ("Pro", True)
    if p in ("Pro", "Lite", "Basic"):
        return (p, False)
    return None  # STARTER ou desconhecidos: sem validação


@st.cache_data(ttl=300)
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
            f.member_range,
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

        # Normaliza email ou nome puro para forma única (ex: thalles.borges@inchurch.com.br
        # e "Thálles Borges" → ambos viram "Thalles Borges"). Sem isso, filtros e
        # agregações por vendedor duplicam o mesmo responsável.
        def email_to_name(val):
            if pd.isna(val) or val == "":
                return val
            s = str(val)
            if "@" in s:
                s = s.split("@")[0].replace(".", " ")
            s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
            return " ".join(p.capitalize() for p in s.split())

        df["sales_owner"] = df["sales_owner"].apply(email_to_name)
        df["sdr_owner"]   = df["sdr_owner"].apply(email_to_name)

        # Carrega tabelas de referência de preço 1x antes do loop.
        # Fallback seguro: se falhar (tabela inacessível, schema mudou, etc), segue só com flags antigas.
        try:
            precos = load_precos_tables()
        except Exception as e:
            st.warning(f"Não foi possível carregar tabelas de preço — flags de 'Preço Fora de Tabela' desativadas. Erro: {e}")
            precos = {"produtos": {}, "modulos": {}, "setup_range": {}, "hubspot_divergencias": set()}



        # Conferência inválida: campos obrigatórios ausentes + preço fora de tabela
        problemas = []
        for _, row in df.iterrows():
            erros = []
            if str(row.get("fonte", "")) == "Sem Assinatura Superlógica":
                erros.append("Sem Assinatura Superlógica")
            if pd.isna(row["plan"]) or row["plan"] == "":
                erros.append("Plano ausente")
            is_upsell_painel = "painel" in str(row.get("fonte", "")).lower()
            if not is_upsell_painel and (pd.isna(row["sales_owner"]) or row["sales_owner"] == ""):
                erros.append("Vendedor ausente")
            if (
                not pd.isna(row["setup"]) and row["setup"] > 0
                and not pd.isna(row["first_setup_value"])
                and row["first_setup_value"] > 0
                and row["first_setup_value"] < row["setup"] * 0.10
            ):
                erros.append("Setup < 10%")

            # --- Conferências de "Preço Fora de Tabela" ---
            # Só aplica a partir de abril/2026 — jan-mar validados manualmente pelo gestor.
            primeiro_pagamento = row.get("first_payment")
            validar_preco = (
                pd.notna(primeiro_pagamento)
                and pd.Timestamp(primeiro_pagamento) >= pd.Timestamp("2026-04-01")
            )

            plano_info = _plano_lookup(row.get("plan"))
            faixa = row.get("member_range") if "member_range" in row else None
            setup_total = row.get("setup")
            if validar_preco and plano_info and faixa and not pd.isna(faixa):
                plano, eh_filha = plano_info
                produto = _derivar_produto_base(row.get("products"))
                upsell_flag = bool(row.get("upsell")) if pd.notna(row.get("upsell")) else False

                # Mensalidade fora de tabela (só Lite/Basic — Pro tem mensalidade negociada)
                if plano in ("Lite", "Basic"):
                    produto_key = produto if plano == "Lite" else None  # Basic usa produto NULL
                    mensalidade_esperada = (
                        precos["produtos"].get((plano, produto_key, faixa, eh_filha, upsell_flag, False))
                    )
                    if mensalidade_esperada is not None and not pd.isna(row["value"]):
                        modulos_do_deal = _extrair_modulos(row.get("products"))
                        def _preco_modulo(mod):
                            v = precos["modulos"].get((faixa, mod))
                            return v if v is not None else precos["modulos"].get((None, mod), 0.0)
                        mensalidade_esperada_total = mensalidade_esperada + sum(
                            _preco_modulo(m) for m in modulos_do_deal
                        )
                        if abs(row["value"] - mensalidade_esperada_total) > 0.01:
                            erros.append("Mensalidade fora de tabela")

                # Setup fora de range — valida o setup TOTAL contra precos_setup (min-max).
                # Pro: setup é obrigatório → valida mesmo quando ausente (0/null fora do range).
                # Lite: setup é opcional → só valida quando efetivamente contratado (> 0).
                if plano in ("Lite", "Pro") and produto:
                    rng = precos["setup_range"].get((plano, produto, faixa))
                    if rng is not None:
                        minimo, maximo = rng
                        setup_val = float(setup_total) if not pd.isna(setup_total) else 0.0
                        if plano == "Pro" or setup_val > 0:
                            if setup_val < minimo or setup_val > maximo:
                                erros.append("Setup fora de range")

            # Divergência HubSpot — não aplica para Upsell Painel (não passa por HubSpot)
            tg = str(row.get("tertiarygroup_id", ""))
            fonte_str = str(row.get("fonte", "")).lower()
            if (
                tg
                and tg in precos["hubspot_divergencias"]
                and "upsell painel" not in fonte_str
            ):
                erros.append("Divergência HubSpot")

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
    df["mes_fmt"] = df[date_col].apply(fmt_mes_abrev_pt)
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


def no_data(label="Dados nao disponiveis"):
    st.info(label)
