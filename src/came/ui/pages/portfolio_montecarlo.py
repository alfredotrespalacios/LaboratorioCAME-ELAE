"""Cálculo rápido Monte Carlo de generación, precio y contratación."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.portfolio import (
    MAX_ITERATIONS,
    SENSITIVITY_METRICS,
    PortfolioInputs,
    historical_portfolio_parameters,
    sensitivity_contract_correlation,
    sensitivity_contract_price,
    sensitivity_contract_share,
    simulate_portfolio,
)
from came.ui.components import export_and_collect, page_header, show_indicators
from came.ui.monthly_access import ModelingData, modeling_data_or_message


def _integrated_or_message(*, key: str) -> ModelingData | None:
    return modeling_data_or_message(key=key)


def _inputs() -> tuple[PortfolioInputs, int] | None:
    mode = st.radio("Origen de parámetros", ["Supuestos manuales", "Historia integrada"], horizontal=True)
    defaults: dict[str, float] = {
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
            return None
        data = monthly.wide
        generation_ids = monthly.long[monthly.long["family"].eq("Generación") & monthly.long["unit"].eq("GWh-día")]["series_id"].drop_duplicates()
        price_ids = monthly.long[monthly.long["family"].eq("Mercado") & monthly.long["variable"].str.contains("precio|costo", case=False, na=False)]["series_id"].drop_duplicates()
        gen_columns = [monthly.labels[item] for item in generation_ids if item in monthly.labels]
        price_columns = [monthly.labels[item] for item in price_ids if item in monthly.labels]
        if not gen_columns or not price_columns:
            st.error("La base no contiene simultáneamente una serie de generación y una de precio.")
            return None
        generation_column = st.selectbox("Serie de generación", gen_columns)
        price_column = st.selectbox("Serie de precio", price_columns)
        month = st.selectbox("Mes calendario para estimar parámetros", list(range(1, 13)), format_func=lambda value: pd.Timestamp(2000, value, 1).strftime("%B"))
        history = data[pd.to_datetime(data["datetime"]).dt.month == month].copy()
        history["Generación_mensual_GWh"] = history[generation_column] * pd.to_datetime(history["datetime"]).dt.days_in_month
        try:
            params = historical_portfolio_parameters(history["Generación_mensual_GWh"], history[price_column])
            paired = history[["Generación_mensual_GWh", price_column]].dropna()
            defaults.update(params)
            defaults["generation_max_gwh"] = float(history["Generación_mensual_GWh"].max() * 1.05)
            defaults["target_correlation"] = float(paired.corr().iloc[0, 1]) if len(paired) >= 2 else 0.0
            excluded = int(params["excluded_nonpositive_prices"])
            st.caption(f"Parámetros estimados con {len(history)} observaciones del mes seleccionado; {excluded} precios no positivos excluidos.")
        except Exception as exc:
            st.error(str(exc))
            return None
    cols = st.columns(3)
    generation_mean = cols[0].number_input("Media generación esperada (GWh/mes)", min_value=0.0, value=float(defaults["generation_mean_gwh"]))
    generation_sd = cols[1].number_input("Desv. generación", min_value=0.001, value=float(defaults["generation_sd_gwh"]))
    generation_max = cols[2].number_input("Máximo generación", min_value=0.001, value=float(defaults["generation_max_gwh"]))
    cols = st.columns(3)
    price_mean = cols[0].number_input("Media precio (COP/kWh)", min_value=0.001, value=float(defaults["price_mean_cop_kwh"]))
    price_sd = cols[1].number_input("Desv. precio", min_value=0.0, value=float(defaults["price_sd_cop_kwh"]))
    correlation = cols[2].number_input("Correlación fija", min_value=-0.99, max_value=0.99, value=float(defaults["target_correlation"]), step=0.05)
    cols = st.columns(5)
    contract_share = cols[0].number_input("Porcentaje contratado", min_value=-2.0, max_value=2.0, value=0.70, step=0.10, format="%.2f")
    contract_price = cols[1].number_input("Precio contrato", min_value=0.0, value=260.0)
    trm = cols[2].number_input("TRM (COP/USD)", min_value=1.0, value=4000.0)
    iterations = int(cols[3].number_input("Iteraciones", min_value=100, max_value=MAX_ITERATIONS, value=1000, step=100))
    seed = int(cols[4].number_input("Semilla", min_value=0, value=42))
    st.info("Volumen contratado = porcentaje contratado × generación esperada. Más de 100 % representa sobrecontratación; un porcentaje negativo representa una posición compradora en contratos.")
    return (
        PortfolioInputs(
            generation_mean_gwh=generation_mean,
            generation_sd_gwh=generation_sd,
            generation_max_gwh=generation_max,
            price_mean_cop_kwh=price_mean,
            price_sd_cop_kwh=price_sd,
            target_correlation=correlation,
            contract_share=contract_share,
            contract_price_cop_kwh=contract_price,
            iterations=iterations,
            trm_cop_usd=trm,
            seed=seed,
        ),
        excluded,
    )


def _sensitivity_figure(frame: pd.DataFrame, color: str | None, title: str):
    id_columns = ["Porcentaje contratado"] + ([color] if color else [])
    long = frame.melt(id_vars=id_columns, value_vars=list(SENSITIVITY_METRICS), var_name="Indicador", value_name="Valor")
    fig = px.line(
        long,
        x="Porcentaje contratado",
        y="Valor",
        color=color,
        facet_row="Indicador",
        markers=True,
        title=title,
        height=1250,
    )
    fig.update_yaxes(matches=None, title_text="")
    fig.for_each_annotation(lambda annotation: annotation.update(text=annotation.text.split("=")[-1]))
    fig.update_xaxes(tickformat=".0%")
    return fig


def _export_sensitivity(frame: pd.DataFrame, inputs: PortfolioInputs, title: str, figure: Any, key: str, methodology: list[str]) -> None:
    export_and_collect(
        module="13. Cálculo rápido de portafolios",
        title=title,
        data=frame,
        indicators={"Combinaciones": len(frame), "Iteraciones por escenario": inputs.iterations},
        parameters=asdict(inputs),
        methodology=methodology + ["VaR es el percentil 5 % de los resultados; CVaR es el promedio del 5 % inferior; M-CVaR = Media − CVaR.", "Las combinaciones reutilizan los mismos sorteos base de la semilla."],
        source="Supuestos del usuario y base mensual cuando se selecciona",
        unit="Millones COP",
        period="Simulación mensual",
        figure=figure,
        additional={"Resultados": frame},
        key=key,
    )


def page_portfolio() -> None:
    page_header(
        13,
        "Cálculo rápido de portafolios de generación",
        "Simula generación, precio y contratación; después evalúa sensibilidades manteniendo comparables los escenarios aleatorios.",
        "Parámetros de la base mensual publicada o supuestos editables",
    )
    resolved = _inputs()
    if resolved is None:
        return
    inputs, excluded = resolved
    tabs = st.tabs(["1. Simulación individual", "2. Sensibilidad contratación", "3. Contratación–correlación", "4. Contratación–precio"])

    with tabs[0]:
        if st.button("Simular portafolio", type="primary", key="portfolio_run"):
            try:
                with st.spinner("Calibrando correlación y ejecutando sorteos…"):
                    result = simulate_portfolio(inputs)
                result.excluded_nonpositive_prices = excluded
                st.session_state["portfolio_result"] = {"result": result, "inputs": inputs}
            except Exception as exc:
                st.error(str(exc))
        state = st.session_state.get("portfolio_result")
        if state:
            result = state["result"]
            show_indicators({"Correlación objetivo": inputs.target_correlation, "Correlación realizada": result.realized_correlation, "Correlación latente": result.latent_correlation})
            st.dataframe(result.summary, hide_index=True, width="stretch")
            st.subheader("Riesgo de cola inferior")
            st.dataframe(result.performance, hide_index=True, width="stretch")
            sales = result.simulations[["Ventas_sin_cobertura_millones_COP", "Ventas_con_cobertura_millones_COP"]].melt(var_name="Escenario", value_name="Ventas")
            sales_fig = px.histogram(sales, x="Ventas", color="Escenario", barmode="overlay", opacity=0.55, nbins=50, title="Distribución de resultados mensuales")
            generation_fig = px.histogram(result.simulations, x="Generación_GWh", nbins=50, title="Generación simulada")
            price_fig = px.histogram(result.simulations, x="Precio_bolsa_COP_kWh", nbins=50, title="Precio de bolsa simulado")
            st.plotly_chart(sales_fig, width="stretch")
            cols = st.columns(2)
            cols[0].plotly_chart(generation_fig, width="stretch")
            cols[1].plotly_chart(price_fig, width="stretch")
            scatter_fig = px.scatter(result.simulations.sample(min(5000, len(result.simulations)), random_state=1), x="Generación_GWh", y="Precio_bolsa_COP_kWh", title="Dependencia generación–precio")
            st.plotly_chart(scatter_fig, width="stretch")
            export_and_collect(
                module="13. Cálculo rápido de portafolios",
                title="Portafolio de generación con contratación",
                data=result.simulations,
                indicators={"Correlación objetivo": inputs.target_correlation, "Correlación realizada": result.realized_correlation},
                parameters=asdict(inputs),
                methodology=["Generación normal truncada entre cero y su máximo.", "Precio lognormal; la correlación latente se calibra para aproximar la correlación objetivo.", "Los escenarios con y sin contratación usan los mismos sorteos.", "VaR y CVaR se expresan como resultados financieros y pueden ser negativos."],
                source="Supuestos del usuario y base mensual publicada cuando se selecciona",
                unit="Millones COP y millones USD",
                period="Simulación mensual",
                figure=sales_fig,
                figures=[("Generación simulada", generation_fig), ("Precio de bolsa simulado", price_fig), ("Dependencia generación–precio", scatter_fig)],
                additional={"Resumen": result.summary, "Percentiles": result.percentiles, "Riesgo": result.performance},
                key="portafolio_monte_carlo",
            )
        else:
            st.info("La simulación individual conserva fijos contratación, correlación y precio contractual.")

    with tabs[1]:
        cols = st.columns(2)
        share_min = cols[0].number_input("Contratación mínima", min_value=-2.0, max_value=2.0, value=0.0, step=0.10, key="share_min")
        share_max = cols[1].number_input("Contratación máxima", min_value=-2.0, max_value=2.0, value=1.0, step=0.10, key="share_max")
        shares = np.linspace(share_min, share_max, 10)
        st.dataframe(pd.DataFrame({"Porcentaje contratado": shares}), hide_index=True)
        if st.button("Calcular sensibilidad a contratación", type="primary", key="share_run"):
            try:
                st.session_state["share_sensitivity"] = sensitivity_contract_share(inputs, shares)
            except Exception as exc:
                st.error(str(exc))
        frame = st.session_state.get("share_sensitivity")
        if isinstance(frame, pd.DataFrame):
            fig = _sensitivity_figure(frame, None, "Sensibilidad al porcentaje contratado")
            st.plotly_chart(fig, width="stretch")
            st.dataframe(frame, hide_index=True, width="stretch")
            _export_sensitivity(frame, inputs, "Sensibilidad al porcentaje contratado", fig, "sensibilidad_contratacion", ["Correlación y precio contractual permanecen fijos."])

    with tabs[2]:
        defaults = pd.DataFrame({"Correlación": np.linspace(-0.7, 0.7, 5)})
        correlations_frame = st.data_editor(defaults, hide_index=True, width="stretch", key="correlation_values")
        corr_share_min = st.number_input("Contratación mínima", -2.0, 2.0, 0.0, 0.10, key="corr_share_min")
        corr_share_max = st.number_input("Contratación máxima", -2.0, 2.0, 1.0, 0.10, key="corr_share_max")
        corr_shares = np.linspace(corr_share_min, corr_share_max, 10)
        if st.button("Calcular contratación–correlación", type="primary", key="corr_run"):
            try:
                st.session_state["corr_sensitivity"] = sensitivity_contract_correlation(inputs, corr_shares, correlations_frame["Correlación"])
            except Exception as exc:
                st.error(str(exc))
        frame = st.session_state.get("corr_sensitivity")
        if isinstance(frame, pd.DataFrame):
            frame = frame.copy()
            frame["Correlación (serie)"] = frame["Correlación"].map(lambda value: f"{value:.2f}")
            fig = _sensitivity_figure(frame, "Correlación (serie)", "Sensibilidad conjunta contratación–correlación")
            st.plotly_chart(fig, width="stretch")
            st.dataframe(frame.drop(columns="Correlación (serie)"), hide_index=True, width="stretch")
            _export_sensitivity(frame.drop(columns="Correlación (serie)"), inputs, "Sensibilidad contratación–correlación", fig, "sensibilidad_contratacion_correlacion", ["Se evalúan diez porcentajes para cada una de cinco correlaciones editables."])

    with tabs[3]:
        cols = st.columns(2)
        price_min = cols[0].number_input("Precio contractual mínimo", min_value=0.0, value=max(0.0, inputs.contract_price_cop_kwh * 0.8), key="contract_price_min")
        price_max = cols[1].number_input("Precio contractual máximo", min_value=0.0, value=inputs.contract_price_cop_kwh * 1.2, key="contract_price_max")
        prices = np.linspace(price_min, price_max, 5)
        price_share_min = st.number_input("Contratación mínima", -2.0, 2.0, 0.0, 0.10, key="price_share_min")
        price_share_max = st.number_input("Contratación máxima", -2.0, 2.0, 1.0, 0.10, key="price_share_max")
        price_shares = np.linspace(price_share_min, price_share_max, 10)
        st.caption("Se generan cinco precios equidistantes. La correlación permanece fija en el valor de la simulación individual.")
        if st.button("Calcular contratación–precio", type="primary", key="price_run"):
            try:
                st.session_state["price_sensitivity"] = sensitivity_contract_price(inputs, price_shares, prices)
            except Exception as exc:
                st.error(str(exc))
        frame = st.session_state.get("price_sensitivity")
        if isinstance(frame, pd.DataFrame):
            frame = frame.copy()
            frame["Precio (serie)"] = frame["Precio contrato COP/kWh"].map(lambda value: f"{value:,.2f}")
            fig = _sensitivity_figure(frame, "Precio (serie)", "Sensibilidad conjunta contratación–precio")
            st.plotly_chart(fig, width="stretch")
            st.dataframe(frame.drop(columns="Precio (serie)"), hide_index=True, width="stretch")
            _export_sensitivity(frame.drop(columns="Precio (serie)"), inputs, "Sensibilidad contratación–precio contractual", fig, "sensibilidad_contratacion_precio", ["Se evalúan diez porcentajes para cada uno de cinco precios equidistantes; la correlación permanece fija."])
