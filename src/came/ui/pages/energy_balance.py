"""Balance energético por escenarios con demanda y disponibilidad editables."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from came.analytics.balance import (
    build_balance_comparison,
    build_default_balance_table,
    calculate_balance,
    years_until_zero_margin,
)
from came.config import TECHNOLOGY_ORDER
from came.errors import DataQualityError
from came.ui.charts import bars
from came.ui.components import export_and_collect, page_header, unavailable
from came.ui.loaders import xm_capacity


def _empty_balance_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Tecnología": TECHNOLOGY_ORDER[:10],
            "CEN_MW": [0.0] * 10,
            "FP_normal": [0.52, 0.90, 0.90, 0.90, 0.90, 0.90, 0.17, 0.90, 0.90, 0.25],
            "FP_nino": [0.35, 0.90, 0.90, 0.90, 0.90, 0.90, 0.17, 0.90, 0.90, 0.25],
        }
    )


def _scenario_summary(
    table: pd.DataFrame,
    *,
    first_name: str,
    first_demand: float,
    second_name: str,
    second_demand: float,
    growth: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calcula resumen y tabla larga para dos escenarios con nombres libres."""

    names = [str(first_name).strip(), str(second_name).strip()]
    if not all(names):
        raise DataQualityError("Cada escenario debe tener un nombre.")
    if names[0].casefold() == names[1].casefold():
        raise DataQualityError("Los dos escenarios deben tener nombres diferentes.")
    definitions = [
        (names[0], float(first_demand), "FP_normal"),
        (names[1], float(second_demand), "FP_nino"),
    ]
    summaries: list[dict[str, Any]] = []
    technology_rows: list[pd.DataFrame] = []
    for name, demand, factor_column in definitions:
        result = calculate_balance(
            table,
            demand_gwh_day=demand,
            factor_column=factor_column,
        )
        availability = result.table["Disponibilidad_GWh_día"].astype(float)
        long = result.table[
            ["Tecnología", "CEN_MW", factor_column, "Disponibilidad_GWh_día"]
        ].rename(columns={factor_column: "Factor_planta"})
        long.insert(0, "Escenario", name)
        long["Participación_pct"] = (
            availability / result.availability_gwh_day * 100
            if result.availability_gwh_day > 0
            else 0.0
        )
        long["Demanda_escenario_GWh_día"] = demand
        technology_rows.append(long)
        summaries.append(
            {
                "Escenario": name,
                "Demanda_GWh_día": demand,
                "Disponibilidad_GWh_día": result.availability_gwh_day,
                "Margen_pct": result.margin * 100,
                "Demanda_no_cubierta_GWh_día": result.uncovered_demand_gwh_day,
                "Cobertura_pct": result.generation_demand_ratio * 100,
                "Crecimiento_demanda_anual_pct": growth * 100,
                "Años_hasta_margen_cero": years_until_zero_margin(
                    demand,
                    result.availability_gwh_day,
                    growth,
                ),
            }
        )
    return pd.DataFrame(summaries), pd.concat(technology_rows, ignore_index=True)


def _availability_demand_figure(
    scenario_rows: pd.DataFrame,
    demands: list[tuple[str, float]],
) -> go.Figure:
    """Barra apilada de tecnologías y dos líneas de demanda con etiquetas dinámicas."""

    figure = px.bar(
        scenario_rows,
        x="Escenario",
        y="Disponibilidad_GWh_día",
        color="Tecnología",
        barmode="stack",
        title="Disponibilidad por tecnología y demanda de cada escenario",
        labels={"Disponibilidad_GWh_día": "GWh-día"},
    )
    line_styles = [
        {"color": "#9B1C1C", "dash": "dash"},
        {"color": "#18324A", "dash": "dot"},
    ]
    scenario_names = scenario_rows["Escenario"].drop_duplicates().tolist()
    for (name, demand), style in zip(demands, line_styles, strict=False):
        figure.add_trace(
            go.Scatter(
                x=scenario_names,
                y=[float(demand)] * len(scenario_names),
                mode="lines+markers",
                name=f"Demanda · {name}",
                legendgroup="demanda",
                line=style,
                marker={"size": 7},
                hovertemplate=f"Demanda · {name}: %{{y:.3f}} GWh-día<extra></extra>",
            )
        )
    figure.update_layout(
        xaxis_title="Escenario",
        yaxis_title="Disponibilidad y demanda (GWh-día)",
        legend_title="Tecnología o demanda",
    )
    return figure


