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

st.switch_page("pages/1_Fechamentos.py")
