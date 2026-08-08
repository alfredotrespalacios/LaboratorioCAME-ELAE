"""Componentes de presentación, autenticación, exportación y canasta."""

from __future__ import annotations

import hmac
import json
from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from came.config import APP_SUBTITLE, APP_TITLE, APP_VERSION, AppSettings
from came.exports import build_excel, build_pdf, plotly_png
from came.report import make_package

HISTORY_START = date(2000, 1, 1)


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        html, body, .stApp, [data-testid="stAppViewContainer"] {
          background: #F7F9FC; color: #101828;
        }
        .stApp h1, .stApp h2, .stApp h3, .stApp h4,
        .stApp p, .stApp li, .stApp label,
        [data-testid="stWidgetLabel"] p,
        [data-testid="stMarkdownContainer"] { color: #101828; }
        [data-testid="stSidebar"] { background: #18324A; }
        [data-testid="stSidebar"] *, [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label { color: #F7F9FC !important; }
        div[data-baseweb="input"], div[data-baseweb="select"] > div,
        div[data-baseweb="textarea"], [data-testid="stDateInput"] > div > div {
          background: #FFFFFF !important; border-color: #98A2B3 !important;
        }
        input, textarea, div[data-baseweb="select"] span {
          color: #101828 !important; -webkit-text-fill-color: #101828 !important;
        }
        input::placeholder, textarea::placeholder {
          color: #667085 !important; -webkit-text-fill-color: #667085 !important;
        }
        [data-testid="stMetric"] {
          background: white; border: 1px solid #E4E7EC; border-radius: .65rem;
          padding: .75rem 1rem; box-shadow: 0 1px 2px rgba(16,24,40,.04);
        }
        [data-testid="stMetricLabel"] *, [data-testid="stMetricValue"] * {
          color: #101828 !important;
        }
        div[data-testid="stExpander"], [data-testid="stDataFrame"],
        [data-testid="stTable"] { background: white; border-radius: .55rem; }
        [data-testid="stAlert"] * { color: #101828 !important; }
        button[kind="primary"] { color: #FFFFFF !important; }
        .came-kicker { color:#C69214; font-weight:700; letter-spacing:.08em; font-size:.78rem; }
        .came-source { color:#667085; font-size:.84rem; }
        .came-guide dt { color:#18324A; font-weight:700; margin-top:.45rem; }
        .came-guide dd { color:#344054; margin-left:0; margin-bottom:.45rem; }
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


def passwords_match(candidate: str, expected: object) -> bool:
    """Compara contraseñas de forma segura y compatible con texto Unicode."""

    return hmac.compare_digest(
        candidate.encode("utf-8"),
        str(expected).encode("utf-8"),
    )


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
        st.session_state["authenticated"] = passwords_match(password, settings.access_password)
        if st.session_state["authenticated"]:
            st.rerun()
        st.error("Contraseña incorrecta.")
    return False


def date_range_controls(
    key: str,
    months: int = 60,
    *,
    min_date: date = HISTORY_START,
) -> tuple[date, date]:
    """Selector explícito desde 2000 con cinco años iniciales y acceso a toda la historia."""

    end_default = date.today() - timedelta(days=1)
    start_default = max(min_date, end_default - timedelta(days=round(months * 30.44)))
    start_key = f"{key}_start"
    end_key = f"{key}_end"
    if start_key not in st.session_state:
        st.session_state[start_key] = start_default
    if end_key not in st.session_state:
        st.session_state[end_key] = end_default
    if st.button(
        "Toda la historia",
        key=f"{key}_all_history",
        help=f"Ajusta el periodo desde {min_date:%d/%m/%Y} hasta ayer.",
    ):
        st.session_state[start_key] = min_date
        st.session_state[end_key] = end_default
    left, right = st.columns(2)
    start = left.date_input(
        "Fecha inicial",
        key=start_key,
        min_value=min_date,
        max_value=end_default,
        help="Primer día que se solicitará a la fuente oficial.",
    )
    end = right.date_input(
        "Fecha final",
        key=end_key,
        min_value=min_date,
        max_value=end_default,
        help="Último día incluido en la consulta; de forma predeterminada es ayer.",
    )
    if start > end:
        st.error("La fecha inicial no puede ser posterior a la final.")
    return start, end


def parameter_guide(items: dict[str, str]) -> None:
    """Explica de forma homogénea qué debe ingresar o elegir el usuario."""

    with st.expander("¿Qué se solicita en cada parámetro?"):
        body = "".join(
            f"<dt>{label}</dt><dd>{description}</dd>" for label, description in items.items()
        )
        st.markdown(f'<dl class="came-guide">{body}</dl>', unsafe_allow_html=True)


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
    """Entrega archivos homogéneos y registra automáticamente el resultado en el informe."""

    warnings = warnings or []
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
        additional_tables=additional,
        package_id=key,
    ).to_dict()
    packages = st.session_state.setdefault("report_packages", [])
    position = next(
        (index for index, item in enumerate(packages) if item.get("package_id") == key),
        None,
    )
    if position is None:
        packages.append(package)
    else:
        packages[position] = package

    excel: bytes | None = None
    pdf: bytes | None = None
    excel_error = ""
    pdf_error = ""
    try:
        excel = build_excel(
            data=data,
            summary=indicators,
            parameters=parameters,
            methodology=methodology,
            coverage={"Periodo": period, "Fuente": source, "Unidad": unit},
            additional=additional,
        )
    except Exception as exc:
        excel_error = str(exc)
    try:
        pdf = build_pdf(
            title=title,
            subtitle=f"{period} · {source}",
            indicators=indicators,
            tables={"Datos": data},
            methodology=methodology,
            warnings=warnings,
            figures=[("Resultado gráfico", plotly_png(figure))] if figure is not None else None,
        )
    except Exception as exc:
        pdf_error = str(exc)

    col_excel, col_pdf, col_json = st.columns(3)
    if excel is not None:
        col_excel.download_button(
            "Descargar Excel",
            excel,
            file_name=f"{key}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key}_xlsx",
            use_container_width=True,
        )
    else:
        col_excel.warning(f"Excel no disponible: {excel_error}")
    if pdf is not None:
        col_pdf.download_button(
            "Descargar PDF",
            pdf,
            file_name=f"{key}.pdf",
            mime="application/pdf",
            key=f"{key}_pdf",
            use_container_width=True,
        )
    else:
        col_pdf.warning(f"PDF no disponible: {pdf_error}")
    col_json.download_button(
        "Descargar resultado JSON",
        json.dumps(package, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        file_name=f"{key}.json",
        mime="application/json",
        key=f"{key}_json",
        use_container_width=True,
    )
    st.caption("Este resultado ya quedó guardado automáticamente para el informe ejecutivo.")


def unavailable(exc: Exception, *, source: str) -> None:
    st.error(f"{source} no pudo entregar este resultado: {exc}")
    st.caption("No se sustituyó la fuente por datos simulados. Ajuste el periodo o reintente.")
