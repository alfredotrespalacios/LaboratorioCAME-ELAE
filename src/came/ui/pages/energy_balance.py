"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from came.analytics.balance import (
    build_default_balance_table,
    calculate_balance,
    years_until_zero_margin,
)
from came.config import TECHNOLOGY_ORDER
from came.ui.charts import bars
from came.ui.components import (
    export_and_collect,
    page_header,
    unavailable,
)
from came.ui.loaders import (
    xm_capacity,
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
    selected_date = st.date_input(
        "Fecha de capacidad efectiva", value=date.today() - timedelta(days=1)
    )
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
        width="stretch",
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
            comparison = normal.table[
                ["Tecnología", "CEN_MW", "FP_normal", "Generación_disponible_GWh_día"]
            ].rename(
                columns={
                    "Generación_disponible_GWh_día": "Disponibilidad_normal_GWh_día"
                }
            )
            comparison["FP_nino"] = nino.table["FP_nino"].to_numpy()
            comparison["Disponibilidad_Niño_GWh_día"] = nino.table[
                "Generación_disponible_GWh_día"
            ].to_numpy()
            normal_total = comparison["Disponibilidad_normal_GWh_día"].sum()
            nino_total = comparison["Disponibilidad_Niño_GWh_día"].sum()
            comparison["Participación_normal_pct"] = (
                comparison["Disponibilidad_normal_GWh_día"] / normal_total * 100
                if normal_total > 0
                else 0.0
            )
            comparison["Participación_Niño_pct"] = (
                comparison["Disponibilidad_Niño_GWh_día"] / nino_total * 100
                if nino_total > 0
                else 0.0
            )
            summary = pd.DataFrame(
                [
                    {
                        "Escenario": "Normal",
                        "Generación_GWh_día": normal.generation_available_gwh_day,
                        "Margen_pct": normal.margin * 100,
                        "Demanda_no_cubierta_GWh_día": normal.uncovered_demand_gwh_day,
                        "Años_hasta_margen_cero": years_until_zero_margin(
                            demand, normal.generation_available_gwh_day, growth
                        ),
                    },
                    {
                        "Escenario": "El Niño",
                        "Generación_GWh_día": nino.generation_available_gwh_day,
                        "Margen_pct": nino.margin * 100,
                        "Demanda_no_cubierta_GWh_día": nino.uncovered_demand_gwh_day,
                        "Años_hasta_margen_cero": years_until_zero_margin(
                            demand, nino.generation_available_gwh_day, growth
                        ),
                    },
                ]
            )
            st.session_state["balance_result"] = {
                "summary": summary,
                "normal": normal.table,
                "nino": nino.table,
                "comparison": comparison,
                "inputs": edited.copy(),
                "demand": demand,
                "growth": growth,
            }
            st.session_state["balance_table"] = normal.table
        except Exception as exc:
            st.error(str(exc))
    result = st.session_state.get("balance_result")
    if not result:
        st.info(
            "Las capacidades en cero son un lienzo editable, no datos observados. Cargue XM o ingrese sus supuestos."
        )
        return
    summary = result["summary"]
    st.dataframe(summary, width="stretch", hide_index=True)
    st.subheader("Disponibilidad por tecnología")
    st.caption(
        "La disponibilidad se calcula para cada tecnología como CEN × factor de planta × 24 / 1.000."
    )
    st.dataframe(
        result["comparison"],
        width="stretch",
        hide_index=True,
        column_config={
            "CEN_MW": st.column_config.NumberColumn(
                "Capacidad efectiva neta (MW)", format="%.2f"
            ),
            "FP_normal": st.column_config.NumberColumn("FP normal", format="%.3f"),
            "Disponibilidad_normal_GWh_día": st.column_config.NumberColumn(
                "Disponibilidad normal (GWh-día)", format="%.3f"
            ),
            "FP_nino": st.column_config.NumberColumn("FP El Niño", format="%.3f"),
            "Disponibilidad_Niño_GWh_día": st.column_config.NumberColumn(
                "Disponibilidad El Niño (GWh-día)", format="%.3f"
            ),
            "Participación_normal_pct": st.column_config.NumberColumn(
                "Participación normal (%)", format="%.2f"
            ),
            "Participación_Niño_pct": st.column_config.NumberColumn(
                "Participación El Niño (%)", format="%.2f"
            ),
        },
    )
    fig = bars(
        summary, "Escenario", "Margen_pct", color="Escenario", title="Margen energético", unit="%"
    )
    st.plotly_chart(fig, width="stretch")
    indicators = {
        "Demanda_GWh_día": result["demand"],
        "Margen_normal_pct": summary.iloc[0]["Margen_pct"],
        "Margen_Niño_pct": summary.iloc[1]["Margen_pct"],
    }
    export_and_collect(
        module="7. Balance energético",
        title="Balance energético rápido de Colombia",
        data=summary,
        indicators=indicators,
        parameters={"Demanda GWh-día": result["demand"], "Crecimiento": result["growth"]},
        methodology=[
            "Generación disponible = CEN MW × factor de planta × 24 / 1.000.",
            "Margen = generación disponible / demanda - 1.",
        ],
        source="XM y supuestos editables",
        unit="GWh-día y %",
        period=str(selected_date),
        figure=fig,
        additional={
            "Supuestos": result["inputs"],
            "Normal": result["normal"],
            "El Niño": result["nino"],
            "Disponibilidad por tecnología": result["comparison"],
        },
        key="balance_energetico_colombia",
    )
