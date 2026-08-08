"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from came.ui.charts import bars
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    unavailable,
)
from came.ui.loaders import (
    xm_generation_technology,
)


def page_generation_technology(timeout: int) -> None:
    page_header(
        3,
        "Generación nacional por tecnología",
        "Energía y participación de cada tecnología con homologación explícita de combustibles.",
        "XM · Gene/Recurso y ListadoRecursos",
    )
    start, end = date_range_controls("gen_tech")
    frequency_label = st.radio(
        "Frecuencia", ["Mensual", "Diaria"], horizontal=True, key="gen_tech_freq"
    )
    frequency = "monthly" if frequency_label == "Mensual" else "daily"
    if st.button("Consultar generación", type="primary", key="gen_tech_run"):
        try:
            with st.spinner("Consultando generación por recurso…"):
                st.session_state["gen_tech_result"] = xm_generation_technology(
                    start, end, frequency, timeout
                )
                st.session_state["gen_tech_query"] = (start, end, frequency)
        except Exception as exc:
            unavailable(exc, source="XM")
    data = st.session_state.get("gen_tech_result")
    if data is None or data.empty:
        st.info("Consulte la generación oficial para ver la composición tecnológica.")
        return
    selected = st.multiselect(
        "Tecnologías",
        [str(value) for value in data["technology"].dropna().unique()],
        default=[str(value) for value in data["technology"].dropna().unique()],
    )
    filtered = data[data["technology"].astype(str).isin(selected)]
    indicators = {
        "Generación del último periodo (GWh)": float(
            filtered.groupby("datetime")["GWh"].sum().iloc[-1]
        ),
        "Tecnologías": filtered["technology"].nunique(),
    }
    show_indicators(indicators)
    fig = bars(
        filtered,
        "datetime",
        "GWh",
        color="technology",
        title="Generación por tecnología",
        unit="GWh",
    )
    st.plotly_chart(fig, use_container_width=True)
    latest = filtered[filtered["datetime"] == filtered["datetime"].max()]
    st.plotly_chart(
        px.pie(latest, values="GWh", names="technology", title="Participación del último periodo"),
        use_container_width=True,
    )
    query = st.session_state.get("gen_tech_query", (start, end, frequency))
    export_and_collect(
        module="3. Generación por tecnología",
        title="Generación de Colombia por tecnología",
        data=filtered,
        indicators=indicators,
        parameters={"Frecuencia": query[2], "Tecnologías": selected},
        methodology=["Cada intervalo de Gene/Recurso se suma por periodo y tecnología homologada."],
        source="XM",
        unit="GWh",
        period=f"{query[0]} a {query[1]}",
        figure=fig,
        key="generacion_tecnologia_colombia",
    )
