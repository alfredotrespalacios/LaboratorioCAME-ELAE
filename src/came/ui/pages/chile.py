"""Módulos 9–10: España y Chile."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from came.data.providers.chile import ChileProvider
from came.ui.charts import line
from came.ui.components import (
    export_and_collect,
    page_header,
    show_indicators,
    unavailable,
)
from came.ui.published_view import render_published_country


def _remote_filename(url: str, fallback: str) -> str:
    name = Path(urlparse(url).path).name
    return name if Path(name).suffix else fallback


def page_chile(
    timeout: int,
    costs_url: str | None = None,
    demand_url: str | None = None,
) -> None:
    page_header(
        10,
        "Mercado eléctrico de Chile",
        "Costo marginal por barra y precio nacional ponderado por demanda a partir de exportaciones oficiales.",
        "Coordinador Eléctrico Nacional",
    )
    origin = st.radio(
        "Origen",
        ["Base mensual publicada", "Procesar archivos oficiales"],
        horizontal=True,
        key="chile_origin",
    )
    if origin == "Base mensual publicada":
        if not render_published_country("CHL", key="chile_published"):
            st.info("Construya Chile desde **Mantenimiento → Mantenimiento de datos**.")
        return
    st.info(
        "El portal oficial sirve estas tablas mediante Qlik y puede bloquear descargas automáticas. "
        "Por eso este módulo acepta directamente los TSV/XLSX exportados del Coordinador y valida su estructura."
    )
    st.markdown(
        "Descargas oficiales: [costos marginales](https://www.coordinador.cl/costos-marginales/) · "
        "[demanda real](https://www.coordinador.cl/operacion/graficos/operacion-real/demanda-real/)"
    )
    costs_file = st.file_uploader(
        "Archivo oficial de costos marginales", type=["xlsx", "xls", "csv", "tsv", "txt"]
    )
    demand_file = st.file_uploader(
        "Archivo oficial de demanda por barra", type=["xlsx", "xls", "csv", "tsv", "txt"]
    )
    if costs_url and demand_url:
        if st.button("Descargar las dos URLs oficiales configuradas", key="chile_configured_run"):
            try:
                provider = ChileProvider(timeout=timeout)
                with st.spinner("Descargando archivos configurados…"):
                    cost_content = provider.fetch_configured_url(costs_url)
                    demand_content = provider.fetch_configured_url(demand_url)
                    cost_name = _remote_filename(costs_url, "costos.xlsx")
                    demand_name = _remote_filename(demand_url, "demanda.xlsx")
                    costs = provider.parse_marginal_cost(cost_content, cost_name)
                    demand = provider.parse_demand(demand_content, demand_name)
                    national, by_time = provider.national_weighted_price(costs, demand)
                    st.session_state["chile_result"] = {
                        "costs": costs,
                        "demand": demand,
                        "by_time": by_time,
                        "national": national,
                        "files": (cost_name, demand_name),
                    }
            except Exception as exc:
                unavailable(exc, source="URLs configuradas del Coordinador")
    elif costs_url or demand_url:
        st.warning(
            "Para automatizar Chile deben configurarse juntas CHILE_COSTS_URL y CHILE_DEMAND_URL."
        )
    if st.button("Procesar archivos oficiales", type="primary", key="chile_run"):
        if not costs_file or not demand_file:
            st.error("Cargue ambos archivos oficiales para calcular una ponderación nacional.")
        else:
            try:
                provider = ChileProvider(timeout=timeout)
                costs = provider.parse_marginal_cost(costs_file.getvalue(), costs_file.name)
                demand = provider.parse_demand(demand_file.getvalue(), demand_file.name)
                national, by_time = provider.national_weighted_price(costs, demand)
                st.session_state["chile_result"] = {
                    "costs": costs,
                    "demand": demand,
                    "by_time": by_time,
                    "national": national,
                    "files": (costs_file.name, demand_file.name),
                }
            except Exception as exc:
                unavailable(exc, source="archivos del Coordinador")
    result = st.session_state.get("chile_result")
    if not result:
        st.info(
            "Los cálculos se habilitan cuando se cargan los dos archivos de la misma cobertura."
        )
        return
    data = result["by_time"]
    indicators = {
        "Precio ponderado nacional (USD/MWh)": result["national"],
        "Demanda media (MWh)": float(data["demand_mwh"].mean()),
        "Barras promedio": float(data["bars"].mean()),
    }
    show_indicators(indicators)
    fig = line(data, "price_usd_mwh", title="Costo marginal nacional ponderado", unit="USD/MWh")
    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(
        line(data, "demand_mwh", title="Demanda agregada de las barras coincidentes", unit="MWh"),
        use_container_width=True,
    )
    export_and_collect(
        module="10. Chile",
        title="Mercado eléctrico de Chile",
        data=data,
        indicators=indicators,
        parameters={"Archivo costos": result["files"][0], "Archivo demanda": result["files"][1]},
        methodology=[
            "El precio nacional es el promedio del costo marginal por barra ponderado por su demanda en cada intervalo.",
            "Solo se usan coincidencias exactas de fecha y barra entre ambos archivos.",
        ],
        source="Coordinador Eléctrico Nacional de Chile",
        unit="USD/MWh y MWh",
        period=f"{data['datetime'].min()} a {data['datetime'].max()}",
        figure=fig,
        additional={"Costos por barra": result["costs"], "Demanda por barra": result["demand"]},
        key="mercado_chile",
    )
