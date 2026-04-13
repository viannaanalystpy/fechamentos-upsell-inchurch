import streamlit as st

PALETTE = [
    "#6eda2c",  # 0 — Verde primário
    "#ffffff",  # 1 — Branco
    "#57d124",  # 2 — Verde secundário
    "#a0a0a0",  # 3 — Cinza médio
    "#4c4c4c",  # 4 — Cinza escuro
    "#292929",  # 5 — Borda dark
    "#8ae650",  # 6 — Verde claro
    "#3ba811",  # 7 — Verde profundo
    "#cccccc",  # 8 — Cinza claro
    "#111111",  # 9 — Quase preto
]

FONTE_COLORS = {
    "SPLGC":            "#6eda2c",
    "HubSpot":          "#ffffff",
    "Ajustes manuais":  "#a0a0a0",
}

PRODUTO_COLORS = {
    "app":     "#6eda2c",
    "kids":    "#ffffff",
    "journey": "#8ae650",
    "site":    "#a0a0a0",
    "outros":  "#4c4c4c",
}

PLAN_COLORS = {
    "pro":          "#6eda2c",
    "lite":         "#ffffff",
    "starter":      "#a0a0a0",
    "basic":        "#8ae650",
    "igreja filha": "#4c4c4c",
    "squad":        "#f0a500",
    "outros":       "#292929",
}


def inject_css():
    st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
    html, body, [class*="css"], .stApp, button, input, select, textarea {
        font-family: 'Outfit', sans-serif !important;
    }
    :root {
        --bg-main:    #000000;
        --bg-card:    #121212;
        --bg-hover:   #1E1E1E;
        --border:     #292929;
        --border-hi:  #4c4c4c;
        --accent-1:   #6eda2c;
        --accent-2:   #57d124;
        --text-main:  #ffffff;
        --text-muted: #a0a0a0;
    }
    .stApp { background: var(--bg-main) !important; }
    section[data-testid="stSidebar"] {
        background: var(--bg-card) !important;
        border-right: 1px solid var(--border);
    }
    div[data-testid="stAppViewBlockContainer"] { padding-top: 1.5rem !important; }
    h1 {
        font-size: 2rem; font-weight: 700; color: #ffffff;
        margin-bottom: 4px; letter-spacing: -0.02em;
    }
    h1 span { color: #6eda2c; }
    h2, h3 {
        font-size: 1.1rem; font-weight: 600; color: #a0a0a0;
        letter-spacing: 0.08em; text-transform: uppercase;
        padding: 0 0 12px 0;
        margin: 24px 0 16px 0;
    }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #161616, #121212);
        border: 1px solid #2a2a2a;
        border-top: 3px solid var(--accent-1);
        border-radius: 14px;
        padding: 22px 24px;
        min-height: 140px;
        height: 140px;
        transition: all 0.25s ease;
    }
    [data-testid="stMetric"]:hover {
        border-top-color: var(--accent-2);
        background: linear-gradient(145deg, #1a1a1a, #141414);
        box-shadow: 0 8px 28px rgba(110, 218, 44, 0.1);
        transform: translateY(-3px);
    }
    [data-testid="stMetricLabel"] > div {
        font-size: 0.8rem; font-weight: 500; color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.06em;
    }
    [data-testid="stMetricValue"] > div {
        font-size: 2.1rem; font-weight: 700; color: var(--accent-1);
    }
    div[data-baseweb="tab-list"] {
        background: var(--bg-card); border-radius: 12px;
        padding: 5px; border: 1px solid var(--border); gap: 4px;
    }
    button[data-baseweb="tab"] {
        background: transparent; border-radius: 8px;
        color: var(--text-muted); font-weight: 500; font-size: 0.88rem;
        padding: 8px 18px; transition: all 0.2s ease;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: rgba(110, 218, 44, 0.12);
        border: 1px solid rgba(110, 218, 44, 0.28);
        color: var(--accent-1); font-weight: 600;
    }
    div[data-baseweb="tab-highlight"],
    div[data-baseweb="tab-border"] { display: none !important; }
    div[data-baseweb="select"] > div {
        background: var(--bg-card); border: 1px solid var(--border);
        border-radius: 10px; min-height: 44px; color: var(--text-main);
    }
    div[data-baseweb="select"] > div:hover {
        border-color: var(--accent-1);
        box-shadow: 0 4px 12px rgba(110, 218, 44, 0.1);
    }
    [data-testid="stSidebarNavLink"] { border-radius: 8px; transition: all 0.2s ease; }
    [data-testid="stSidebarNavLink"]:hover { background: rgba(110, 218, 44, 0.06) !important; }
    [data-testid="stSidebarNavLink"][aria-current="page"] {
        background: rgba(110, 218, 44, 0.1) !important;
        border-left: 2px solid var(--accent-1) !important;
        color: var(--accent-1) !important;
    }
    ::-webkit-scrollbar { width: 7px; height: 7px; }
    ::-webkit-scrollbar-track { background: var(--bg-main); }
    ::-webkit-scrollbar-thumb { background: #4c4c4c; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #6c6c6c; }
    </style>
    """, unsafe_allow_html=True)


def chart_layout(fig, height=380, legend_bottom=False):
    legend_cfg = dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit", size=12, color="#a0a0a0")
    )
    if legend_bottom:
        legend_cfg.update(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5)
    fig.update_layout(
        height=height,
        template="plotly_dark",
        margin=dict(l=4, r=4, t=32, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=13),
        legend=legend_cfg,
        xaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1,
                   zeroline=False, title="", type="category"),
        yaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1,
                   zeroline=False, title=""),
        hoverlabel=dict(bgcolor="#141414", bordercolor="#292929", font_size=13,
                        font_family="Outfit, sans-serif", font_color="#ffffff"),
    )
    return fig
