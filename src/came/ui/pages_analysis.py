"""Módulos 11–13: modelación, volatilidad y portafolios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.modeling import (
    fit_supervised,
    naive_forecast,
    prepare_model_matrix,
    regression_metrics,
)
from came.analytics.portfolio import (
    MAX_ITERATIONS,
    PortfolioInputs,
    historical_portfolio_parameters,
    simulate_portfolio,
)
from came.analytics.volatility import fit_sarima, fit_sarima_garch
from came.ui.charts import line, observed_estimated
from came.ui.components import export_and_collect, page_header, show_indicators, show_warnings


def _integrated_or_message() -> pd.DataFrame | None:
    data = st.session_state.get("integrated_data")
    if data is None or data.empty:
        st.info("Primero construya la base en el módulo 6. Así los modelos usan datos oficiales trazables y la misma cobertura.")
        return None
    return data.copy()


def _page_time_series_forecast(data: pd.DataFrame, numeric: list[str]) -> None:
    variable = st.selectbox("Serie objetivo", numeric, key="forecast_variable")
    model_label = st.selectbox(
        "Modelo temporal",
        ["Ingenuo", "Ingenuo estacional", "ARIMA", "SARIMA"],
    )
    horizon = st.slider("Horizonte futuro (meses)", 1, 36, 12, key="forecast_horizon")
    train_fraction = st.slider(
        "Proporción para entrenamiento cronológico",
        0.50,
        0.95,
        0.80,
        0.05,
        key="forecast_train_fraction",
    )
    p = d = q = 0
    seasonal = (0, 0, 0, 0)
    if model_label in {"ARIMA", "SARIMA"}:
        cols = st.columns(3)
        p = int(cols[0].number_input("p", 0, 5, 1, key="forecast_p"))
        d = int(cols[1].number_input("d", 0, 2, 1, key="forecast_d"))
        q = int(cols[2].number_input("q", 0, 5, 1, key="forecast_q"))
    if model_label == "SARIMA":
        cols = st.columns(4)
        seasonal = (
            int(cols[0].number_input("P", 0, 3, 0, key="forecast_P")),
            int(cols[1].number_input("D", 0, 2, 1, key="forecast_D")),
            int(cols[2].number_input("Q", 0, 3, 1, key="forecast_Q")),
            int(cols[3].number_input("s", 2, 24, 12, key="forecast_s")),
        )
    if st.button("Validar y pronosticar", type="primary", key="forecast_run"):
        try:
            series_frame = data[["datetime", variable]].dropna().sort_values("datetime")
            split = int(len(series_frame) * train_fraction)
            if split < 20 or len(series_frame) - split < 2:
                raise ValueError("Se requieren al menos 20 meses de entrenamiento y dos de validación.")
            train = series_frame.iloc[:split]
            test = series_frame.iloc[split:]
            indexed_train = pd.Series(train[variable].to_numpy(), index=train["datetime"])
            indexed_full = pd.Series(series_frame[variable].to_numpy(), index=series_frame["datetime"])
            if model_label in {"Ingenuo", "Ingenuo estacional"}:
                seasonal_period = 12 if model_label == "Ingenuo estacional" else None
                validation_prediction = naive_forecast(indexed_train, len(test), seasonal_period)
                future_prediction = naive_forecast(indexed_full, horizon, seasonal_period)
                intervals = None
                model_parameters = {"Periodo estacional": seasonal_period}
            else:
                seasonal_order = seasonal if model_label == "SARIMA" else (0, 0, 0, 0)
                validation_model = fit_sarima(
                    indexed_train,
                    order=(p, d, q),
                    seasonal_order=seasonal_order,
                    horizon=len(test),
                )
                full_model = fit_sarima(
                    indexed_full,
                    order=(p, d, q),
                    seasonal_order=seasonal_order,
                    horizon=horizon,
                )
                validation_prediction = validation_model.forecast["media"].to_numpy()
                future_prediction = full_model.forecast["media"].to_numpy()
                intervals = full_model.forecast
                model_parameters = {
                    "order": (p, d, q),
                    "seasonal_order": seasonal_order,
                    "AIC": full_model.aic,
                    "BIC": full_model.bic,
                }
            validation = pd.DataFrame(
                {
                    "datetime": test["datetime"].to_numpy(),
                    "observado": test[variable].to_numpy(),
                    "estimado": validation_prediction,
                }
            )
            metrics = regression_metrics(validation["observado"], validation["estimado"])
            future_dates = pd.date_range(
                pd.Timestamp(series_frame["datetime"].max()) + pd.offsets.MonthBegin(),
                periods=horizon,
                freq="MS",
            )
            future = pd.DataFrame({"datetime": future_dates, "media": future_prediction})
            if intervals is not None:
                for column in ("inferior_80", "superior_80", "inferior_95", "superior_95"):
                    future[column] = intervals[column].to_numpy()
            else:
                residual_sd = float((validation["observado"] - validation["estimado"]).std(ddof=1))
                future["inferior_80"] = future["media"] - 1.2815515655 * residual_sd
                future["superior_80"] = future["media"] + 1.2815515655 * residual_sd
                future["inferior_95"] = future["media"] - 1.9599639845 * residual_sd
                future["superior_95"] = future["media"] + 1.9599639845 * residual_sd
            st.session_state["forecast_result"] = {
                "validation": validation,
                "future": future,
                "metrics": metrics,
                "model": model_label,
                "variable": variable,
                "parameters": model_parameters | {"Entrenamiento": train_fraction},
                "series": series_frame,
            }
        except Exception as exc:
            st.error(str(exc))
    state = st.session_state.get("forecast_result")
    if not state:
        st.info("La validación usa el último bloque de la historia y el pronóstico se reestima con toda la serie.")
        return
    show_indicators(state["metrics"], precision=3)
    validation_fig = observed_estimated(
        state["validation"],
        title=f"Validación cronológica · {state['model']}",
        unit=state["variable"],
    )
    st.plotly_chart(validation_fig, use_container_width=True)
    forecast_fig = px.line(
        state["future"],
        x="datetime",
        y=["media", "inferior_80", "superior_80", "inferior_95", "superior_95"],
        title="Pronóstico fuera de muestra",
    )
    st.plotly_chart(forecast_fig, use_container_width=True)
    st.dataframe(state["future"], use_container_width=True, hide_index=True)
    export_and_collect(
        module="11. Modelación y pronóstico",
        title=f"{state['model']} para {state['variable']}",
        data=state["future"],
        indicators=state["metrics"],
        parameters=state["parameters"],
        methodology=[
            "La validación respeta el orden temporal y usa el bloque final como prueba.",
            "El pronóstico futuro se reestima con toda la historia válida.",
            "Los modelos ingenuos usan intervalos empíricos; ARIMA/SARIMA usan los intervalos del modelo.",
        ],
        source="Base integrada del módulo 6",
        unit=state["variable"],
        period=f"{state['series']['datetime'].min()} a {state['series']['datetime'].max()}",
        figure=forecast_fig,
        additional={"Validación": state["validation"]},
        key="pronostico_series_temporales",
    )


def page_modeling() -> None:
    page_header(
        11,
        "Laboratorio de modelación y pronóstico",
        "Compara modelos con una partición cronológica y rezagos elegidos expresamente por el usuario.",
        "Base integrada construida en el módulo 6",
    )
    data = _integrated_or_message()
    if data is None:
        return
    numeric = [column for column in data.select_dtypes(include=np.number).columns if column != "Tiempo"]
    mode = st.radio(
        "Familia de modelos",
        ["Supervisados", "Series temporales"],
        horizontal=True,
    )
    if mode == "Series temporales":
        _page_time_series_forecast(data, numeric)
        return
    target = st.selectbox("Variable objetivo", numeric)
    default_features = [column for column in numeric if column != target][:3]
    features = st.multiselect("Variables explicativas contemporáneas", [column for column in numeric if column != target], default=default_features)
    lagged = st.multiselect("Variables a rezagar", list(dict.fromkeys(features + [target])), default=[target])
    lag_labels = st.multiselect(
        "Rezagos",
        ["Periodo anterior", "Seis meses", "Un año"],
        default=["Periodo anterior"],
    )
    lag_map = {"Periodo anterior": "anterior", "Seis meses": "seis_meses", "Un año": "un_ano"}
    include_time = st.checkbox("Incluir tendencia Tiempo", value=False)
    model_label = st.selectbox("Modelo", ["Regresión lineal", "Árbol", "KNN", "Random Forest"])
    model_map = {"Regresión lineal": "linear", "Árbol": "tree", "KNN": "knn", "Random Forest": "random_forest"}
    train_fraction = st.slider("Proporción de entrenamiento", 0.50, 0.95, 0.80, 0.05)
    with st.expander("Hiperparámetros"):
        max_depth = st.number_input("Profundidad máxima", min_value=1, max_value=50, value=5)
        neighbors = st.number_input("Vecinos KNN", min_value=1, max_value=100, value=5)
        estimators = st.number_input("Árboles Random Forest", min_value=50, max_value=1000, value=300, step=50)
        standardize = st.checkbox("Estandarizar explicativas", value=model_map[model_label] == "knn")
    if st.button("Estimar y evaluar", type="primary", key="model_run"):
        try:
            matrix, feature_columns = prepare_model_matrix(
                data,
                target=target,
                features=features,
                selected_lags=[lag_map[label] for label in lag_labels],
                lagged_features=lagged,
                include_time=include_time,
                frequency="monthly",
            )
            result = fit_supervised(
                matrix,
                target=target,
                feature_columns=feature_columns,
                model=model_map[model_label],
                train_fraction=train_fraction,
                standardize=standardize,
                max_depth=int(max_depth),
                n_neighbors=int(neighbors),
                n_estimators=int(estimators),
            )
            st.session_state["model_result"] = {
                "result": result,
                "matrix": matrix,
                "target": target,
                "features": feature_columns,
                "parameters": {
                    "Modelo": model_label,
                    "Entrenamiento": train_fraction,
                    "Rezagos": lag_labels,
                    "Tiempo": include_time,
                },
            }
        except Exception as exc:
            st.error(str(exc))
    state = st.session_state.get("model_result")
    if not state:
        st.info("La estimación se ejecuta únicamente cuando se pulsa el botón.")
        return
    result = state["result"]
    show_indicators(result.metrics, precision=3)
    fig = observed_estimated(result.predictions, title=f"Validación cronológica · {result.model_name}", unit=state["target"])
    st.plotly_chart(fig, use_container_width=True)
    left, right = st.columns(2)
    left.subheader("Efectos o importancias")
    left.dataframe(result.feature_effects, use_container_width=True, hide_index=True)
    right.subheader("Residuales")
    right.plotly_chart(px.scatter(result.residuals, x="datetime", y="residual_estandarizado", title="Residual estandarizado"), use_container_width=True)
    if result.tree_rules:
        with st.expander("Reglas del árbol"):
            st.code(result.tree_rules)
    show_warnings(result.warnings)
    export_and_collect(
        module="11. Modelación y pronóstico",
        title=f"{result.model_name} para {state['target']}",
        data=result.predictions,
        indicators=result.metrics,
        parameters=state["parameters"] | {"Variables": state["features"]},
        methodology=["Partición cronológica; no se mezclan observaciones futuras en entrenamiento.", f"Intervalos: {result.interval_method}."],
        source="Base integrada del módulo 6",
        unit=state["target"],
        period=f"{state['matrix']['datetime'].min()} a {state['matrix']['datetime'].max()}",
        warnings=result.warnings,
        figure=fig,
        additional={"Matriz de modelo": state["matrix"], "Efectos": result.feature_effects, "Residuales": result.residuals},
        key="laboratorio_modelacion",
    )


def page_volatility() -> None:
    page_header(
        12,
        "Modelación de volatilidad SARIMA–GARCH",
        "SARIMA modela la media; GARCH modela la varianza condicional de sus residuales.",
        "Base integrada construida en el módulo 6",
    )
    data = _integrated_or_message()
    if data is None:
        return
    numeric = [column for column in data.select_dtypes(include=np.number).columns if column not in {"Tiempo", "Niño", "Niña"}]
    variable = st.selectbox("Serie mensual", numeric, key="vol_variable")
    series_frame = data[["datetime", variable]].dropna().copy()
    st.plotly_chart(line(series_frame.rename(columns={variable: "value"}), "value", title="Serie seleccionada", unit=variable), use_container_width=True)
    st.subheader("Órdenes")
    cols = st.columns(7)
    p = cols[0].number_input("p", 0, 5, 1)
    d = cols[1].number_input("d", 0, 2, 1)
    q = cols[2].number_input("q", 0, 5, 1)
    seasonal_p = cols[3].number_input("P", 0, 3, 0)
    seasonal_d = cols[4].number_input("D", 0, 2, 1)
    seasonal_q = cols[5].number_input("Q", 0, 3, 1)
    seasonal_s = cols[6].number_input("s", 2, 24, 12)
    horizon = st.slider("Horizonte mensual", 1, 36, 12)
    use_garch = st.checkbox("Agregar GARCH", value=True)
    gcols = st.columns(3)
    garch_p = gcols[0].number_input("GARCH p", 1, 5, 1)
    garch_q = gcols[1].number_input("GARCH q", 1, 5, 1)
    distribution = gcols[2].selectbox("Distribución", ["normal", "t"])
    if st.button("Estimar volatilidad", type="primary", key="vol_run"):
        try:
            indexed = pd.Series(series_frame[variable].to_numpy(), index=series_frame["datetime"])
            if use_garch:
                result = fit_sarima_garch(
                    indexed,
                    sarima_order=(int(p), int(d), int(q)),
                    seasonal_order=(int(seasonal_p), int(seasonal_d), int(seasonal_q), int(seasonal_s)),
                    garch_order=(int(garch_p), int(garch_q)),
                    distribution=distribution,
                    horizon=horizon,
                )
            else:
                result = fit_sarima(
                    indexed,
                    order=(int(p), int(d), int(q)),
                    seasonal_order=(int(seasonal_p), int(seasonal_d), int(seasonal_q), int(seasonal_s)),
                    horizon=horizon,
                )
            st.session_state["vol_result"] = {"result": result, "garch": use_garch, "variable": variable, "series": series_frame, "orders": ((p, d, q), (seasonal_p, seasonal_d, seasonal_q, seasonal_s), (garch_p, garch_q), distribution)}
        except Exception as exc:
            st.error(str(exc))
    state = st.session_state.get("vol_result")
    if not state:
        st.info("Para GARCH se requieren al menos 30 residuales útiles después del arranque estacional.")
        return
    result = state["result"]
    sarima = result.sarima if state["garch"] else result
    show_indicators({"AIC": sarima.aic, "BIC": sarima.bic})
    fitted = sarima.fitted.reset_index().rename(columns={sarima.fitted.index.name or "index": "datetime"})
    if "datetime" not in fitted:
        fitted.insert(0, "datetime", state["series"]["datetime"].iloc[-len(fitted):].to_numpy())
    fig = observed_estimated(fitted, title="Ajuste SARIMA", unit=state["variable"])
    st.plotly_chart(fig, use_container_width=True)
    forecast = result.combined_forecast if state["garch"] else sarima.forecast
    st.subheader("Pronóstico")
    st.dataframe(forecast, use_container_width=True, hide_index=True)
    st.subheader("Residuales originales y estandarizados")
    residuals = result.standardized_residuals.reset_index() if state["garch"] else sarima.residuals.reset_index()
    st.plotly_chart(px.line(residuals, y=[column for column in ("residual", "residual_estandarizado") if column in residuals], title="Diagnóstico de residuales"), use_container_width=True)
    warnings = result.warnings if state["garch"] else ["Las bandas SARIMA provienen del modelo de la media y sus supuestos paramétricos."]
    show_warnings(warnings)
    export_and_collect(
        module="12. SARIMA–GARCH",
        title=f"Volatilidad de {state['variable']}",
        data=forecast,
        indicators={"AIC": sarima.aic, "BIC": sarima.bic},
        parameters={"Órdenes": state["orders"], "GARCH": state["garch"]},
        methodology=["SARIMA estima la media condicional.", "Cuando está habilitado, GARCH estima la varianza de los residuales SARIMA."],
        source="Base integrada del módulo 6",
        unit=state["variable"],
        period=f"{state['series']['datetime'].min()} a {state['series']['datetime'].max()}",
        warnings=warnings,
        figure=fig,
        additional={"Ajuste": fitted, "Residuales": residuals},
        key="sarima_garch",
    )


def page_portfolio() -> None:
    page_header(
        13,
        "Portafolio de generación y simulación Monte Carlo",
        "Simula generación truncada, precio lognormal y cobertura usando los mismos sorteos en ambos escenarios.",
        "Parámetros históricos del módulo 6 o supuestos editables",
    )
    mode = st.radio("Origen de parámetros", ["Supuestos manuales", "Historia integrada"], horizontal=True)
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
        data = _integrated_or_message()
        if data is None:
            return
        gen_columns = [column for column in data if column.startswith("Generación_") and column.endswith("GWh_día")]
        if not gen_columns or "Precio_bolsa_COP_kWh" not in data:
            st.error("La base no contiene simultáneamente generación y precio de bolsa.")
            return
        generation_column = st.selectbox("Serie de generación", gen_columns)
        month = st.selectbox("Mes calendario para estimar parámetros", list(range(1, 13)), format_func=lambda value: pd.Timestamp(2000, value, 1).strftime("%B"))
        history = data[pd.to_datetime(data["datetime"]).dt.month == month].copy()
        history["Generación_mensual_GWh"] = history[generation_column] * pd.to_datetime(history["datetime"]).dt.days_in_month
        try:
            params = historical_portfolio_parameters(history["Generación_mensual_GWh"], history["Precio_bolsa_COP_kWh"])
            paired = history[["Generación_mensual_GWh", "Precio_bolsa_COP_kWh"]].dropna()
            defaults.update(params)
            defaults["generation_max_gwh"] = float(history["Generación_mensual_GWh"].max() * 1.05)
            defaults["target_correlation"] = float(paired.corr().iloc[0, 1]) if len(paired) >= 2 else 0.0
            excluded = int(params["excluded_nonpositive_prices"])
            st.caption(f"Parámetros estimados con {len(history)} observaciones del mes seleccionado; {excluded} precios no positivos excluidos.")
        except Exception as exc:
            st.error(str(exc))
            return
    cols = st.columns(3)
    generation_mean = cols[0].number_input("Media generación (GWh/mes)", min_value=0.0, value=float(defaults["generation_mean_gwh"]))
    generation_sd = cols[1].number_input("Desv. generación", min_value=0.001, value=float(defaults["generation_sd_gwh"]))
    generation_max = cols[2].number_input("Máximo generación", min_value=0.001, value=float(defaults["generation_max_gwh"]))
    cols = st.columns(3)
    price_mean = cols[0].number_input("Media precio (COP/kWh)", min_value=0.001, value=float(defaults["price_mean_cop_kwh"]))
    price_sd = cols[1].number_input("Desv. precio", min_value=0.0, value=float(defaults["price_sd_cop_kwh"]))
    correlation = cols[2].number_input("Correlación objetivo", min_value=-0.99, max_value=0.99, value=float(defaults["target_correlation"]), step=0.05)
    cols = st.columns(4)
    contract_share = cols[0].slider("Cobertura", 0.0, 1.0, 0.70, 0.05)
    contract_price = cols[1].number_input("Precio contrato (COP/kWh)", min_value=0.0, value=260.0)
    trm = cols[2].number_input("TRM (COP/USD)", min_value=1.0, value=4000.0)
    iterations = cols[3].number_input("Iteraciones", min_value=100, max_value=MAX_ITERATIONS, value=1000, step=100)
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
        st.info("Máximo permitido: 1.000.000 de iteraciones. La semilla hace reproducible el ejercicio.")
        return
    result = state["result"]
    show_indicators({"Correlación_objetivo": state["inputs"].target_correlation, "Correlación_realizada": result.realized_correlation, "Correlación_latente": result.latent_correlation})
    st.dataframe(result.summary, use_container_width=True, hide_index=True)
    st.subheader("Riesgo de cola inferior")
    st.dataframe(result.performance, use_container_width=True, hide_index=True)
    melted = result.simulations[["Ventas_sin_cobertura_millones_COP", "Ventas_con_cobertura_millones_COP"]].melt(var_name="Escenario", value_name="Ventas")
    fig = px.histogram(melted, x="Ventas", color="Escenario", barmode="overlay", opacity=.55, nbins=50, title="Distribución de ventas mensuales")
    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(px.scatter(result.simulations.sample(min(5000, len(result.simulations)), random_state=1), x="Generación_GWh", y="Precio_bolsa_COP_kWh", title="Dependencia generación–precio"), use_container_width=True)
    export_and_collect(
        module="13. Portafolio Monte Carlo",
        title="Portafolio de generación con cobertura",
        data=result.simulations,
        indicators={"Correlación objetivo": state["inputs"].target_correlation, "Correlación realizada": result.realized_correlation},
        parameters=vars(state["inputs"]),
        methodology=["Generación normal truncada por rechazo entre cero y su máximo.", "Precio lognormal; la correlación latente se calibra para aproximar la correlación objetivo después de transformar y truncar.", "Los escenarios con y sin cobertura usan exactamente los mismos sorteos."],
        source="Supuestos del usuario e historia integrada cuando se selecciona",
        unit="Millones COP y millones USD",
        period="Simulación mensual",
        figure=fig,
        additional={"Resumen": result.summary, "Percentiles": result.percentiles, "Riesgo": result.performance},
        key="portafolio_monte_carlo",
    )
