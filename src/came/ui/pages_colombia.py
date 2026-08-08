"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.aggregation import summary_indicators
from came.analytics.balance import (
    build_default_balance_table,
    calculate_balance,
    years_until_zero_margin,
)
from came.analytics.offer_curve import (
    build_offer_curve,
    offer_percentiles,
    sensitivity_table,
)
from came.config import TECHNOLOGY_ORDER, default_offer_stat
from came.ui.charts import bars, histogram, line, offer_curve
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    show_warnings,
    unavailable,
)
from came.ui.loaders import (
    xm_capacity,
    xm_catalog,
    xm_demand,
    xm_explore,
    xm_generation_resources,
    xm_generation_technology,
    xm_integrated,
    xm_offers,
    xm_spot,
    xm_unserved,
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
    annual = data.assign(Año=pd.to_datetime(data["datetime"]).dt.year).groupby("Año", as_index=False)["value"].mean()
    left.plotly_chart(bars(annual, "Año", "value", color=None, title="Promedio anual", unit="COP/kWh"), use_container_width=True)
    right.plotly_chart(histogram(data, "value", title="Distribución", unit="COP/kWh"), use_container_width=True)
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


def page_demand(timeout: int) -> None:
    page_header(
        2,
        "Demanda nacional",
        "Demanda del SIN y demanda no atendida sin doble conteo entre área y subárea.",
        "XM · DemaSIN, DemaNoAtenProg y DemaNoAtenNoProg",
    )
    start, end = date_range_controls("demand")
    frequency_label = st.radio("Frecuencia", ["Mensual", "Diaria"], horizontal=True, key="demand_freq")
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
        st.plotly_chart(line(unserved, "GWh_día", title="Demanda no atendida", unit="GWh-día"), use_container_width=True)
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


def page_generation_technology(timeout: int) -> None:
    page_header(
        3,
        "Generación nacional por tecnología",
        "Energía y participación de cada tecnología con homologación explícita de combustibles.",
        "XM · Gene/Recurso y ListadoRecursos",
    )
    start, end = date_range_controls("gen_tech")
    frequency_label = st.radio("Frecuencia", ["Mensual", "Diaria"], horizontal=True, key="gen_tech_freq")
    frequency = "monthly" if frequency_label == "Mensual" else "daily"
    if st.button("Consultar generación", type="primary", key="gen_tech_run"):
        try:
            with st.spinner("Consultando generación por recurso…"):
                st.session_state["gen_tech_result"] = xm_generation_technology(start, end, frequency, timeout)
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
        "Generación del último periodo (GWh)": float(filtered.groupby("datetime")["GWh"].sum().iloc[-1]),
        "Tecnologías": filtered["technology"].nunique(),
    }
    show_indicators(indicators)
    fig = bars(filtered, "datetime", "GWh", color="technology", title="Generación por tecnología", unit="GWh")
    st.plotly_chart(fig, use_container_width=True)
    latest = filtered[filtered["datetime"] == filtered["datetime"].max()]
    st.plotly_chart(px.pie(latest, values="GWh", names="technology", title="Participación del último periodo"), use_container_width=True)
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


