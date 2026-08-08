"""Componentes de presentación, autenticación, exportación y canasta."""

from __future__ import annotations

import hmac
from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from came.config import APP_SUBTITLE, APP_TITLE, APP_VERSION, AppSettings
from came.exports import build_excel, build_pdf, plotly_png
from came.report import make_package


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #F7F9FC; }
        [data-testid="stSidebar"] { background: #18324A; }
        [data-testid="stSidebar"] * { color: #F7F9FC; }
        [data-testid="stMetric"] {
          background: white; border: 1px solid #E4E7EC; border-radius: .65rem;
          padding: .75rem 1rem; box-shadow: 0 1px 2px rgba(16,24,40,.04);
        }
        div[data-testid="stExpander"] { background: white; border-radius: .55rem; }
        .came-kicker { color:#C69214; font-weight:700; letter-spacing:.08em; font-size:.78rem; }
        .came-source { color:#667085; font-size:.84rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def app_header() -> None:
    st.markdown('<div class="came-kicker">ELAE · MERCADOS ELÉCTRICOS</div>', unsafe_allow_html=True)
    st.title(APP_TITLE)
    st.caption(f"{APP_SUBTITLE} · versión {APP_VERSION}")


def page_header(number: int, title: str, description: str, source: str | None = None) -> None:
    st.header(f"{number}. {title}")
    st.write(description)
    if source:
        st.markdown(f'<div class="came-source">Fuente: {source}</div>', unsafe_allow_html=True)


def settings_from_streamlit() -> AppSettings:
    try:
        mapping = dict(st.secrets)
    except Exception:
        mapping = {}
    return AppSettings.from_mapping(mapping)


def authentication_gate(settings: AppSettings) -> bool:
    """Bloquea por defecto y revoca sesiones cuando cambia ACCESS_VERSION."""

    if not settings.authentication_required:
        st.sidebar.success("Modo local de desarrollo")
        return True
    if not settings.access_password:
        st.error(
            "La aplicación está cerrada porque falta ACCESS_PASSWORD. "
            "Configúrela en los secretos de Streamlit junto con ACCESS_VERSION."
        )
        return False
    if st.session_state.get("auth_version") != settings.access_version:
        st.session_state["authenticated"] = False
        st.session_state["auth_version"] = settings.access_version
    if st.session_state.get("authenticated"):
        return True
    with st.form("came_login", clear_on_submit=True):
        st.subheader("Acceso al laboratorio")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Ingresar", type="primary")
    if submitted:
        st.session_state["authenticated"] = hmac.compare_digest(
            password, settings.access_password
        )
        if st.session_state["authenticated"]:
            st.rerun()
        st.error("Contraseña incorrecta.")
    return False


def date_range_controls(key: str, months: int = 24) -> tuple[date, date]:
    end_default = date.today() - timedelta(days=1)
    start_default = end_default - timedelta(days=round(months * 30.44))
    left, right = st.columns(2)
    start = left.date_input("Fecha inicial", value=start_default, key=f"{key}_start")
    end = right.date_input("Fecha final", value=end_default, key=f"{key}_end")
    if start > end:
        st.error("La fecha inicial no puede ser posterior a la final.")
    return start, end


def show_indicators(indicators: dict[str, Any], precision: int = 2) -> None:
    visible = [(key, value) for key, value in indicators.items() if value is not None]
    if not visible:
        return
    columns = st.columns(min(len(visible), 5))
    for index, (key, value) in enumerate(visible):
        if isinstance(value, (float, int)):
            display = f"{value:,.{precision}f}"
        else:
            display = str(value)
        columns[index % len(columns)].metric(str(key).replace("_", " ").title(), display)


def show_warnings(warnings: list[str] | None) -> None:
    for warning in dict.fromkeys(warnings or []):
        st.warning(warning)


def export_and_collect(
    *,
    module: str,
    title: str,
    data: pd.DataFrame,
    indicators: dict[str, Any],
    parameters: dict[str, Any],
    methodology: list[str],
    source: str,
    unit: str,
    period: str,
    warnings: list[str] | None = None,
    figure: Any = None,
    additional: dict[str, Any] | None = None,
    key: str,
) -> None:
    """Entrega archivos homogéneos y permite enviar el resultado al informe final."""

    warnings = warnings or []
    excel = build_excel(
        data=data,
        summary=indicators,
        parameters=parameters,
        methodology=methodology,
        coverage={"Periodo": period, "Fuente": source, "Unidad": unit},
        additional=additional,
    )
    pdf = build_pdf(
        title=title,
        subtitle=f"{period} · {source}",
        indicators=indicators,
        tables={"Datos": data},
        methodology=methodology,
        warnings=warnings,
        figures=[("Resultado gráfico", plotly_png(figure))] if figure is not None else None,
    )
    col_excel, col_pdf, col_report = st.columns(3)
    col_excel.download_button(
        "Descargar Excel",
        excel,
        file_name=f"{key}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_xlsx",
        use_container_width=True,
    )
    col_pdf.download_button(
        "Descargar PDF",
        pdf,
        file_name=f"{key}.pdf",
        mime="application/pdf",
        key=f"{key}_pdf",
        use_container_width=True,
    )
    if col_report.button("Añadir al informe", key=f"{key}_basket", use_container_width=True):
        package = make_package(
            module=module,
            title=title,
            period=period,
            source=source,
            unit=unit,
            configuration=parameters,
            indicators=indicators,
            methodology=methodology,
            warnings=warnings,
            table=data,
        )
        st.session_state.setdefault("report_packages", []).append(package.to_dict())
        st.toast("Resultado añadido al informe ejecutivo.", icon="✅")


def unavailable(exc: Exception, *, source: str) -> None:
    st.error(f"{source} no pudo entregar este resultado: {exc}")
    st.caption("No se sustituyó la fuente por datos simulados. Ajuste el periodo o reintente.")

