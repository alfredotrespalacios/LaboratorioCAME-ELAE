"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

import streamlit as st

from came.analytics.aggregation import summary_indicators
from came.ui.charts import line
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    show_warnings,
    unavailable,
)
from came.ui.loaders import (
    xm_catalog,
    xm_explore,
)


def page_xm_explorer(timeout: int) -> None:
    page_header(
        5,
        "Explorador libre de variables de XM",
        "Consulta el catálogo vivo sin depender de una lista fija incorporada en la aplicación.",
        "API pública XM",
    )
    if st.button("Actualizar catálogo", type="primary", key="catalog_run"):
        try:
            st.session_state["xm_catalog"] = xm_catalog(timeout)
        except Exception as exc:
            unavailable(exc, source="XM")
    catalog = st.session_state.get("xm_catalog")
    if catalog is None:
        st.info("Cargue el catálogo vivo de métricas de XM.")
        return
    search = st.text_input("Buscar por id, nombre, entidad o unidad")
    visible = catalog.copy()
    if search:
        mask = (
            visible.astype(str)
            .apply(lambda col: col.str.contains(search, case=False, na=False))
            .any(axis=1)
        )
        visible = visible[mask]
    st.dataframe(visible, use_container_width=True, hide_index=True)
    supported = visible[visible["Type"].astype(str) != "ListsEntities"].copy()
    labels = {
        f"{row.MetricId} · {row.MetricName} · {row.Entity} · {row.MetricUnits}": (
            row.MetricId,
            row.Entity,
        )
        for row in supported.itertuples()
    }
    if not labels:
        st.warning("El filtro no dejó métricas temporales consultables.")
        return
    selected_label = st.selectbox("Métrica", list(labels))
    start, end = date_range_controls("explorer", months=3)
    if st.button("Consultar métrica", key="explorer_run"):
        metric, entity = labels[selected_label]
        try:
            with st.spinner("Consultando métrica…"):
                st.session_state["explorer_result"] = xm_explore(
                    metric, entity, start, end, timeout
                )
                st.session_state["explorer_query"] = (metric, entity, start, end)
        except Exception as exc:
            unavailable(exc, source="XM")
    result = st.session_state.get("explorer_result")
    if result is None:
        return
    data = result.data
    indicators = summary_indicators(data)
    show_indicators(indicators)
    fig = line(data, "value", title=result.meta.variable_name, unit=result.meta.unit)
    st.plotly_chart(fig, use_container_width=True)
    show_warnings(result.warnings)
    metric, entity, query_start, query_end = st.session_state["explorer_query"]
    export_and_collect(
        module="5. Explorador XM",
        title=result.meta.variable_name,
        data=data,
        indicators=indicators,
        parameters={"MetricId": metric, "Entidad": entity},
        methodology=[result.meta.methodology],
        source="XM",
        unit=result.meta.unit,
        period=f"{query_start} a {query_end}",
        warnings=result.warnings,
        figure=fig,
        key="explorador_xm",
    )
