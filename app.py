"""Entrada única de Streamlit para la introducción, 19 módulos y mantenimiento."""

from __future__ import annotations

import sys
from functools import partial
from importlib import import_module
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Laboratorio CAME · ELAE",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Community Cloud conserva la versión de Python elegida al crear el despliegue. El proyecto se
# valida con Python 3.12; detenerse aquí evita iniciar una descarga histórica en una instancia que
# luego falle durante una recarga con módulos parcialmente importados.
if sys.version_info[:2] != (3, 12):
    st.error(
        "Entorno incompatible: esta instalación usa Python "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}. "
        "Laboratorio CAME 1.4.1 requiere Python 3.12. Cambie la versión del despliegue antes de "
        "construir o actualizar bases históricas."
    )
    st.stop()

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


def _run_page(module_name: str, function_name: str, *args: object) -> None:
    """Carga únicamente el módulo seleccionado por el usuario."""

    module = import_module(f"came.ui.pages.{module_name}")
    function = getattr(module, function_name)
    function(*args)


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
                partial(_run_page, "introduction", "page_introduction"),
                title="Introducción",
                url_path="introduccion",
                default=True,
            ),
        ],
        "Colombia": [
            st.Page(
                partial(
                    _run_page,
                    "price_spot",
                    "page_spot",
                    settings.request_timeout_seconds,
                ),
                title="1. Precio de bolsa",
                url_path="precio-bolsa",
            ),
            st.Page(
                partial(
                    _run_page,
                    "demand_national",
                    "page_demand",
                    settings.request_timeout_seconds,
                ),
                title="2. Demanda nacional",
                url_path="demanda",
            ),
            st.Page(
                partial(
                    _run_page,
                    "generation_technology",
                    "page_generation_technology",
                    settings.request_timeout_seconds,
                ),
                title="3. Generación por tecnología",
                url_path="generacion-tecnologia",
            ),
            st.Page(
                partial(
                    _run_page,
                    "generation_resource",
                    "page_generation_resource",
                    settings.request_timeout_seconds,
                ),
                title="4. Generación por recurso",
                url_path="generacion-recurso",
            ),
            st.Page(
                partial(
                    _run_page,
                    "xm_explorer",
                    "page_xm_explorer",
                    settings.request_timeout_seconds,
                ),
                title="5. Explorador XM",
                url_path="explorador-xm",
            ),
            st.Page(
                partial(
                    _run_page,
                    "base_integrated",
                    "page_integrated",
                    settings.request_timeout_seconds,
                ),
                title="6. Base integrada",
                url_path="base-integrada",
            ),
            st.Page(
                partial(
                    _run_page,
                    "energy_balance",
                    "page_balance",
                    settings.request_timeout_seconds,
                ),
                title="7. Balance energético",
                url_path="balance",
            ),
            st.Page(
                partial(
                    _run_page,
                    "offer_curve",
                    "page_offer_curve",
                    settings.request_timeout_seconds,
                ),
                title="8. Curva de oferta",
                url_path="curva-oferta",
            ),
        ],
        "Otros mercados": [
            st.Page(
                partial(
                    _run_page,
                    "spain",
                    "page_spain",
                    settings.request_timeout_seconds,
                ),
                title="9. España",
                url_path="espana",
            ),
            st.Page(
                partial(
                    _run_page,
                    "chile",
                    "page_chile",
                    settings.request_timeout_seconds,
                    settings.chile_costs_url,
                    settings.chile_demand_url,
                ),
                title="10. Chile",
                url_path="chile",
            ),
        ],
        "Análisis y modelación": [
            st.Page(
                partial(_run_page, "modeling_forecast", "page_modeling"),
                title="11. Modelación y pronóstico",
                url_path="modelacion",
            ),
            st.Page(
                partial(_run_page, "sarima_garch", "page_volatility"),
                title="12. SARIMA–GARCH",
                url_path="sarima-garch",
            ),
        ],
        "Estructuración de portafolios": [
            st.Page(
                partial(_run_page, "portfolio_montecarlo", "page_portfolio"),
                title="13. Cálculo rápido de portafolios",
                url_path="portafolio",
            ),
        ],
        "Casos de estudio": [
            st.Page(
                partial(_run_page, "case_studies", "page_case_study", 14),
                title="14. Caso de estudio 1",
                url_path="caso-estudio-1",
            ),
            st.Page(
                partial(_run_page, "case_studies", "page_case_study", 15),
                title="15. Caso de estudio 2",
                url_path="caso-estudio-2",
            ),
            st.Page(
                partial(_run_page, "case_studies", "page_case_study", 16),
                title="16. Caso de estudio 3",
                url_path="caso-estudio-3",
            ),
            st.Page(
                partial(_run_page, "case_studies", "page_case_study", 17),
                title="17. Caso de estudio 4",
                url_path="caso-estudio-4",
            ),
            st.Page(
                partial(_run_page, "case_studies", "page_case_study", 18),
                title="18. Caso de estudio 5",
                url_path="caso-estudio-5",
            ),
        ],
        "Informe": [
            st.Page(
                partial(_run_page, "executive_report", "page_report"),
                title="19. Informe ejecutivo",
                url_path="informe",
            ),
        ],
        "Mantenimiento": [
            st.Page(
                partial(
                    _run_page,
                    "data_maintenance",
                    "page_data_maintenance",
                    settings.request_timeout_seconds,
                ),
                title="Mantenimiento de datos",
                url_path="mantenimiento-datos",
            ),
        ],
    }
)
navigation.run()
