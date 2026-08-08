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
from came.analytics.volatility import fit_sarima
from came.ui.charts import observed_estimated
from came.ui.components import export_and_collect, page_header, show_indicators, show_warnings
from came.ui.monthly_access import ModelingData, modeling_data_or_message


def _integrated_or_message(*, key: str) -> ModelingData | None:
    return modeling_data_or_message(key=key)


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
                raise ValueError(
                    "Se requieren al menos 20 meses de entrenamiento y dos de validación."
                )
            train = series_frame.iloc[:split]
            test = series_frame.iloc[split:]
            indexed_train = pd.Series(train[variable].to_numpy(), index=train["datetime"])
            indexed_full = pd.Series(
                series_frame[variable].to_numpy(), index=series_frame["datetime"]
            )
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
        st.info(
            "La validación usa el último bloque de la historia y el pronóstico se reestima con toda la serie."
        )
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
        source="Base mensual publicada",
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
        "Base mensual publicada del país seleccionado",
    )
    monthly = _integrated_or_message(key="modeling")
    if monthly is None:
        return
    data = monthly.wide
    numeric = [
        column for column in data.select_dtypes(include=np.number).columns if column != "Tiempo"
    ]
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
    features = st.multiselect(
        "Variables explicativas contemporáneas",
        [column for column in numeric if column != target],
        default=default_features,
    )
    lagged = st.multiselect(
        "Variables a rezagar", list(dict.fromkeys(features + [target])), default=[target]
    )
    lag_labels = st.multiselect(
        "Rezagos",
        ["Periodo anterior", "Seis meses", "Un año"],
        default=["Periodo anterior"],
    )
    lag_map = {"Periodo anterior": "anterior", "Seis meses": "seis_meses", "Un año": "un_ano"}
    include_time = st.checkbox("Incluir tendencia Tiempo", value=False)
    model_label = st.selectbox("Modelo", ["Regresión lineal", "Árbol", "KNN", "Random Forest"])
    model_map = {
        "Regresión lineal": "linear",
        "Árbol": "tree",
        "KNN": "knn",
        "Random Forest": "random_forest",
    }
    train_fraction = st.slider("Proporción de entrenamiento", 0.50, 0.95, 0.80, 0.05)
    with st.expander("Hiperparámetros"):
        max_depth = st.number_input("Profundidad máxima", min_value=1, max_value=50, value=5)
        neighbors = st.number_input("Vecinos KNN", min_value=1, max_value=100, value=5)
        estimators = st.number_input(
            "Árboles Random Forest", min_value=50, max_value=1000, value=300, step=50
        )
        standardize = st.checkbox(
            "Estandarizar explicativas", value=model_map[model_label] == "knn"
        )
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
    fig = observed_estimated(
        result.predictions,
        title=f"Validación cronológica · {result.model_name}",
        unit=state["target"],
    )
    st.plotly_chart(fig, use_container_width=True)
    left, right = st.columns(2)
    left.subheader("Efectos o importancias")
    left.dataframe(result.feature_effects, use_container_width=True, hide_index=True)
    right.subheader("Residuales")
    right.plotly_chart(
        px.scatter(
            result.residuals,
            x="datetime",
            y="residual_estandarizado",
            title="Residual estandarizado",
        ),
        use_container_width=True,
    )
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
        methodology=[
            "Partición cronológica; no se mezclan observaciones futuras en entrenamiento.",
            f"Intervalos: {result.interval_method}.",
        ],
        source=f"Base mensual publicada · {monthly.country_label}",
        unit=state["target"],
        period=f"{state['matrix']['datetime'].min()} a {state['matrix']['datetime'].max()}",
        warnings=result.warnings,
        figure=fig,
        additional={
            "Matriz de modelo": state["matrix"],
            "Efectos": result.feature_effects,
            "Residuales": result.residuals,
        },
        key="laboratorio_modelacion",
    )