def page_generation_resource(timeout: int) -> None:
    page_header(
        4,
        "Generación por planta, recurso o empresa",
        "Exploración jerárquica de la generación reportada por los recursos de XM.",
        "XM · Gene/Recurso, ListadoRecursos y ListadoAgentes",
    )
    start, end = date_range_controls("gen_resource", months=6)
    if st.button("Consultar recursos", type="primary", key="gen_resource_run"):
        try:
            with st.spinner("Descargando recursos y metadatos…"):
                st.session_state["gen_resource_result"] = xm_generation_resources(start, end, timeout)
                st.session_state["gen_resource_query"] = (start, end)
        except Exception as exc:
            unavailable(exc, source="XM")
    raw = st.session_state.get("gen_resource_result")
    if raw is None or raw.empty:
        st.info("Use un periodo corto para la primera consulta; los datos son horarios por recurso.")
        return
    level = st.selectbox("Nivel de análisis", ["Recurso", "Empresa", "Tecnología"])
    column = {"Recurso": "resource_name", "Empresa": "company_name", "Tecnología": "technology"}[level]
    if column not in raw:
        st.warning(f"XM no proporcionó {column} para esta consulta; se usará el código del recurso.")
        column = "entity_id"
    choices = sorted(raw[column].dropna().astype(str).unique())
    selected = st.multiselect("Elementos", choices, default=choices[: min(10, len(choices))])
    data = raw[raw[column].astype(str).isin(selected)].copy()
    data["Grupo"] = data[column].astype(str)
    monthly = data.groupby([pd.Grouper(key="datetime", freq="MS"), "Grupo"], as_index=False)["value"].sum()
    indicators = {"Generación seleccionada (GWh)": float(monthly["value"].sum()), "Elementos": len(selected)}
    show_indicators(indicators)
    fig = bars(monthly, "datetime", "value", color="Grupo", title=f"Generación por {level.lower()}", unit="GWh")
    st.plotly_chart(fig, use_container_width=True)
    query = st.session_state.get("gen_resource_query", (start, end))
    export_and_collect(
        module="4. Generación por recurso",
        title=f"Generación de Colombia por {level.lower()}",
        data=monthly,
        indicators=indicators,
        parameters={"Nivel": level, "Elementos": selected},
        methodology=["Suma mensual de los intervalos de generación por recurso seleccionado."],
        source="XM",
        unit="GWh",
        period=f"{query[0]} a {query[1]}",
        figure=fig,
        key="generacion_recurso_colombia",
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
        mask = visible.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        visible = visible[mask]
    st.dataframe(visible, use_container_width=True, hide_index=True)
    supported = visible[visible["Type"].astype(str) != "ListsEntities"].copy()
    labels = {
        f"{row.MetricId} · {row.MetricName} · {row.Entity} · {row.MetricUnits}": (row.MetricId, row.Entity)
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
                st.session_state["explorer_result"] = xm_explore(metric, entity, start, end, timeout)
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


def page_integrated(timeout: int) -> None:
    page_header(
        6,
        "Base integrada del mercado eléctrico",
        "Alinea mensualmente las principales variables del mercado y conserva el estado de cada fuente.",
        "XM, datos.gov.co y NOAA",
    )
    start, end = date_range_controls("integrated", months=60)
    include_macro = st.checkbox("Incluir TRM y ENSO", value=True)
    if st.button("Construir o actualizar base", type="primary", key="integrated_run"):
        try:
            with st.spinner("Integrando fuentes; un fallo parcial no elimina las demás series…"):
                result = xm_integrated(start, end, include_macro, timeout)
                st.session_state["integrated_result"] = result
                st.session_state["integrated_data"] = result.data
                st.session_state["integrated_query"] = (start, end, include_macro)
        except Exception as exc:
            unavailable(exc, source="Fuentes integradas")
    result = st.session_state.get("integrated_result")
    if result is None:
        st.info("Construya la base para habilitar también los módulos de modelación y portafolios.")
        return
    st.subheader("Estado por variable")
    st.dataframe(result.status, use_container_width=True, hide_index=True)
    show_warnings(result.warnings)
    data = result.data
    if data.empty:
        st.error("Ninguna variable estuvo disponible para el periodo.")
        return
    variables = [column for column in data.columns if column not in {"datetime", "Tiempo", "Niño", "Niña"}]
    selected = st.multiselect("Series visibles", variables, default=variables[: min(5, len(variables))])
    fig = line(data, selected, title="Base integrada", unit="Unidades propias (consulte la tabla)") if selected else None
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    indicators = {"Meses": len(data), "Variables": len(variables), "Disponibilidad_pct": float(data[variables].notna().mean().mean() * 100)}
    show_indicators(indicators)
    st.dataframe(data, use_container_width=True, hide_index=True)
    query = st.session_state.get("integrated_query", (start, end, include_macro))
    export_and_collect(
        module="6. Base integrada",
        title="Base integrada del mercado eléctrico colombiano",
        data=data,
        indicators=indicators,
        parameters={"Incluye macro": query[2]},
        methodology=result.methodologies,
        source="XM, datos.gov.co y NOAA",
        unit="Varias; visibles por columna",
        period=f"{query[0]} a {query[1]}",
        warnings=result.warnings,
        figure=fig,
        additional={"Estado de variables": result.status},
        key="base_integrada_colombia",
    )


def _empty_balance_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Tecnología": TECHNOLOGY_ORDER[:10],
            "CEN_MW": [0.0] * 10,
            "FP_normal": [0.52, 0.90, 0.90, 0.90, 0.90, 0.90, 0.17, 0.90, 0.90, 0.25],
            "FP_nino": [0.35, 0.90, 0.90, 0.90, 0.90, 0.90, 0.17, 0.90, 0.90, 0.25],
        }
    )


