"""Módulos 11–13: modelación, volatilidad y portafolios."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.portfolio import (
    MAX_ITERATIONS,
    PortfolioInputs,
    historical_portfolio_parameters,
    simulate_portfolio,
)
from came.ui.components import export_and_collect, page_header, show_indicators
from came.ui.monthly_access import ModelingData, modeling_data_or_message


def _integrated_or_message(*, key: str) -> ModelingData | None:
    return modeling_data_or_message(key=key)


def page_portfolio() -> None:
    page_header(
        13,
        "Portafolio de generación y simulación Monte Carlo",
        "Simula generación truncada, precio lognormal y cobertura usando los mismos sorteos en ambos escenarios.",
        "Parámetros de la base mensual publicada o supuestos editables",
    )
    mode = st.radio(
        "Origen de parámetros", ["Supuestos manuales", "Historia integrada"], horizontal=True
    )
    defaults = {
        "generation_mean_gwh": 100.0,
        "generation_sd_gwh": 20.0,
        "generation_max_gwh": 180.0,
        "price_mean_cop_kwh": 250.0,
        "price_sd_cop_kwh": 90.0,
        "target_correlation": -0.20,
    }
    excluded = 0
    if mode == "Historia integrada":
        monthly = _integrated_or_message(key="portfolio")
        if monthly is None:
            return
        data = monthly.wide
        generation_ids = monthly.long[
            monthly.long["family"].eq("Generación") & monthly.long["unit"].eq("GWh-día")
        ]["series_id"].drop_duplicates()
        price_ids = monthly.long[
            monthly.long["family"].eq("Mercado")
            & monthly.long["variable"].str.contains("precio|costo", case=False, na=False)
        ]["series_id"].drop_duplicates()
        gen_columns = [monthly.labels[item] for item in generation_ids if item in monthly.labels]
        price_columns = [monthly.labels[item] for item in price_ids if item in monthly.labels]
        if not gen_columns or not price_columns:
            st.error("La base no contiene simultáneamente una serie de generación y una de precio.")
            return
        generation_column = st.selectbox("Serie de generación", gen_columns)
        price_column = st.selectbox("Serie de precio", price_columns)
        month = st.selectbox(
            "Mes calendario para estimar parámetros",
            list(range(1, 13)),
            format_func=lambda value: pd.Timestamp(2000, value, 1).strftime("%B"),
        )
        history = data[pd.to_datetime(data["datetime"]).dt.month == month].copy()
        history["Generación_mensual_GWh"] = (
            history[generation_column] * pd.to_datetime(history["datetime"]).dt.days_in_month
        )
        try:
            params = historical_portfolio_parameters(
                history["Generación_mensual_GWh"], history[price_column]
            )
            paired = history[["Generación_mensual_GWh", price_column]].dropna()
            defaults.update(params)
            defaults["generation_max_gwh"] = float(history["Generación_mensual_GWh"].max() * 1.05)
            defaults["target_correlation"] = (
                float(paired.corr().iloc[0, 1]) if len(paired) >= 2 else 0.0
            )
            excluded = int(params["excluded_nonpositive_prices"])
            st.caption(
                f"Parámetros estimados con {len(history)} observaciones del mes seleccionado; {excluded} precios no positivos excluidos."
            )
        except Exception as exc:
            st.error(str(exc))
            return
    cols = st.columns(3)
    generation_mean = cols[0].number_input(
        "Media generación (GWh/mes)", min_value=0.0, value=float(defaults["generation_mean_gwh"])
    )
    generation_sd = cols[1].number_input(
        "Desv. generación", min_value=0.001, value=float(defaults["generation_sd_gwh"])
    )
    generation_max = cols[2].number_input(
        "Máximo generación", min_value=0.001, value=float(defaults["generation_max_gwh"])
    )
    cols = st.columns(3)
    price_mean = cols[0].number_input(
        "Media precio (COP/kWh)", min_value=0.001, value=float(defaults["price_mean_cop_kwh"])
    )
    price_sd = cols[1].number_input(
        "Desv. precio", min_value=0.0, value=float(defaults["price_sd_cop_kwh"])
    )
    correlation = cols[2].number_input(
        "Correlación objetivo",
        min_value=-0.99,
        max_value=0.99,
        value=float(defaults["target_correlation"]),
        step=0.05,
    )
    cols = st.columns(4)
    contract_share = cols[0].slider("Cobertura", 0.0, 1.0, 0.70, 0.05)
    contract_price = cols[1].number_input("Precio contrato (COP/kWh)", min_value=0.0, value=260.0)
    trm = cols[2].number_input("TRM (COP/USD)", min_value=1.0, value=4000.0)
    iterations = cols[3].number_input(
        "Iteraciones", min_value=100, max_value=MAX_ITERATIONS, value=1000, step=100
    )
    seed = st.number_input("Semilla reproducible", min_value=0, value=42)
    if st.button("Simular portafolio", type="primary", key="portfolio_run"):
        try:
            inputs = PortfolioInputs(
                generation_mean_gwh=generation_mean,
                generation_sd_gwh=generation_sd,
                generation_max_gwh=generation_max,
                price_mean_cop_kwh=price_mean,
                price_sd_cop_kwh=price_sd,
                target_correlation=correlation,
                contract_share=contract_share,
                contract_price_cop_kwh=contract_price,
                iterations=int(iterations),
                trm_cop_usd=trm,
                seed=int(seed),
            )
            with st.spinner("Calibrando correlación y ejecutando sorteos…"):
                result = simulate_portfolio(inputs)
            result.excluded_nonpositive_prices = excluded
            st.session_state["portfolio_result"] = {"result": result, "inputs": inputs}
        except Exception as exc:
            st.error(str(exc))
    state = st.session_state.get("portfolio_result")
    if not state:
        st.info(
            "Máximo permitido: 1.000.000 de iteraciones. La semilla hace reproducible el ejercicio."
        )
        return
    result = state["result"]
    show_indicators(
        {
            "Correlación_objetivo": state["inputs"].target_correlation,
            "Correlación_realizada": result.realized_correlation,
            "Correlación_latente": result.latent_correlation,
        }
    )
    st.dataframe(result.summary, use_container_width=True, hide_index=True)
    st.subheader("Riesgo de cola inferior")
    st.dataframe(result.performance, use_container_width=True, hide_index=True)
    melted = result.simulations[
        ["Ventas_sin_cobertura_millones_COP", "Ventas_con_cobertura_millones_COP"]
    ].melt(var_name="Escenario", value_name="Ventas")
    fig = px.histogram(
        melted,
        x="Ventas",
        color="Escenario",
        barmode="overlay",
        opacity=0.55,
        nbins=50,
        title="Distribución de ventas mensuales",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(
        px.scatter(
            result.simulations.sample(min(5000, len(result.simulations)), random_state=1),
            x="Generación_GWh",
            y="Precio_bolsa_COP_kWh",
            title="Dependencia generación–precio",
        ),
        use_container_width=True,
    )
    export_and_collect(
        module="13. Portafolio Monte Carlo",
        title="Portafolio de generación con cobertura",
        data=result.simulations,
        indicators={
            "Correlación objetivo": state["inputs"].target_correlation,
            "Correlación realizada": result.realized_correlation,
        },
        parameters=vars(state["inputs"]),
        methodology=[
            "Generación normal truncada por rechazo entre cero y su máximo.",
            "Precio lognormal; la correlación latente se calibra para aproximar la correlación objetivo después de transformar y truncar.",
            "Los escenarios con y sin cobertura usan exactamente los mismos sorteos.",
        ],
        source="Supuestos del usuario y base mensual publicada cuando se selecciona",
        unit="Millones COP y millones USD",
        period="Simulación mensual",
        figure=fig,
        additional={
            "Resumen": result.summary,
            "Percentiles": result.percentiles,
            "Riesgo": result.performance,
        },
        key="portafolio_monte_carlo",
    )
