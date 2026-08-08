"""Módulos 1–8: mercado colombiano."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from came.analytics.offer_curve import (
    build_offer_curve,
    offer_percentiles,
    sensitivity_table,
)
from came.config import TECHNOLOGY_ORDER, default_offer_stat
from came.ui.charts import offer_curve
from came.ui.components import (
    export_and_collect,
    page_header,
    show_indicators,
    unavailable,
)
from came.ui.loaders import (
    xm_offers,
)


def _offer_seed() -> pd.DataFrame:
    balance = st.session_state.get("balance_table")
    if balance is not None and not balance.empty:
        seed = balance[["Tecnología", "Generación_disponible_GWh_día"]].rename(
            columns={"Generación_disponible_GWh_día": "Disponibilidad_GWh_día"}
        )
        seed["Precio_COP_kWh"] = 0.0
        return seed
    return pd.DataFrame(
        {
            "Tecnología": TECHNOLOGY_ORDER[:10],
            "Disponibilidad_GWh_día": [0.0] * 10,
            "Precio_COP_kWh": [0.0] * 10,
        }
    )


def page_offer_curve(timeout: int) -> None:
    page_header(
        8,
        "Curva de oferta rápida",
        "Construye una curva escalonada y estima el precio con ajustes lineal, cuadrático, cúbico y exponencial.",
        "XM · PrecOferDesp/Recurso; disponibilidad y supuestos editables",
    )
    left, right = st.columns(2)
    offer_start = left.date_input(
        "Inicio de ofertas", value=date.today() - timedelta(days=30), key="offer_start"
    )
    offer_end = right.date_input(
        "Fin de ofertas", value=date.today() - timedelta(days=1), key="offer_end"
    )
    if st.button("Cargar percentiles de ofertas XM", type="primary", key="offer_live"):
        try:
            raw = xm_offers(offer_start, offer_end, timeout)
            percentiles = offer_percentiles(raw)
            seed = _offer_seed().merge(percentiles, on="Tecnología", how="left")
            seed["Precio_COP_kWh"] = seed.apply(
                lambda row: row.get(default_offer_stat(str(row["Tecnología"])), np.nan), axis=1
            )
            st.session_state["offer_percentiles"] = percentiles
            st.session_state["offer_seed"] = seed[
                ["Tecnología", "Disponibilidad_GWh_día", "Precio_COP_kWh"]
            ]
        except Exception as exc:
            unavailable(exc, source="XM")
    if "offer_seed" not in st.session_state:
        st.session_state["offer_seed"] = _offer_seed()
    scenario_a = st.text_input("Nombre del escenario 1", value="Escenario base")
    scenario_b = st.text_input("Nombre del escenario 2", value="Escenario alternativo")
    demand = st.number_input(
        "Demanda para el despacho (GWh-día)", min_value=0.01, value=230.0, step=1.0
    )
    real_price = st.number_input(
        "Precio real para contraste (COP/kWh, opcional; 0 = no usar)", min_value=0.0, value=0.0
    )
    include_hydro = st.checkbox("Incluir hidráulica en los ajustes continuos", value=True)
    tabs = st.tabs([scenario_a, scenario_b])
    edited_tables: list[pd.DataFrame] = []
    for index, tab in enumerate(tabs):
        with tab:
            base = st.session_state["offer_seed"].copy()
            if index == 1:
                base["Disponibilidad_GWh_día"] = (
                    pd.to_numeric(base["Disponibilidad_GWh_día"], errors="coerce").fillna(0) * 0.90
                )
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
                result = build_offer_curve(
                    table,
                    demand_gwh_day=demand,
                    real_price=real_price or None,
                    include_hydraulic=include_hydro,
                )
                fits = pd.DataFrame([vars(item) for item in result.fits])
                outputs.append((name, result, fits, sensitivity_table(table, base_demand=demand)))
            st.session_state["offer_results"] = outputs
        except Exception as exc:
            st.error(str(exc))
    outputs = st.session_state.get("offer_results")
    if not outputs:
        st.info(
            "Las filas con cero son supuestos editables. Cargue ofertas XM y una disponibilidad antes de estimar."
        )
        return
    combined: list[pd.DataFrame] = []
    last_fig = None
    for name, result, fits, sensitivity in outputs:
        st.subheader(name)
        show_indicators(
            {
                "Marginal_discreto_COP_kWh": result.marginal_discrete_price,
                "Tecnología_marginal": result.marginal_technology,
                "Déficit_GWh_día": result.deficit_gwh_day,
            }
        )
        last_fig = offer_curve(result.supply, demand)
        st.plotly_chart(last_fig, use_container_width=True)
        st.dataframe(
            fits[
                [
                    "model",
                    "equation",
                    "r2",
                    "estimated_price",
                    "absolute_error",
                    "percentage_error",
                    "warning",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
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
        parameters={
            "Escenario 1": scenario_a,
            "Escenario 2": scenario_b,
            "Incluye hidráulica": include_hydro,
        },
        methodology=[
            "La oferta se ordena por precio y se acumula sin extrapolar cuando existe déficit.",
            "P5 por defecto para hidráulica, solar y eólica; P50 para las demás tecnologías.",
        ],
        source="XM y supuestos editables",
        unit="COP/kWh y GWh-día",
        period=f"{offer_start} a {offer_end}",
        figure=last_fig,
        additional={"Percentiles XM": st.session_state.get("offer_percentiles", pd.DataFrame())},
        key="curva_oferta_colombia",
    )