def page_balance(timeout: int) -> None:
    page_header(
        7,
        "Balance energético rápido",
        "Contrasta demanda promedio diaria con generación disponible bajo factores de planta editables.",
        "XM · CapEfecNeta/Recurso; supuestos del usuario",
    )
    selected_date = st.date_input("Fecha de capacidad efectiva", value=date.today() - timedelta(days=1))
    if st.button("Cargar capacidad de XM", type="primary", key="balance_capacity"):
        try:
            capacity, effective = xm_capacity(selected_date, timeout)
            values = dict(zip(capacity["Tecnología"], capacity["CEN_MW"], strict=False))
            st.session_state["balance_seed"] = build_default_balance_table(values)
            st.session_state["balance_effective"] = effective
        except Exception as exc:
            unavailable(exc, source="XM")
    if "balance_seed" not in st.session_state:
        st.session_state["balance_seed"] = _empty_balance_table()
    if st.session_state.get("balance_effective") is not None:
        st.caption(f"Capacidad efectiva publicada usada: {st.session_state['balance_effective']}")
    edited = st.data_editor(
        st.session_state["balance_seed"],
        num_rows="dynamic",
        use_container_width=True,
        key="balance_editor",
        column_config={
            "CEN_MW": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
            "FP_normal": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, format="%.3f"),
            "FP_nino": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, format="%.3f"),
        },
    )
    demand = st.number_input("Demanda (GWh-día)", min_value=0.01, value=230.0, step=1.0)
    growth = st.number_input("Crecimiento anual de demanda (%)", value=2.5, step=0.1) / 100
    if st.button("Calcular dos escenarios", key="balance_run"):
        try:
            normal = calculate_balance(edited, demand_gwh_day=demand, factor_column="FP_normal")
            nino = calculate_balance(edited, demand_gwh_day=demand, factor_column="FP_nino")
            summary = pd.DataFrame(
                [
                    {"Escenario": "Normal", "Generación_GWh_día": normal.generation_available_gwh_day, "Margen_pct": normal.margin * 100, "Demanda_no_cubierta_GWh_día": normal.uncovered_demand_gwh_day, "Años_hasta_margen_cero": years_until_zero_margin(demand, normal.generation_available_gwh_day, growth)},
                    {"Escenario": "El Niño", "Generación_GWh_día": nino.generation_available_gwh_day, "Margen_pct": nino.margin * 100, "Demanda_no_cubierta_GWh_día": nino.uncovered_demand_gwh_day, "Años_hasta_margen_cero": years_until_zero_margin(demand, nino.generation_available_gwh_day, growth)},
                ]
            )
            st.session_state["balance_result"] = {"summary": summary, "normal": normal.table, "nino": nino.table, "inputs": edited.copy(), "demand": demand, "growth": growth}
            st.session_state["balance_table"] = normal.table
        except Exception as exc:
            st.error(str(exc))
    result = st.session_state.get("balance_result")
    if not result:
        st.info("Las capacidades en cero son un lienzo editable, no datos observados. Cargue XM o ingrese sus supuestos.")
        return
    summary = result["summary"]
    st.dataframe(summary, use_container_width=True, hide_index=True)
    fig = bars(summary, "Escenario", "Margen_pct", color="Escenario", title="Margen energético", unit="%")
    st.plotly_chart(fig, use_container_width=True)
    indicators = {"Demanda_GWh_día": result["demand"], "Margen_normal_pct": summary.iloc[0]["Margen_pct"], "Margen_Niño_pct": summary.iloc[1]["Margen_pct"]}
    export_and_collect(
        module="7. Balance energético",
        title="Balance energético rápido de Colombia",
        data=summary,
        indicators=indicators,
        parameters={"Demanda GWh-día": result["demand"], "Crecimiento": result["growth"]},
        methodology=["Generación disponible = CEN MW × factor de planta × 24 / 1.000.", "Margen = generación disponible / demanda - 1."],
        source="XM y supuestos editables",
        unit="GWh-día y %",
        period=str(selected_date),
        figure=fig,
        additional={"Supuestos": result["inputs"], "Normal": result["normal"], "El Niño": result["nino"]},
        key="balance_energetico_colombia",
    )


def _offer_seed() -> pd.DataFrame:
    balance = st.session_state.get("balance_table")
    if balance is not None and not balance.empty:
        seed = balance[["Tecnología", "Generación_disponible_GWh_día"]].rename(columns={"Generación_disponible_GWh_día": "Disponibilidad_GWh_día"})
        seed["Precio_COP_kWh"] = 0.0
        return seed
    return pd.DataFrame({"Tecnología": TECHNOLOGY_ORDER[:10], "Disponibilidad_GWh_día": [0.0] * 10, "Precio_COP_kWh": [0.0] * 10})


