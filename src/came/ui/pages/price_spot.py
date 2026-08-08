"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.aggregation import summary_indicators
from came.ui.charts import bars, histogram, line
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    unavailable,
)
from came.ui.loaders import (
    xm_explore,
    xm_spot,
)


def page_spot(timeout: int) -> None:
    page_header(
        1,
        "Precio de bolsa",
        "Evolución, variaciones y distribución del precio nacional de bolsa.",
        "XM · PrecBolsNaci",
    )
    start, end = date_range_controls("spot")
    frequency_label = st.radio("Frecuencia", ["Mensual", "Diaria"], horizontal=True)
    frequency = "monthly" if frequency_label == "Mensual" else "daily"
    if st.button("Consultar precio", type="primary", key="spot_run"):
        try:
            with st.spinner("Consultando XM…"):
                st.session_state["spot_result"] = xm_spot(start, end, frequency, timeout)
                st.session_state["spot_query"] = (start, end, frequency)
        except Exception as exc:
            unavailable(exc, source="XM")
    data = st.session_state.get("spot_result")
    if data is None or data.empty:
        st.info("Seleccione un periodo y consulte la fuente oficial.")
        return
    indicators = summary_indicators(data)
    show_indicators(indicators)
    fig = line(data, "value", title="Precio de bolsa", unit="COP/kWh")
    st.plotly_chart(fig, use_container_width=True)
    left, right = st.columns(2)
    annual = (
        data.assign(Año=pd.to_datetime(data["datetime"]).dt.year)
        .groupby("Año", as_index=False)["value"]
        .mean()
    )
    left.plotly_chart(
        bars(annual, "Año", "value", color=None, title="Promedio anual", unit="COP/kWh"),
        use_container_width=True,
    )
    right.plotly_chart(
        histogram(data, "value", title="Distribución", unit="COP/kWh"), use_container_width=True
    )
    with st.expander("Perfil intradiario de los últimos 31 días del periodo"):
        if st.button("Cargar observaciones horarias", key="spot_hourly"):
            try:
                hourly_start = max(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=30))
                result = xm_explore("PrecBolsNaci", "Sistema", hourly_start, end, timeout)
                hourly = result.data[["datetime", "value"]].copy()
                local = hourly["datetime"].dt.tz_convert("America/Bogota")
                hourly["Hora"] = local.dt.hour
                st.session_state["spot_hourly_data"] = hourly
            except Exception as exc:
                unavailable(exc, source="XM")
        hourly = st.session_state.get("spot_hourly_data")
        if hourly is not None:
            st.plotly_chart(
                px.violin(hourly, x="Hora", y="value", box=True, title="Precio por hora del día"),
                use_container_width=True,
            )
    query = st.session_state.get("spot_query", (start, end, frequency))
    export_and_collect(
        module="1. Precio de bolsa",
        title="Precio de bolsa de Colombia",
        data=data,
        indicators=indicators,
        parameters={"Frecuencia": query[2]},
        methodology=["Promedio simple de las observaciones de precio en cada periodo."],
        source="XM · PrecBolsNaci",
        unit="COP/kWh",
        period=f"{query[0]} a {query[1]}",
        figure=fig,
        key="precio_bolsa_colombia",
    )
