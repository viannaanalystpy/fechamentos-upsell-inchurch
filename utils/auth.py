# -*- coding: utf-8 -*-
"""
Autenticação Google OAuth 2.0 — restringe acesso a emails @inchurch.com.br
Sessão persistida em cookie (7 dias) para sobreviver a recarregamentos de página.
"""
import secrets as _secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import extra_streamlit_components as stx
import requests
import streamlit as st

ALLOWED_DOMAIN = "inchurch.com.br"
_COOKIE_EMAIL  = "ic_user_email"
_COOKIE_NAME   = "ic_user_name"
_COOKIE_DAYS   = 1


def _cookie_manager():
    return stx.CookieManager(key="ic_cookie_mgr")


def _secrets_google():
    g = st.secrets["google"]
    return g["client_id"], g["client_secret"], g["redirect_uri"]


def _build_auth_url(client_id: str, redirect_uri: str) -> str:
    state = _secrets.token_urlsafe(16)
    st.session_state["_oauth_state"] = state
    params = urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "online",
        "prompt":        "select_account",
    })
    return f"https://accounts.google.com/o/oauth2/auth?{params}"


def _exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        },
        timeout=15,
    )
    return r.json()


def _get_user_info(access_token: str) -> dict:
    r = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    return r.json()


def check_login():
    """
    Chama no topo de cada página.
    - Se autenticado (session ou cookie): renderiza badge e retorna.
    - Se callback do Google: valida, persiste em session + cookie.
    - Se não autenticado: exibe tela de login e chama st.stop().
    """
    cm = _cookie_manager()

    # 1. Já autenticado nesta sessão (mais rápido)
    if st.session_state.get("user_email"):
        _render_badge(cm)
        return

    # 2. Cookie persistido de sessão anterior
    email_cookie = cm.get(_COOKIE_EMAIL)
    name_cookie  = cm.get(_COOKIE_NAME)
    if email_cookie:
        st.session_state["user_email"] = email_cookie
        st.session_state["user_name"]  = name_cookie or email_cookie
        _render_badge(cm)
        return

    client_id, client_secret, redirect_uri = _secrets_google()

    # 3. Callback do Google (code na URL)
    params = st.query_params
    if "code" in params:
        with st.spinner("Autenticando..."):
            token = _exchange_code(params["code"], client_id, client_secret, redirect_uri)

        if "access_token" not in token:
            st.error("Falha na autenticação. Tente novamente.")
            st.query_params.clear()
            st.rerun()

        user  = _get_user_info(token["access_token"])
        email = user.get("email", "")

        if not email.lower().endswith(f"@{ALLOWED_DOMAIN}"):
            st.error(
                f"Acesso restrito a emails @{ALLOWED_DOMAIN}.\n\n"
                f"Você entrou com **{email}**."
            )
            st.query_params.clear()
            st.stop()

        name   = user.get("name", email)
        expiry = datetime.now() + timedelta(days=_COOKIE_DAYS)

        st.session_state["user_email"] = email
        st.session_state["user_name"]  = name
        cm.set(_COOKIE_EMAIL, email, expires_at=expiry)
        cm.set(_COOKIE_NAME,  name,  expires_at=expiry)
        st.query_params.clear()
        st.rerun()

    # 4. Tela de login
    auth_url = _build_auth_url(client_id, redirect_uri)

    st.markdown("""
    <div style="text-align:center; padding:120px 0 40px 0;">
      <h1 style="font-size:2.8rem; margin-bottom:8px; border:none; padding:0;">
        In<span style="color:#6eda2c">Church</span>
      </h1>
      <p style="color:#a0a0a0; font-size:1.1rem; margin:0;">
        Dashboard de Fechamento de Vendas
      </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        st.link_button("Entrar com Google", auth_url, use_container_width=True)

    st.stop()


def _render_badge(cm=None):
    name = st.session_state.get("user_name", st.session_state.get("user_email", ""))
    with st.sidebar:
        st.markdown(
            f"<p style='color:#a0a0a0; font-size:0.85rem; margin:0'>👤 {name}</p>",
            unsafe_allow_html=True,
        )
        if st.button("Sair", key="_logout_btn"):
            if cm:
                cm.delete(_COOKIE_EMAIL)
                cm.delete(_COOKIE_NAME)
            for k in ("user_email", "user_name", "_oauth_state"):
                st.session_state.pop(k, None)
            st.rerun()
