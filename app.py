import streamlit as st

st.set_page_config(
    page_title="Fechamentos | InChurch",
    page_icon="📊",
    layout="wide",
)

from utils.style import inject_css
from utils.auth import check_login

inject_css()
check_login()

pg = st.navigation([
    st.Page("pages/1_Fechamentos.py", title="Fechamentos", icon="📊")
])
pg.run()
