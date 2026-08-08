"""Módulos 9–10: España y Chile."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import plotly.express as px
import streamlit as st

from came.analytics.aggregation import summary_indicators
from came.config import REDATA_SYSTEMS, REDATA_WIDGETS
from came.data.providers.chile import ChileProvider
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


def page_spain(timeout: int) -> None:
    page_header(
        9,
        "Mercado eléctrico de España",
        "Indicadores físicos de Red Eléctrica y precios del mercado diario de OMIE.",
        "REData — Red Eléctrica y OMIE",
    )
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
                    result = redata_widget(category, widget, start, end, trunc, system, unit, timeout)
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
        st.plotly_chart(fig, use_container_width=True)
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
    st.caption("OMIE publica un archivo por día; para una consulta ágil se recomienda iniciar con una semana.")
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
    st.plotly_chart(fig, use_container_width=True)
    local = data["datetime"].dt.tz_convert("Europe/Madrid")
    profile = data.assign(Hora=local.dt.hour).groupby("Hora", as_index=False)["value"].mean()
    st.plotly_chart(bars(profile, "Hora", "value", color=None, title="Perfil intradiario promedio", unit="EUR/MWh"), use_container_width=True)
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
    st.info(
        "El portal oficial sirve estas tablas mediante Qlik y puede bloquear descargas automáticas. "
        "Por eso este módulo acepta directamente los TSV/XLSX exportados del Coordinador y valida su estructura."
    )
    st.markdown(
        "Descargas oficiales: [costos marginales](https://www.coordinador.cl/costos-marginales/) · "
        "[demanda real](https://www.coordinador.cl/operacion/graficos/operacion-real/demanda-real/)"
    )
    costs_file = st.file_uploader("Archivo oficial de costos marginales", type=["xlsx", "xls", "csv", "tsv", "txt"])
    demand_file = st.file_uploader("Archivo oficial de demanda por barra", type=["xlsx", "xls", "csv", "tsv", "txt"])
    if costs_url and demand_url:
        if st.button(
            "Descargar las dos URLs oficiales configuradas", key="chile_configured_run"
        ):
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
        st.warning("Para automatizar Chile deben configurarse juntas CHILE_COSTS_URL y CHILE_DEMAND_URL.")
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
        st.info("Los cálculos se habilitan cuando se cargan los dos archivos de la misma cobertura.")
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
    st.plotly_chart(line(data, "demand_mwh", title="Demanda agregada de las barras coincidentes", unit="MWh"), use_container_width=True)
    export_and_collect(
        module="10. Chile",
        title="Mercado eléctrico de Chile",
        data=data,
        indicators=indicators,
        parameters={"Archivo costos": result["files"][0], "Archivo demanda": result["files"][1]},
        methodology=["El precio nacional es el promedio del costo marginal por barra ponderado por su demanda en cada intervalo.", "Solo se usan coincidencias exactas de fecha y barra entre ambos archivos."],
        source="Coordinador Eléctrico Nacional de Chile",
        unit="USD/MWh y MWh",
        period=f"{data['datetime'].min()} a {data['datetime'].max()}",
        figure=fig,
        additional={"Costos por barra": result["costs"], "Demanda por barra": result["demand"]},
        key="mercado_chile",
    )