def page_offer_curve(timeout: int) -> None:
    page_header(
        8,
        "Curva de oferta rápida",
        "Construye una curva escalonada y estima el precio con ajustes lineal, cuadrático, cúbico y exponencial.",
        "XM · PrecOferDesp/Recurso; disponibilidad y supuestos editables",
    )
    left, right = st.columns(2)
    offer_start = left.date_input("Inicio de ofertas", value=date.today() - timedelta(days=30), key="offer_start")
    offer_end = right.date_input("Fin de ofertas", value=date.today() - timedelta(days=1), key="offer_end")
    if st.button("Cargar percentiles de ofertas XM", type="primary", key="offer_live"):
        try:
            raw = xm_offers(offer_start, offer_end, timeout)
            percentiles = offer_percentiles(raw)
            seed = _offer_seed().merge(percentiles, on="Tecnología", how="left")
            seed["Precio_COP_kWh"] = seed.apply(lambda row: row.get(default_offer_stat(str(row["Tecnología"])), np.nan), axis=1)
            st.session_state["offer_percentiles"] = percentiles
            st.session_state["offer_seed"] = seed[["Tecnología", "Disponibilidad_GWh_día", "Precio_COP_kWh"]]
        except Exception as exc:
            unavailable(exc, source="XM")
    if "offer_seed" not in st.session_state:
        st.session_state["offer_seed"] = _offer_seed()
    scenario_a = st.text_input("Nombre del escenario 1", value="Escenario base")
    scenario_b = st.text_input("Nombre del escenario 2", value="Escenario alternativo")
    demand = st.number_input("Demanda para el despacho (GWh-día)", min_value=0.01, value=230.0, step=1.0)
    real_price = st.number_input("Precio real para contraste (COP/kWh, opcional; 0 = no usar)", min_value=0.0, value=0.0)
    include_hydro = st.checkbox("Incluir hidráulica en los ajustes continuos", value=True)
    tabs = st.tabs([scenario_a, scenario_b])
    edited_tables: list[pd.DataFrame] = []
    for index, tab in enumerate(tabs):
        with tab:
            base = st.session_state["offer_seed"].copy()
            if index == 1:
                base["Disponibilidad_GWh_día"] = pd.to_numeric(base["Disponibilidad_GWh_día"], errors="coerce").fillna(0) * 0.90
            edited_tables.append(
                st.data_editor(
                    base,
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"offer_editor_{index}",
                    column_config={
                        "Disponibilidad_GWh_día": st.column_config.NumberColumn(min_value=0.0),
                        "Precio_COP_kWh": st.column_config.NumberColumn(min_value=0.0),
                    },
                )
            )
    if st.button("Calcular ambos escenarios", key="offer_run"):
        try:
            outputs = []
            for name, table in zip((scenario_a, scenario_b), edited_tables, strict=True):
                result = build_offer_curve(table, demand_gwh_day=demand, real_price=real_price or None, include_hydraulic=include_hydro)
                fits = pd.DataFrame([vars(item) for item in result.fits])
                outputs.append((name, result, fits, sensitivity_table(table, base_demand=demand)))
            st.session_state["offer_results"] = outputs
        except Exception as exc:
            st.error(str(exc))
    outputs = st.session_state.get("offer_results")
    if not outputs:
        st.info("Las filas con cero son supuestos editables. Cargue ofertas XM y una disponibilidad antes de estimar.")
        return
    combined: list[pd.DataFrame] = []
    last_fig = None
    for name, result, fits, sensitivity in outputs:
        st.subheader(name)
        show_indicators({"Marginal_discreto_COP_kWh": result.marginal_discrete_price, "Tecnología_marginal": result.marginal_technology, "Déficit_GWh_día": result.deficit_gwh_day})
        last_fig = offer_curve(result.supply, demand)
        st.plotly_chart(last_fig, use_container_width=True)
        st.dataframe(fits[["model", "equation", "r2", "estimated_price", "absolute_error", "percentage_error", "warning"]], use_container_width=True, hide_index=True)
        with st.expander("Sensibilidad a la demanda"):
            st.dataframe(sensitivity, use_container_width=True, hide_index=True)
        part = fits.assign(Escenario=name)
        combined.append(part)
    results_table = pd.concat(combined, ignore_index=True)
    export_and_collect(
        module="8. Curva de oferta",
        title="Curva de oferta rápida de Colombia",
        data=results_table,
        indicators={"Demanda_GWh_día": demand, "Escenarios": 2},
        parameters={"Escenario 1": scenario_a, "Escenario 2": scenario_b, "Incluye hidráulica": include_hydro},
        methodology=["La oferta se ordena por precio y se acumula sin extrapolar cuando existe déficit.", "P5 por defecto para hidráulica, solar y eólica; P50 para las demás tecnologías."],
        source="XM y supuestos editables",
        unit="COP/kWh y GWh-día",
        period=f"{offer_start} a {offer_end}",
        figure=last_fig,
        additional={"Percentiles XM": st.session_state.get("offer_percentiles", pd.DataFrame())},
        key="curva_oferta_colombia",
    )
