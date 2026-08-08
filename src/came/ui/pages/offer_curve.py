"""Curva de oferta rápida con CEN, factores de planta y ofertas editables."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from came.analytics.balance import (
    build_default_balance_table,
    generation_available_gwh_day,
)
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
from came.ui.loaders import xm_capacity, xm_offers


def _empty_offer_seed() -> pd.DataFrame:
    capacity = {technology: 0.0 for technology in TECHNOLOGY_ORDER[:10]}
    seed = build_default_balance_table(capacity)
    seed["Precio_COP_kWh"] = 0.0
    return seed


def _offer_seed() -> pd.DataFrame:
    """Reutiliza los supuestos del balance cuando están disponibles."""

    balance = st.session_state.get("balance_seed")
    required = {"Tecnología", "CEN_MW", "FP_normal", "FP_nino"}
    if isinstance(balance, pd.DataFrame) and required.issubset(balance.columns):
        seed = balance[["Tecnología", "CEN_MW", "FP_normal", "FP_nino"]].copy()
        seed["Precio_COP_kWh"] = 0.0
        return seed
    return _empty_offer_seed()


def _merge_percentiles(seed: pd.DataFrame, percentiles: pd.DataFrame) -> pd.DataFrame:
    percentile_columns = ["P5", "P25", "P50", "P75", "P95", "Promedio", "n"]
    clean = seed.drop(columns=percentile_columns, errors="ignore")
    merged = clean.merge(percentiles, on="Tecnología", how="left")

    def starting_price(row: pd.Series) -> float:
        statistic = default_offer_stat(str(row["Tecnología"]))
        candidate = pd.to_numeric(pd.Series([row.get(statistic)]), errors="coerce").iloc[0]
        if pd.notna(candidate):
            return float(candidate)
        previous = pd.to_numeric(
            pd.Series([row.get("Precio_COP_kWh")]), errors="coerce"
        ).iloc[0]
        return float(previous) if pd.notna(previous) else 0.0

    merged["Precio_COP_kWh"] = merged.apply(starting_price, axis=1)
    return merged


def _scenario_inputs(seed: pd.DataFrame, *, nino: bool) -> pd.DataFrame:
    factor_column = "FP_nino" if nino else "FP_normal"
    table = seed[["Tecnología", "CEN_MW", factor_column, "Precio_COP_kWh"]].copy()
    return table.rename(columns={factor_column: "Factor_planta"})


def _calculated_offer_table(table: pd.DataFrame) -> pd.DataFrame:
    calculated = table.copy()
    calculated["CEN_MW"] = pd.to_numeric(calculated["CEN_MW"], errors="coerce")
    calculated["Factor_planta"] = pd.to_numeric(
        calculated["Factor_planta"], errors="coerce"
    )
    calculated["Disponibilidad_GWh_día"] = generation_available_gwh_day(
        calculated["CEN_MW"], calculated["Factor_planta"]
    )
    return calculated[
        [
            "Tecnología",
            "CEN_MW",
            "Factor_planta",
            "Disponibilidad_GWh_día",
            "Precio_COP_kWh",
        ]
    ]


def page_offer_curve(timeout: int) -> None:
    page_header(
        8,
        "Curva de oferta rápida",
        "Construye una curva escalonada y estima el precio con ajustes lineal, cuadrático, cúbico y exponencial.",
        "XM · CapEfecNeta/Recurso y PrecOferDesp/Recurso; factores de planta editables",
    )
    left, right = st.columns(2)
    offer_start = left.date_input(
        "Inicio de ofertas", value=date.today() - timedelta(days=30), key="offer_start"
    )
    offer_end = right.date_input(
        "Fin de ofertas", value=date.today() - timedelta(days=1), key="offer_end"
    )
    if "offer_seed" not in st.session_state:
        st.session_state["offer_seed"] = _offer_seed()

    if st.button(
        "Cargar capacidad y percentiles de ofertas XM",
        type="primary",
        key="offer_live",
    ):
        seed = st.session_state["offer_seed"].copy()
        loaded = False
        try:
            capacity, effective = xm_capacity(offer_end, timeout)
            values = dict(zip(capacity["Tecnología"], capacity["CEN_MW"], strict=False))
            capacity_seed = build_default_balance_table(values)
            previous_prices = seed[["Tecnología", "Precio_COP_kWh"]].drop_duplicates(
                "Tecnología", keep="last"
            )
            seed = capacity_seed.merge(previous_prices, on="Tecnología", how="left")
            seed["Precio_COP_kWh"] = seed["Precio_COP_kWh"].fillna(0.0)
            st.session_state["offer_capacity_effective"] = effective
            loaded = True
        except Exception as exc:
            unavailable(exc, source="XM · capacidad efectiva neta")
        try:
            raw = xm_offers(offer_start, offer_end, timeout)
            percentiles = offer_percentiles(raw)
            seed = _merge_percentiles(seed, percentiles)
            st.session_state["offer_percentiles"] = percentiles
            loaded = True
        except Exception as exc:
            unavailable(exc, source="XM · precios de oferta")
        if loaded:
            st.session_state["offer_seed"] = seed[
                ["Tecnología", "CEN_MW", "FP_normal", "FP_nino", "Precio_COP_kWh"]
            ]

    effective = st.session_state.get("offer_capacity_effective")
    if effective is not None:
        st.caption(f"Capacidad efectiva publicada usada: {effective}")

    scenario_a = st.text_input("Nombre del escenario 1", value="Escenario normal")
    scenario_b = st.text_input("Nombre del escenario 2", value="Escenario El Niño")
    demand = st.number_input(
        "Demanda para el despacho (GWh-día)", min_value=0.01, value=230.0, step=1.0
    )
    real_price = st.number_input(
        "Precio real para contraste (COP/kWh, opcional; 0 = no usar)",
        min_value=0.0,
        value=0.0,
    )
    include_hydro = st.checkbox("Incluir hidráulica en los ajustes continuos", value=True)
    st.caption(
        "Disponibilidad (GWh-día) = CEN (MW) × factor de planta × 24 / 1.000. "
        "El factor es normal en el escenario 1 y de El Niño en el escenario 2."
    )

    tabs = st.tabs([scenario_a, scenario_b])
    edited_tables: list[pd.DataFrame] = []
    for index, tab in enumerate(tabs):
        with tab:
            inputs = _scenario_inputs(st.session_state["offer_seed"], nino=index == 1)
            edited = st.data_editor(
                inputs,
                num_rows="dynamic",
                width="stretch",
                key=f"offer_editor_{index}",
                column_config={
                    "CEN_MW": st.column_config.NumberColumn(
                        "Capacidad efectiva neta (MW)", min_value=0.0, format="%.2f"
                    ),
                    "Factor_planta": st.column_config.NumberColumn(
                        "Factor de planta", min_value=0.0, max_value=1.0, format="%.3f"
                    ),
                    "Precio_COP_kWh": st.column_config.NumberColumn(
                        "Precio de oferta (COP/kWh)", min_value=0.0, format="%.2f"
                    ),
                },
            )
            calculated = _calculated_offer_table(edited)
            st.markdown("**Tabla calculada del escenario**")
            st.dataframe(
                calculated,
                hide_index=True,
                width="stretch",
                column_config={
                    "CEN_MW": "Capacidad efectiva neta (MW)",
                    "Factor_planta": "Factor de planta",
                    "Disponibilidad_GWh_día": st.column_config.NumberColumn(
                        "Disponibilidad (GWh-día)", format="%.3f"
                    ),
                    "Precio_COP_kWh": "Precio de oferta (COP/kWh)",
                },
            )
            edited_tables.append(calculated)

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
                outputs.append(
                    (name, result, fits, sensitivity_table(table, base_demand=demand), table)
                )
            st.session_state["offer_results"] = outputs
        except Exception as exc:
            st.error(str(exc))
    outputs = st.session_state.get("offer_results")
    if not outputs:
        st.info(
            "Las capacidades o precios en cero son supuestos editables. Cargue XM o ingrese "
            "sus propios valores antes de estimar."
        )
        return

    combined: list[pd.DataFrame] = []
    scenario_tables: list[pd.DataFrame] = []
    last_fig = None
    for name, result, fits, sensitivity, table in outputs:
        st.subheader(name)
        show_indicators(
            {
                "Marginal_discreto_COP_kWh": result.marginal_discrete_price,
                "Tecnología_marginal": result.marginal_technology,
                "Déficit_GWh_día": result.deficit_gwh_day,
            }
        )
        last_fig = offer_curve(result.supply, demand)
        st.plotly_chart(last_fig, width="stretch")
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
            width="stretch",
            hide_index=True,
        )
        with st.expander("Sensibilidad a la demanda"):
            st.dataframe(sensitivity, width="stretch", hide_index=True)
        combined.append(fits.assign(Escenario=name))
        scenario_tables.append(table.assign(Escenario=name))

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
            "Disponibilidad = CEN MW × factor de planta × 24 / 1.000.",
            "La oferta se ordena por precio y se acumula sin extrapolar cuando existe déficit.",
            "P5 por defecto para hidráulica, solar y eólica; P50 para las demás tecnologías.",
        ],
        source="XM y supuestos editables",
        unit="MW, factor, GWh-día y COP/kWh",
        period=f"{offer_start} a {offer_end}",
        figure=last_fig,
        additional={
            "Escenarios": pd.concat(scenario_tables, ignore_index=True),
            "Percentiles XM": st.session_state.get("offer_percentiles", pd.DataFrame()),
        },
        key="curva_oferta_colombia",
    )
