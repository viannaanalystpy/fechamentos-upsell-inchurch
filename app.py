import streamlit as st

st.set_page_config(
    page_title="Fechamento de Vendas | InChurch",
    page_icon="📊",
    layout="wide",
)

from utils.style import inject_css
from utils.auth import check_login

inject_css()
check_login()

st.markdown("""
    <div style="text-align:center; padding: 80px 0 40px 0;">
      <h1 style="font-size:2.8rem; margin-bottom:8px; border:none; padding:0;">
        In<span style="color:#6eda2c">Church</span>
      </h1>
      <p style="color:#a0a0a0; font-size:1.1rem; margin:0;">Dashboard de Fechamento de Vendas</p>
    </div>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.page_link("pages/1_Fechamentos.py", label="Abrir Dashboard", icon="📊", use_container_width=True)
