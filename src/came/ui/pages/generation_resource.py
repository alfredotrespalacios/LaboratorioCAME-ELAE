"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

import pandas as pd
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
    xm_generation_resources,
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
                st.session_state["gen_resource_result"] = xm_generation_resources(
                    start, end, timeout
                )
                st.session_state["gen_resource_query"] = (start, end)
        except Exception as exc:
            unavailable(exc, source="XM")
    history = st.session_state.get("gen_resource_result")
    if history is None or history.by_resource.empty:
        st.info(
            "Consulte un periodo. La aplicación reduce los datos horarios a un histórico mensual "
            "completo antes de preparar el reporte."
        )
        return
    level = st.selectbox("Nivel de análisis", ["Recurso", "Empresa", "Tecnología"])
    table, column = {
        "Recurso": (history.by_resource, "resource_name"),
        "Empresa": (history.by_company, "company_name"),
        "Tecnología": (history.by_technology, "technology"),
    }[level]
    choices = sorted(table[column].dropna().astype(str).unique())
    selected = st.multiselect("Elementos", choices, default=choices[: min(10, len(choices))])
    data = table[table[column].astype(str).isin(selected)].copy()
    data["Grupo"] = data[column].astype(str)
    monthly = data.groupby(["datetime", "Grupo"], as_index=False)[["GWh_mes", "GWh_día"]].sum()
    indicators = {
        "Generación seleccionada (GWh)": float(monthly["GWh_mes"].sum()),
        "Elementos visibles": len(selected),
        "Recursos en el Excel": int(history.by_resource["resource_code"].nunique()),
        "Meses en el Excel": int(history.by_resource["datetime"].nunique()),
    }
    show_indicators(indicators)
    fig = bars(
        monthly,
        "datetime",
        "GWh_mes",
        color="Grupo",
        title=f"Generación por {level.lower()}",
        unit="GWh/mes",
    )
    st.plotly_chart(fig, width="stretch")
    st.info(
        "El Excel conserva el histórico mensual de **todos los recursos consultados**, aunque "
        "la gráfica muestre únicamente los elementos seleccionados. Para solicitar la máxima "
        "cobertura disponible, use **Toda la historia** antes de consultar."
    )
    query = st.session_state.get("gen_resource_query", (start, end))

    def excel_labels(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.rename(
            columns={
                "datetime": "Mes",
                "resource_code": "Código recurso",
                "resource_name": "Recurso",
                "company_code": "Código agente",
                "company_name": "Agente o empresa",
                "technology": "Tecnología",
                "GWh_mes": "Generación mensual (GWh)",
                "GWh_día": "Generación promedio (GWh-día)",
            }
        )

    selected_export = excel_labels(monthly)
    validation_export = history.validation.rename(columns={"datetime": "Mes"})
    export_and_collect(
        module="4. Generación por recurso",
        title=f"Generación de Colombia por {level.lower()}",
        data=selected_export,
        indicators=indicators,
        parameters={
            "Nivel visible": level,
            "Elementos visibles": selected,
            "Alcance del Excel": "Todos los recursos del periodo consultado",
        },
        methodology=[
            "Cada intervalo de Gene/Recurso se convierte a GWh y se suma por mes calendario.",
            "GWh-día = generación mensual en GWh dividida por los días calendario del mes.",
            "La gráfica y el PDF usan la selección visible; el Excel conserva todos los recursos.",
            "Los totales por empresa y tecnología se concilian contra el total por recurso.",
        ],
        source="XM",
        unit="GWh-mes y GWh-día",
        period=f"{query[0]} a {query[1]}",
        figure=fig,
        additional={
            "Histórico recursos": excel_labels(history.by_resource),
            "Histórico empresas": excel_labels(history.by_company),
            "Histórico tecnología": excel_labels(history.by_technology),
            "Catálogo recursos": excel_labels(history.resource_catalog),
            "Validación totales": validation_export,
        },
        key="generacion_recurso_colombia",
    )
