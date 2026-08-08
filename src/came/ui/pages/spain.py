"""Módulos 9–10: España y Chile."""

from __future__ import annotations

from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from came.analytics.aggregation import summary_indicators
from came.config import REDATA_SYSTEMS, REDATA_WIDGETS
from came.ui.charts import bars, line
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    show_warnings,
    unavailable,
)
from came.ui.loaders import omie_prices, redata_widget
from came.ui.published_view import render_published_country


def page_spain(timeout: int) -> None:
    page_header(
        9,
        "Mercado eléctrico de España",
        "Indicadores físicos de Red Eléctrica y precios del mercado diario de OMIE.",
        "REData — Red Eléctrica y OMIE",
    )
    origin = st.radio(
        "Origen",
        ["Base mensual publicada", "Consulta directa a las fuentes"],
        horizontal=True,
        key="spain_origin",
    )
    if origin == "Base mensual publicada":
        if not render_published_country("ESP", key="spain_published"):
            st.info("Construya España desde **Mantenimiento → Mantenimiento de datos**.")
        return
    source_mode = st.radio("Conjunto", ["REData", "Precio diario OMIE"], horizontal=True)
    if source_mode == "REData":
        widget_name = st.selectbox("Indicador", list(REDATA_WIDGETS))
        system = st.selectbox("Sistema eléctrico", list(REDATA_SYSTEMS))
        trunc_label = st.selectbox("Agregación de la fuente", ["Mes", "Día", "Año"])
        trunc = {"Mes": "month", "Día": "day", "Año": "year"}[trunc_label]
        start, end = date_range_controls("spain_redata", months=24)
        if st.button("Consultar REData", type="primary", key="spain_redata_run"):
            category, widget, unit = REDATA_WIDGETS[widget_name]
            try:
                with st.spinner("Consultando Red Eléctrica…"):
                    result = redata_widget(
                        category, widget, start, end, trunc, system, unit, timeout
                    )
                    st.session_state["spain_result"] = result
                    st.session_state["spain_mode"] = (widget_name, system, trunc, start, end)
            except Exception as exc:
                unavailable(exc, source="REData")
        result = st.session_state.get("spain_result")
        if result is None:
            st.info("Seleccione el sistema y consulte la API oficial.")
            return
        data = result.data
        entities = sorted(data["entity_name"].dropna().unique())
        selected = st.multiselect("Series", entities, default=entities[: min(8, len(entities))])
        filtered = data[data["entity_name"].isin(selected)]
        indicators = {
            "Observaciones": len(filtered),
            "Series": filtered["entity_name"].nunique(),
            "Último valor": float(filtered["value"].iloc[-1]) if not filtered.empty else None,
        }
        show_indicators(indicators)
        fig = px.line(filtered, x="datetime", y="value", color="entity_name", title=widget_name)
        st.plotly_chart(fig, width="stretch")
        show_warnings(result.warnings)
        mode = st.session_state["spain_mode"]
        export_and_collect(
            module="9. España",
            title=f"España · {mode[0]}",
            data=filtered,
            indicators=indicators,
            parameters={"Sistema": mode[1], "Agregación": mode[2], "Series": selected},
            methodology=[result.meta.methodology],
            source="REData — Red Eléctrica",
            unit=result.meta.unit,
            period=f"{mode[3]} a {mode[4]}",
            warnings=result.warnings,
            figure=fig,
            key="mercado_espana_redata",
        )
        return

    col1, col2 = st.columns(2)
    end = col2.date_input("Fecha final", value=date.today() - timedelta(days=1), key="omie_end")
    start = col1.date_input("Fecha inicial", value=end - timedelta(days=6), key="omie_start")
    st.caption(
        "OMIE publica un archivo por día; para una consulta ágil se recomienda iniciar con una semana."
    )
    if st.button("Consultar precios OMIE", type="primary", key="omie_run"):
        try:
            with st.spinner("Descargando archivos diarios de OMIE…"):
                result = omie_prices(start, end, timeout)
                st.session_state["omie_result"] = result
                st.session_state["omie_query"] = (start, end)
        except Exception as exc:
            unavailable(exc, source="OMIE")
    result = st.session_state.get("omie_result")
    if result is None:
        st.info("Consulte los archivos públicos de precio del mercado diario.")
        return
    data = result.data
    indicators = summary_indicators(data)
    show_indicators(indicators)
    fig = line(data, "value", title="Precio del mercado diario — España", unit="EUR/MWh")
    st.plotly_chart(fig, width="stretch")
    local = data["datetime"].dt.tz_convert("Europe/Madrid")
    profile = data.assign(Hora=local.dt.hour).groupby("Hora", as_index=False)["value"].mean()
    st.plotly_chart(
        bars(
            profile,
            "Hora",
            "value",
            color=None,
            title="Perfil intradiario promedio",
            unit="EUR/MWh",
        ),
        width="stretch",
    )
    show_warnings(result.warnings)
    query = st.session_state["omie_query"]
    export_and_collect(
        module="9. España",
        title="Precio del mercado diario de España",
        data=data,
        indicators=indicators,
        parameters={"Frecuencia": result.meta.frequency},
        methodology=[result.meta.methodology],
        source="OMIE",
        unit="EUR/MWh",
        period=f"{query[0]} a {query[1]}",
        warnings=result.warnings,
        figure=fig,
        key="mercado_espana_omie",
    )
