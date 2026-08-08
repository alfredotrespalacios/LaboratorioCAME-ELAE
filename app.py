"""Entrada única de Streamlit para los 19 módulos del Laboratorio CAME."""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from came.ui.components import (  # noqa: E402
    app_header,
    apply_theme,
    authentication_gate,
    settings_from_streamlit,
)
from came.ui.pages_analysis import page_modeling, page_portfolio, page_volatility  # noqa: E402
from came.ui.pages_colombia import (  # noqa: E402
    page_balance,
    page_demand,
    page_generation_resource,
    page_generation_technology,
    page_integrated,
    page_offer_curve,
    page_spot,
    page_xm_explorer,
)
from came.ui.pages_other import page_chile, page_spain  # noqa: E402
from came.ui.pages_report import page_activity, page_report  # noqa: E402

st.set_page_config(
    page_title="Laboratorio CAME · ELAE",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()
settings = settings_from_streamlit()
if not authentication_gate(settings):
    st.stop()

app_header()
st.sidebar.caption("Herramienta académica · resultados no sustituyen análisis operativo o regulatorio.")

navigation = st.navigation(
    {
        "Colombia": [
            st.Page(partial(page_spot, settings.request_timeout_seconds), title="1. Precio de bolsa", url_path="precio-bolsa"),
            st.Page(partial(page_demand, settings.request_timeout_seconds), title="2. Demanda nacional", url_path="demanda"),
            st.Page(partial(page_generation_technology, settings.request_timeout_seconds), title="3. Generación por tecnología", url_path="generacion-tecnologia"),
            st.Page(partial(page_generation_resource, settings.request_timeout_seconds), title="4. Generación por recurso", url_path="generacion-recurso"),
            st.Page(partial(page_xm_explorer, settings.request_timeout_seconds), title="5. Explorador XM", url_path="explorador-xm"),
            st.Page(partial(page_integrated, settings.request_timeout_seconds), title="6. Base integrada", url_path="base-integrada"),
            st.Page(partial(page_balance, settings.request_timeout_seconds), title="7. Balance energético", url_path="balance"),
            st.Page(partial(page_offer_curve, settings.request_timeout_seconds), title="8. Curva de oferta", url_path="curva-oferta"),
        ],
        "Otros mercados": [
            st.Page(partial(page_spain, settings.request_timeout_seconds), title="9. España", url_path="espana"),
            st.Page(
                partial(
                    page_chile,
                    settings.request_timeout_seconds,
                    settings.chile_costs_url,
                    settings.chile_demand_url,
                ),
                title="10. Chile",
                url_path="chile",
            ),
        ],
        "Análisis y modelación": [
            st.Page(page_modeling, title="11. Modelación y pronóstico", url_path="modelacion"),
            st.Page(page_volatility, title="12. SARIMA–GARCH", url_path="sarima-garch"),
        ],
        "Estructuración de portafolios": [
            st.Page(page_portfolio, title="13. Monte Carlo", url_path="portafolio"),
        ],
        "Actividades académicas": [
            st.Page(partial(page_activity, 14), title="14. Actividad 1", url_path="actividad-1"),
            st.Page(partial(page_activity, 15), title="15. Actividad 2", url_path="actividad-2"),
            st.Page(partial(page_activity, 16), title="16. Actividad 3", url_path="actividad-3"),
            st.Page(partial(page_activity, 17), title="17. Actividad 4", url_path="actividad-4"),
            st.Page(partial(page_activity, 18), title="18. Actividad 5", url_path="actividad-5"),
        ],
        "Informe": [
            st.Page(page_report, title="19. Informe ejecutivo", url_path="informe"),
        ],
    }
)
navigation.run()
