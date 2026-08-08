"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

import pandas as pd
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
    xm_demand,
    xm_unserved,
)


def page_demand(timeout: int) -> None:
    page_header(
        2,
        "Demanda nacional",
        "Demanda del SIN y demanda no atendida sin doble conteo entre área y subárea.",
        "XM · DemaSIN, DemaNoAtenProg y DemaNoAtenNoProg",
    )
    start, end = date_range_controls("demand")
    frequency_label = st.radio(
        "Frecuencia", ["Mensual", "Diaria"], horizontal=True, key="demand_freq"
    )
    frequency = "monthly" if frequency_label == "Mensual" else "daily"
    include_unserved = st.checkbox("Consultar también demanda no atendida", value=True)
    if st.button("Consultar demanda", type="primary", key="demand_run"):
        try:
            with st.spinner("Consultando XM…"):
                demand = xm_demand(start, end, frequency, timeout)
                state = {"demand": demand, "warnings": [], "audit": pd.DataFrame()}
                if include_unserved:
                    monthly, audit, warnings = xm_unserved(start, end, timeout)
                    state.update({"unserved": monthly, "audit": audit, "warnings": warnings})
                st.session_state["demand_result"] = state
                st.session_state["demand_query"] = (start, end, frequency)
        except Exception as exc:
            unavailable(exc, source="XM")
    result = st.session_state.get("demand_result")
    if not result:
        st.info("Consulte un periodo para iniciar.")
        return
    demand = result["demand"]
    indicators = summary_indicators(demand, "GWh_día")
    show_indicators(indicators)
    fig = line(demand, "GWh_día", title="Demanda nacional promedio diaria", unit="GWh-día")
    st.plotly_chart(fig, use_container_width=True)
    additional: dict[str, pd.DataFrame] = {}
    if "unserved" in result:
        unserved = result["unserved"]
        st.plotly_chart(
            line(unserved, "GWh_día", title="Demanda no atendida", unit="GWh-día"),
            use_container_width=True,
        )
        show_warnings(result["warnings"])
        additional = {"Demanda no atendida": unserved, "Auditoría jerárquica": result["audit"]}
        with st.expander("Auditoría área/subárea"):
            st.dataframe(result["audit"], use_container_width=True)
    query = st.session_state.get("demand_query", (start, end, frequency))
    export_and_collect(
        module="2. Demanda nacional",
        title="Demanda nacional de Colombia",
        data=demand,
        indicators=indicators,
        parameters={"Frecuencia": query[2], "Incluye DNA": "unserved" in result},
        methodology=[
            "Energía mensual = suma de intervalos; GWh-día = GWh del mes / días calendario.",
            "Cuando área y subárea coexisten se usa área como total y subárea como verificación.",
        ],
        source="XM",
        unit="GWh-día",
        period=f"{query[0]} a {query[1]}",
        warnings=result["warnings"],
        figure=fig,
        additional=additional,
        key="demanda_colombia",
    )