def page_balance(timeout: int) -> None:
    page_header(
        7,
        "Balance energético rápido",
        "Contrasta la demanda propia de dos escenarios con la disponibilidad calculada a partir de CEN y factores de planta editables.",
        "XM · CapEfecNeta/Recurso; supuestos del usuario",
    )
    st.info(
        "La capacidad efectiva neta es común a los dos escenarios. Cada escenario conserva "
        "su nombre, demanda y factor de planta. La aplicación no interpreta la disponibilidad "
        "como generación observada: es una capacidad energética calculada bajo los supuestos ingresados."
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

    st.subheader("1. Capacidad y factores de planta")
    st.caption(
        "Edite la CEN y los factores de planta. El primer factor alimenta el escenario 1 y "
        "el segundo alimenta el escenario 2; los nombres se definen en el bloque siguiente."
    )
    edited = st.data_editor(
        st.session_state["balance_seed"],
        num_rows="dynamic",
        width="stretch",
        key="balance_editor",
        column_config={
            "CEN_MW": st.column_config.NumberColumn(
                "Capacidad efectiva neta (MW)", min_value=0.0, format="%.2f"
            ),
            "FP_normal": st.column_config.NumberColumn(
                "FP escenario 1", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "FP_nino": st.column_config.NumberColumn(
                "FP escenario 2", min_value=0.0, max_value=1.0, format="%.3f"
            ),
        },
    )

    st.subheader("2. Definición de escenarios")
    left, right = st.columns(2)
    with left:
        first_name = st.text_input(
            "Nombre del escenario 1", value="Operación normal", key="balance_scenario_1"
        )
        first_demand = st.number_input(
            "Demanda del escenario 1 (GWh-día)",
            min_value=0.01,
            value=230.0,
            step=1.0,
            key="balance_demand_1",
        )
    with right:
        second_name = st.text_input(
            "Nombre del escenario 2", value="El Niño", key="balance_scenario_2"
        )
        second_demand = st.number_input(
            "Demanda del escenario 2 (GWh-día)",
            min_value=0.01,
            value=235.0,
            step=1.0,
            key="balance_demand_2",
        )
    growth = (
        st.number_input(
            "Crecimiento anual de demanda para ambos escenarios (%)",
            value=2.5,
            step=0.1,
            key="balance_growth",
        )
        / 100
    )
    st.caption(
        "La tasa de crecimiento no cambia la demanda inicial ni el margen actual. Se utiliza "
        "únicamente para estimar cuántos años tardaría cada escenario en agotar su margen, "
        "suponiendo disponibilidad constante y crecimiento compuesto constante."
    )

    if st.button("Calcular dos escenarios", key="balance_run", type="primary"):
        try:
            summary, scenario_rows = _scenario_summary(
                edited,
                first_name=first_name,
                first_demand=first_demand,
                second_name=second_name,
                second_demand=second_demand,
                growth=growth,
            )
            comparison = build_balance_comparison(
                edited,
                first_name=first_name,
                first_demand_gwh_day=first_demand,
                second_name=second_name,
                second_demand_gwh_day=second_demand,
            )
            st.session_state["balance_result"] = {
                "summary": summary,
                "scenario_rows": scenario_rows,
                "comparison": comparison,
                "inputs": edited.copy(),
                "scenario_names": [first_name.strip(), second_name.strip()],
                "demands": [float(first_demand), float(second_demand)],
                "growth": growth,
            }
            st.session_state["balance_table"] = scenario_rows.copy()
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get("balance_result")
    if not result:
        st.info(
            "Las capacidades en cero son un lienzo editable, no datos observados. Cargue XM "
            "o ingrese sus supuestos y después calcule los escenarios."
        )
        return

    summary = result["summary"]
    names = result["scenario_names"]
    demands = result["demands"]
    st.subheader("3. Resumen de resultados")
    st.dataframe(summary, width="stretch", hide_index=True)
    st.caption(
        "Margen = disponibilidad / demanda − 1. Una demanda no cubierta positiva indica que "
        "la disponibilidad calculada no alcanza la demanda inicial del escenario."
    )

    st.subheader("4. Años hasta margen cero")
    st.latex(r"Demanda_0(1+g)^n-Disponibilidad=0")
    st.latex(
        r"n=\frac{\ln\left(Disponibilidad/Demanda_0\right)}{\ln(1+g)}"
    )
    st.caption(
        "Si la demanda ya iguala o supera la disponibilidad, n = 0. Si g ≤ 0 y todavía "
        "existe margen, el margen no se agotaría bajo este supuesto simplificado."
    )

    st.subheader("5. Disponibilidad por tecnología")
    st.caption(
        "Disponibilidad = CEN × factor de planta × 24 / 1.000. En la fila Total, la CEN y "
        "las disponibilidades se suman, las participaciones llegan a 100 % y el factor de "
        "planta es un promedio ponderado por la CEN."
    )
    st.dataframe(result["comparison"], width="stretch", hide_index=True)

    availability_fig = _availability_demand_figure(
        result["scenario_rows"],
        list(zip(names, demands, strict=True)),
    )
    st.plotly_chart(availability_fig, width="stretch")
    st.caption(
        f"Las dos líneas representan las demandas de «{names[0]}» y «{names[1]}». "
        "Sus etiquetas cambian automáticamente cuando se cambia el nombre de un escenario."
    )
    margin_fig = bars(
        summary,
        "Escenario",
        "Margen_pct",
        color="Escenario",
        title="Margen energético por escenario",
        unit="%",
    )
    st.plotly_chart(margin_fig, width="stretch")

    indicators = {
        f"Demanda · {names[0]} (GWh-día)": demands[0],
        f"Demanda · {names[1]} (GWh-día)": demands[1],
        f"Margen · {names[0]} (%)": summary.iloc[0]["Margen_pct"],
        f"Margen · {names[1]} (%)": summary.iloc[1]["Margen_pct"],
    }
    export_and_collect(
        module="7. Balance energético",
        title="Balance energético rápido de Colombia",
        data=summary,
        indicators=indicators,
        parameters={
            "Escenario 1": names[0],
            "Demanda escenario 1 (GWh-día)": demands[0],
            "Escenario 2": names[1],
            "Demanda escenario 2 (GWh-día)": demands[1],
            "Crecimiento anual": result["growth"],
        },
        methodology=[
            "Disponibilidad = CEN MW × factor de planta × 24 / 1.000.",
            "Factor de planta total = suma(CEN × FP) / suma(CEN).",
            "Margen = disponibilidad / demanda inicial del escenario - 1.",
            "Años hasta margen cero: Demanda₀(1+g)^n - Disponibilidad = 0.",
            "Después de despejar: n = ln(Disponibilidad/Demanda₀) / ln(1+g).",
        ],
        source="XM y supuestos editables",
        unit="MW, factores, GWh-día, años y %",
        period=str(selected_date),
        figure=availability_fig,
        figures=[("Margen energético por escenario", margin_fig)],
        additional={
            "Supuestos tecnológicos": result["inputs"],
            "Disponibilidad comparada": result["comparison"],
            "Detalle por escenario": result["scenario_rows"],
        },
        key="balance_energetico_colombia",
    )
