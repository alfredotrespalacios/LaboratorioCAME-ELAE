"""Módulo 6: consulta de la base mensual publicada y consulta temporal opcional."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from came.data.monthly_store import (
    load_default_metadata,
    load_default_monthly,
    series_options,
    to_wide,
)
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    show_warnings,
    unavailable,
)
from came.ui.loaders import xm_integrated


def _published_base() -> tuple[pd.DataFrame | None, dict[str, object]]:
    try:
        return load_default_monthly("COL"), load_default_metadata("COL")
    except FileNotFoundError as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error(f"El paquete mensual publicado no pudo leerse: {exc}")
    return None, {}


def _published_view(data: pd.DataFrame, metadata: dict[str, object]) -> None:
    options = series_options(data)
    st.caption(
        f"Actualización del paquete: {metadata.get('created_at_utc', 'sin JSON de metadatos')} · "
        f"último mes: {pd.to_datetime(data['datetime'], utc=True).max().date()}"
    )
    columns = st.columns(2)
    families = sorted(options["family"].dropna().astype(str).unique())
    levels = sorted(options["level"].dropna().astype(str).unique())
    selected_families = columns[0].multiselect(
        "Familias",
        families,
        default=families,
        key="integrated_default_families",
    )
    selected_levels = columns[1].multiselect(
        "Niveles",
        levels,
        default=[level for level in levels if level in {"Sistema", "Tecnología", "Calculada"}],
        key="integrated_default_levels",
    )
    visible = options[
        options["family"].isin(selected_families) & options["level"].isin(selected_levels)
    ].copy()
    labels = {
        row.series_id: f"{row.series_name} · {row.unit} · {row.level}"
        for row in visible.itertuples()
    }
    defaults = list(labels)[: min(5, len(labels))]
    selected = st.multiselect(
        "Series visibles",
        list(labels),
        default=defaults,
        format_func=lambda value: labels.get(value, value),
        max_selections=8,
        key="integrated_default_series",
    )
    if not selected:
        st.info("Seleccione al menos una serie mensual.")
        return
    selected_long = data[data["series_id"].isin(selected)].copy()
    first_month = pd.to_datetime(selected_long["datetime"], utc=True).min().date()
    last_month = pd.to_datetime(selected_long["datetime"], utc=True).max().date()
    period = st.slider(
        "Periodo visible",
        min_value=first_month,
        max_value=last_month,
        value=(first_month, last_month),
        key="integrated_default_period",
    )
    dates = pd.to_datetime(selected_long["datetime"], utc=True).dt.date
    selected_long = selected_long[dates.between(period[0], period[1])]
    height = min(max(260 * len(selected), 420), 1800)
    figure = px.line(
        selected_long,
        x="datetime",
        y="value",
        facet_row="series_name",
        facet_row_spacing=min(0.05, 0.25 / max(len(selected), 1)),
        title="Series mensuales publicadas",
        labels={"value": "Valor", "datetime": "Mes"},
        height=height,
    )
    figure.update_yaxes(matches=None, title_text="")
    figure.for_each_annotation(
        lambda annotation: annotation.update(text=annotation.text.split("=")[-1])
    )
    st.plotly_chart(figure, use_container_width=True)
    selected_wide = to_wide(selected_long, "COL")
    indicators = {
        "Meses visibles": selected_wide["datetime"].nunique(),
        "Series visibles": len(selected),
        "Series disponibles": len(options),
        "Cobertura del paquete": f"{data['datetime'].min().date()} a {data['datetime'].max().date()}",
    }
    show_indicators(indicators)
    tabs = st.tabs(["Tabla mensual", "Catálogo de series", "Formato largo"])
    tabs[0].dataframe(selected_wide, use_container_width=True, hide_index=True)
    tabs[1].dataframe(
        options[options["series_id"].isin(selected)], use_container_width=True, hide_index=True
    )
    tabs[2].dataframe(selected_long, use_container_width=True, hide_index=True)
    st.session_state["integrated_data"] = to_wide(data, "COL")
    export_and_collect(
        module="6. Base integrada",
        title="Base integrada mensual de Colombia",
        data=selected_wide,
        indicators=indicators,
        parameters={"Series": [labels[item] for item in selected], "Origen": "Parquet publicado"},
        methodology=[
            "Cada serie conserva en el catálogo su fuente, unidad y regla de agregación.",
            "El Parquet usa formato largo; esta tabla ancha se crea únicamente para la consulta.",
            "No se rellenan meses faltantes de manera silenciosa.",
        ],
        source="Paquete mensual validado de Colombia",
        unit="Una unidad por serie; consulte el catálogo",
        period=f"{period[0]} a {period[1]}",
        figure=figure,
        additional={
            "Series seleccionadas": options[options["series_id"].isin(selected)],
            "Datos formato largo": selected_long,
        },
        key="base_integrada_colombia_publicada",
    )


def _temporary_view(timeout: int) -> None:
    st.warning(
        "La consulta temporal sirve para revisar fuentes, pero no reemplaza el Parquet ni queda "
        "publicada cuando termina la sesión."
    )
    start, end = date_range_controls("integrated", months=60)
    include_macro = st.checkbox("Incluir TRM y ENSO", value=True, key="integrated_temp_macro")
    if st.button("Construir consulta temporal", type="primary", key="integrated_run"):
        try:
            with st.spinner("Integrando fuentes; un fallo parcial no elimina las demás series…"):
                result = xm_integrated(start, end, include_macro, timeout)
                st.session_state["integrated_result"] = result
                st.session_state["integrated_query"] = (start, end, include_macro)
        except Exception as exc:
            unavailable(exc, source="Fuentes integradas")
    result = st.session_state.get("integrated_result")
    if result is None:
        st.info("Pulse el botón solo cuando necesite contrastar una consulta directa.")
        return
    st.dataframe(result.status, use_container_width=True, hide_index=True)
    show_warnings(result.warnings)
    if result.data.empty:
        st.error("Ninguna variable estuvo disponible para el periodo.")
        return
    st.dataframe(result.data, use_container_width=True, hide_index=True)


def page_integrated(timeout: int) -> None:
    page_header(
        6,
        "Base integrada del mercado eléctrico",
        "Consulta, compara y descarga las series mensuales ya validadas.",
        "XM, datos.gov.co y NOAA",
    )
    st.info(
        "**Esta página es para consultar y analizar.** Para construir o actualizar los archivos "
        "abra **Mantenimiento → Mantenimiento de datos**. Streamlit no modifica GitHub automáticamente.",
        icon="📘",
    )
    mode = st.radio(
        "Origen de los datos",
        ["Base mensual publicada", "Consulta temporal a las fuentes"],
        horizontal=True,
        key="integrated_origin",
    )
    if mode == "Consulta temporal a las fuentes":
        _temporary_view(timeout)
        return
    data, metadata = _published_base()
    if data is None or data.empty:
        st.info(
            "Construya la primera versión en Mantenimiento de datos y publique los tres archivos "
            "en `datos_por_defecto/colombia/`."
        )
        return
    _published_view(data, metadata)
