"""Entrada única de Streamlit para la introducción, 19 módulos y mantenimiento."""

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
from came.ui.pages.base_integrated import page_integrated  # noqa: E402
from came.ui.pages.case_studies import page_case_study  # noqa: E402
from came.ui.pages.chile import page_chile  # noqa: E402
from came.ui.pages.data_maintenance import page_data_maintenance  # noqa: E402
from came.ui.pages.demand_national import page_demand  # noqa: E402
from came.ui.pages.energy_balance import page_balance  # noqa: E402
from came.ui.pages.executive_report import page_report  # noqa: E402
from came.ui.pages.generation_resource import page_generation_resource  # noqa: E402
from came.ui.pages.generation_technology import page_generation_technology  # noqa: E402
from came.ui.pages.introduction import page_introduction  # noqa: E402
from came.ui.pages.modeling_forecast import page_modeling  # noqa: E402
from came.ui.pages.offer_curve import page_offer_curve  # noqa: E402
from came.ui.pages.portfolio_montecarlo import page_portfolio  # noqa: E402
from came.ui.pages.price_spot import page_spot  # noqa: E402
from came.ui.pages.sarima_garch import page_volatility  # noqa: E402
from came.ui.pages.spain import page_spain  # noqa: E402
from came.ui.pages.xm_explorer import page_xm_explorer  # noqa: E402

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
st.sidebar.caption(
    "Herramienta académica · resultados no sustituyen análisis operativo o regulatorio."
)

navigation = st.navigation(
    {
        "Inicio": [
            st.Page(
                page_introduction,
                title="Introducción",
                url_path="introduccion",
                default=True,
            ),
        ],
        "Colombia": [
            st.Page(
                partial(page_spot, settings.request_timeout_seconds),
                title="1. Precio de bolsa",
                url_path="precio-bolsa",
            ),
            st.Page(
                partial(page_demand, settings.request_timeout_seconds),
                title="2. Demanda nacional",
                url_path="demanda",
            ),
            st.Page(
                partial(page_generation_technology, settings.request_timeout_seconds),
                title="3. Generación por tecnología",
                url_path="generacion-tecnologia",
            ),
            st.Page(
                partial(page_generation_resource, settings.request_timeout_seconds),
                title="4. Generación por recurso",
                url_path="generacion-recurso",
            ),
            st.Page(
                partial(page_xm_explorer, settings.request_timeout_seconds),
                title="5. Explorador XM",
                url_path="explorador-xm",
            ),
            st.Page(
                partial(page_integrated, settings.request_timeout_seconds),
                title="6. Base integrada",
                url_path="base-integrada",
            ),
            st.Page(
                partial(page_balance, settings.request_timeout_seconds),
                title="7. Balance energético",
                url_path="balance",
            ),
            st.Page(
                partial(page_offer_curve, settings.request_timeout_seconds),
                title="8. Curva de oferta",
                url_path="curva-oferta",
            ),
        ],
        "Otros mercados": [
            st.Page(
                partial(page_spain, settings.request_timeout_seconds),
                title="9. España",
                url_path="espana",
            ),
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
        "Casos de estudio": [
            st.Page(
                partial(page_case_study, 14),
                title="14. Caso de estudio 1",
                url_path="caso-estudio-1",
            ),
            st.Page(
                partial(page_case_study, 15),
                title="15. Caso de estudio 2",
                url_path="caso-estudio-2",
            ),
            st.Page(
                partial(page_case_study, 16),
                title="16. Caso de estudio 3",
                url_path="caso-estudio-3",
            ),
            st.Page(
                partial(page_case_study, 17),
                title="17. Caso de estudio 4",
                url_path="caso-estudio-4",
            ),
            st.Page(
                partial(page_case_study, 18),
                title="18. Caso de estudio 5",
                url_path="caso-estudio-5",
            ),
        ],
        "Informe": [
            st.Page(page_report, title="19. Informe ejecutivo", url_path="informe"),
        ],
        "Mantenimiento": [
            st.Page(
                partial(page_data_maintenance, settings.request_timeout_seconds),
                title="Mantenimiento de datos",
                url_path="mantenimiento-datos",
            ),
        ],
    }
)
navigation.run()
