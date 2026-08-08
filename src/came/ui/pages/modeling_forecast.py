"""Módulo pedagógico de modelos supervisados y series temporales."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from scipy import stats

from came.analytics.diagnostics import (
    correlation_diagnostics,
    residual_descriptive,
    residual_diagnostics,
)
from came.analytics.modeling import (
    HYPERPARAMETER_GUIDE,
    MODEL_GUIDES,
    TRANSFORMATION_LABELS,
    fit_supervised,
    forecast_supervised,
    metrics_table,
    naive_forecast,
    prepare_model_matrix,
    regression_metrics,
    seasonal_future_defaults,
)
from came.analytics.volatility import fit_sarima
from came.ui.components import export_and_collect, page_header, show_indicators, show_warnings
from came.ui.monthly_access import ModelingData, modeling_data_or_message

TIME_SERIES_GUIDES = {
    "Ingenuo": {
        "qué_es": "Supone que el mejor pronóstico futuro es el último valor observado.",
        "ecuación": r"\widehat{Y}_{T+h}=Y_T",
        "uso": "Es un referente mínimo: un modelo más complejo debería superarlo.",
        "limitación": "No incorpora tendencia, estacionalidad ni variables explicativas.",
    },
    "Ingenuo estacional": {
        "qué_es": "Repite el valor observado en la misma posición de la temporada anterior.",
        "ecuación": r"\widehat{Y}_t=Y_{t-s}",
        "uso": "Es un referente fuerte cuando el patrón se repite cada 12 meses.",
        "limitación": "Supone que la forma estacional permanece sin cambios.",
    },
    "ARIMA": {
        "qué_es": "Combina rezagos de la serie, diferencias y errores pasados.",
        "ecuación": r"\phi(B)(1-B)^dY_t=c+\theta(B)\varepsilon_t",
        "uso": "Modela la dependencia temporal de una sola serie.",
        "limitación": "No incorpora estacionalidad explícita ni variables exógenas en esta versión.",
    },
    "SARIMA": {
        "qué_es": "Extiende ARIMA con componentes que se repiten cada s periodos.",
        "ecuación": r"\Phi(B^s)\phi(B)(1-B)^d(1-B^s)^DY_t=c+\Theta(B^s)\theta(B)\varepsilon_t",
        "uso": "Es apropiado para series mensuales con memoria y estacionalidad anual.",
        "limitación": "Una especificación grande puede ser inestable si hay poca historia.",
    },
}


def _integrated_or_message(*, key: str) -> ModelingData | None:
    return modeling_data_or_message(key=key)


def _remember_comparison(
    *, family: str, model: str, target: str, metrics: dict[str, float | None]
) -> None:
    history = st.session_state.setdefault("model_comparison_history", [])
    row = {"Familia": family, "Modelo": model, "Variable": target, **metrics}
    identity = (family, model, target)
    position = next(
        (
            index
            for index, item in enumerate(history)
            if (item.get("Familia"), item.get("Modelo"), item.get("Variable")) == identity
        ),
        None,
    )
    if position is None:
        history.append(row)
    else:
        history[position] = row


def _comparison_export(target: str, key: str) -> None:
    history = pd.DataFrame(st.session_state.get("model_comparison_history", []))
    if history.empty or "Variable" not in history:
        st.caption("Ejecute al menos dos métodos para habilitar el PDF y Excel comparativos.")
        return
    history = history[history["Variable"].eq(target)]
    if len(history) < 2:
        st.caption("Ejecute al menos dos métodos para habilitar el PDF y Excel comparativos.")
        return
    metric_columns = [
        column
        for column in ("MAE", "MSE", "RMSE", "MAPE_pct", "R2", "U_Theil", "MASE")
        if column in history
    ]
    long = history.melt(
        id_vars=["Familia", "Modelo", "Variable"],
        value_vars=metric_columns,
        var_name="Indicador",
        value_name="Valor",
    )
    figure = px.bar(
        long,
        x="Modelo",
        y="Valor",
        color="Familia",
        facet_col="Indicador",
        facet_col_wrap=3,
        title=f"Comparación de métodos · {target}",
        height=700,
    )
    figure.update_yaxes(matches=None)
    st.plotly_chart(figure, width="stretch")
    st.dataframe(history, hide_index=True, width="stretch")
    export_and_collect(
        module="11. Modelación y pronóstico",
        title=f"Comparación de modelos para {target}",
        data=history,
        indicators={"Modelos comparados": len(history)},
        parameters={"Variable": target},
        methodology=[
            "La tabla reúne los resultados más recientes de cada método ejecutado en esta sesión.",
            "Las métricas solo son directamente comparables con la misma variable, periodo y partición.",
        ],
        source="Resultados calculados durante la sesión",
        unit="Según la variable y cada indicador",
        period="Sesión actual",
        figure=figure,
        additional={"Indicadores en formato largo": long},
        key=key,
    )


def _model_explanation(title: str, guide: dict[str, str]) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(guide["qué_es"])
        st.latex(guide.get("cálculo", guide.get("ecuación", "")))
        st.caption(f"Cuándo puede servir: {guide['uso']} Limitación principal: {guide['limitación']}")


def _quality_control(data: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    dates = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    expected = pd.date_range(dates.min(), dates.max(), freq="MS", tz="UTC") if dates.notna().any() else []
    rows = [
        ("Fechas inválidas", int(dates.isna().sum())),
        ("Fechas duplicadas", int(dates.duplicated().sum())),
        ("Meses faltantes", int(len(set(expected).difference(set(dates.dropna()))))),
        ("Valores no numéricos o vacíos", int(data[variables].apply(pd.to_numeric, errors="coerce").isna().sum().sum())),
    ]
    return pd.DataFrame(rows, columns=["Control", "Cantidad"])


def _transformation_editor(variables: list[str], key: str) -> dict[str, str]:
    labels = list(TRANSFORMATION_LABELS.values())
    frame = pd.DataFrame({"Variable": variables, "Transformación": [labels[0]] * len(variables)})
    edited = st.data_editor(
        frame,
        hide_index=True,
        disabled=["Variable"],
        column_config={"Transformación": st.column_config.SelectboxColumn(options=labels, required=True)},
        key=key,
        width="stretch",
    )
    reverse = {label: code for code, label in TRANSFORMATION_LABELS.items()}
    return {str(row.Variable): reverse[str(row.Transformación)] for row in edited.itertuples()}


def _residual_figures(residuals: pd.DataFrame, acf: pd.DataFrame, pacf: pd.DataFrame) -> tuple[list[tuple[str, Any]], list[Any]]:
    clean = residuals.dropna(subset=["residual"]).copy()
    line = px.line(clean, x="datetime", y="residual", color="muestra" if "muestra" in clean else None, title="Residuales sin estandarizar")
    histogram = px.histogram(clean, x="residual", nbins=35, title="Distribución de residuales")
    theoretical, ordered = stats.probplot(clean["residual"], dist="norm", fit=False)
    qq = px.scatter(x=theoretical, y=ordered, labels={"x": "Cuantiles normales teóricos", "y": "Residuales ordenados"}, title="QQ-plot de residuales")
    if len(theoretical):
        low, high = float(min(theoretical)), float(max(theoretical))
        slope, intercept, *_ = stats.linregress(theoretical, ordered)
        qq.add_trace(go.Scatter(x=[low, high], y=[intercept + slope * low, intercept + slope * high], mode="lines", name="Referencia"))
    acf_fig = px.bar(acf, x="Rezago", y="Correlación", title="ACF de residuales")
    pacf_fig = px.bar(pacf, x="Rezago", y="Correlación", title="PACF de residuales")
    named = [("Residuales", line), ("Histograma de residuales", histogram), ("QQ-plot", qq), ("ACF de residuales", acf_fig), ("PACF de residuales", pacf_fig)]
    return named, [line, histogram, qq, acf_fig, pacf_fig]


def _tree_png(estimator: object, feature_names: list[str]) -> bytes:
    import matplotlib.pyplot as plt
    from sklearn.pipeline import Pipeline
    from sklearn.tree import plot_tree

    base = estimator.named_steps["model"] if isinstance(estimator, Pipeline) else estimator
    figure, axis = plt.subplots(figsize=(20, 10))
    plot_tree(base, feature_names=feature_names, filled=True, rounded=True, precision=3, ax=axis)
    figure.tight_layout()
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    plt.close(figure)
    return buffer.getvalue()


def _supervised_timeline(state: dict[str, Any]) -> pd.DataFrame:
    result = state["result"]
    fitted = pd.concat([result.train_predictions, result.test_predictions], ignore_index=True)
    timeline = pd.DataFrame({
        "Fecha": fitted["datetime"],
        "Tipo de dato": fitted["muestra"],
        "Histórico real": fitted["observado"],
        "Ajustado": np.where(fitted["muestra"].str.contains("Entrenamiento|Ajuste"), fitted["estimado"], np.nan),
        "Pronóstico": np.where(fitted["muestra"].eq("Prueba"), fitted["estimado"], np.nan),
        "Inferior 80 %": fitted.get("inferior_80"),
        "Superior 80 %": fitted.get("superior_80"),
        "Inferior 95 %": fitted.get("inferior_95"),
        "Superior 95 %": fitted.get("superior_95"),
        "Residual": fitted["residual"],
    })
    future = state.get("future")
    if isinstance(future, pd.DataFrame) and not future.empty:
        future_rows = pd.DataFrame({
            "Fecha": future["datetime"], "Tipo de dato": "Pronóstico futuro", "Histórico real": np.nan,
            "Ajustado": np.nan, "Pronóstico": future["pronóstico"],
            "Inferior 80 %": future.get("inferior_80"), "Superior 80 %": future.get("superior_80"),
            "Inferior 95 %": future.get("inferior_95"), "Superior 95 %": future.get("superior_95"), "Residual": np.nan,
        })
        timeline = pd.concat([timeline, future_rows], ignore_index=True)
    return timeline.sort_values("Fecha")


def _supervised_plot(timeline: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Histórico real"], name="Real", mode="lines"))
    fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Ajustado"], name="Ajustado", mode="lines"))
    fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Pronóstico"], name="Pronóstico", mode="lines+markers"))
    if timeline["Inferior 95 %"].notna().any():
        fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Superior 95 %"], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Inferior 95 %"], line=dict(width=0), fill="tonexty", name="Rango 95 %", opacity=0.18))
    fig.update_layout(title=title, xaxis_title="Fecha", yaxis_title="Valor")
    return fig


def _page_supervised(data: pd.DataFrame, numeric: list[str], monthly: ModelingData) -> None:
    target = st.selectbox("Variable objetivo", numeric, key="supervised_target")
    candidates = [column for column in numeric if column != target]
    features = st.multiselect("Variables explicativas contemporáneas", candidates, default=candidates[:3], key="supervised_features")
    lagged = st.multiselect("Variables a rezagar", list(dict.fromkeys(features + [target])), default=[target], key="supervised_lagged")
    lag_labels = st.multiselect("Rezagos", ["Periodo anterior", "Seis meses", "Un año"], default=["Periodo anterior"], key="supervised_lags")
    lag_map = {"Periodo anterior": "anterior", "Seis meses": "seis_meses", "Un año": "un_ano"}
    include_time = st.checkbox("Incluir tendencia Tiempo", value=False)
    variables_to_transform = list(dict.fromkeys([target] + features + lagged))
    st.markdown("#### Transformación individual")
    st.caption("Elija para cada variable nivel, logaritmo natural o primera diferencia. El resultado de Y volverá a su unidad original.")
    transformations = _transformation_editor(variables_to_transform, "supervised_transformations")

    model_label = st.selectbox("Modelo", [guide["nombre"] for guide in MODEL_GUIDES.values()])
    model_map = {guide["nombre"]: code for code, guide in MODEL_GUIDES.items()}
    model_code = model_map[model_label]
    _model_explanation(model_label, MODEL_GUIDES[model_code])
    reserve_test = st.checkbox("Reservar datos para prueba", value=True, key="supervised_reserve_test")
    train_fraction = st.slider("Proporción de entrenamiento cronológico", 0.50, 0.95, 0.80, 0.05, disabled=not reserve_test)
    with st.expander("Hiperparámetros y explicación", expanded=True):
        cols = st.columns(4)
        max_depth = int(cols[0].number_input("Profundidad máxima", min_value=1, max_value=50, value=4))
        neighbors = int(cols[1].number_input("Vecinos KNN", min_value=1, max_value=100, value=5))
        estimators = int(cols[2].number_input("Árboles Random Forest", min_value=50, max_value=1000, value=300, step=50))
        random_state = int(cols[3].number_input("Semilla", min_value=0, value=42))
        standardize = st.checkbox("Estandarizar explicativas", value=model_code == "knn")
        diagnostic_lags = int(st.number_input("Rezagos para ACF, PACF y Ljung-Box", min_value=1, max_value=36, value=12))
        st.dataframe(HYPERPARAMETER_GUIDE, hide_index=True, width="stretch")
    with st.expander("Control de calidad previo"):
        st.dataframe(_quality_control(data, variables_to_transform), hide_index=True, width="stretch")

    if st.button("Estimar y evaluar", type="primary", key="model_run"):
        try:
            matrix, feature_columns = prepare_model_matrix(
                data, target=target, features=features, selected_lags=[lag_map[label] for label in lag_labels],
                lagged_features=lagged, include_time=include_time, frequency="monthly", transformations=transformations,
            )
            result = fit_supervised(
                matrix, target=target, feature_columns=feature_columns, model=model_code,
                train_fraction=train_fraction, reserve_test=reserve_test, standardize=standardize,
                random_state=random_state, max_depth=max_depth, n_neighbors=neighbors,
                n_estimators=estimators, diagnostic_lags=diagnostic_lags,
            )
            st.session_state["model_result"] = {
                "result": result, "matrix": matrix, "target": target, "features": feature_columns,
                "raw_features": features, "raw_data": data, "parameters": {
                    "Modelo": model_label, "Reserva de prueba": reserve_test,
                    "Entrenamiento": train_fraction if reserve_test else "100 %", "Rezagos": lag_labels,
                    "Tiempo": include_time, "Transformaciones": transformations,
                    "Profundidad": max_depth, "Vecinos": neighbors, "Árboles": estimators, "Semilla": random_state,
                },
            }
            _remember_comparison(
                family="Supervisado",
                model=result.model_name,
                target=target,
                metrics=result.metrics,
            )
        except Exception as exc:
            st.error(str(exc))

    state = st.session_state.get("model_result")
    if not state:
        st.info("La estimación se ejecuta únicamente cuando se pulsa el botón.")
        return
    result = state["result"]
    show_indicators(result.metrics, precision=3)
    tabs = st.tabs(["Resultados", "Residuales y pruebas", "Interpretación", "Pronóstico", "Descargas"])
    with tabs[0]:
        timeline = _supervised_timeline(state)
        main_fig = _supervised_plot(timeline, f"Real, ajustado y prueba · {result.model_name}")
        st.plotly_chart(main_fig, width="stretch")
        st.dataframe(result.metrics_by_sample, hide_index=True, width="stretch")
        st.dataframe(result.predictions, hide_index=True, width="stretch")
    residual_named, residual_figs = _residual_figures(result.residuals, result.acf, result.pacf)
    with tabs[1]:
        st.plotly_chart(residual_figs[0], width="stretch")
        cols = st.columns(2)
        cols[0].plotly_chart(residual_figs[1], width="stretch")
        cols[1].plotly_chart(residual_figs[2], width="stretch")
        cols = st.columns(2)
        cols[0].plotly_chart(residual_figs[3], width="stretch")
        cols[1].plotly_chart(residual_figs[4], width="stretch")
        st.subheader("Estadística descriptiva")
        st.dataframe(result.residual_descriptive, hide_index=True, width="stretch")
        st.subheader("Pruebas diagnósticas")
        st.dataframe(result.diagnostics, hide_index=True, width="stretch")
    extra_figures: list[tuple[str, Any]] = residual_named
    with tabs[2]:
        if result.equation_general_latex:
            st.markdown("**Ecuación general**")
            st.latex(result.equation_general_latex)
            st.markdown("**Ecuación estimada**")
            st.latex(result.equation_estimated_latex)
            with st.expander("Reporte OLS completo de Statsmodels"):
                st.code(result.statsmodels_summary, language="text")
        st.subheader("Efectos o importancias")
        st.dataframe(result.feature_effects, hide_index=True, width="stretch")
        if result.model_code == "random_forest":
            st.info("La importancia interna mide cuánto reducen los árboles su criterio. La importancia por permutación mide cuánto empeora el modelo cuando se desordena una variable; esta última ayuda a comprobar su aporte predictivo.")
            st.dataframe(result.permutation_importance, hide_index=True, width="stretch")
            importance_fig = px.bar(result.permutation_importance, x="importancia_permutación", y="variable", orientation="h", title="Importancia por permutación")
            st.plotly_chart(importance_fig, width="stretch")
            extra_figures.append(("Importancia por permutación", importance_fig))
        if result.tree_rules:
            if int(state["parameters"]["Profundidad"]) <= 4:
                tree_bytes = _tree_png(result.estimator, result.feature_columns)
                st.image(tree_bytes, caption="Árbol de regresión estimado", width="stretch")
                extra_figures.append(("Árbol de regresión", tree_bytes))
            else:
                st.info("El árbol no se dibuja porque su profundidad es mayor que 4; se muestran las reglas completas.")
            with st.expander("Reglas completas del árbol", expanded=True):
                st.code(result.tree_rules)
        show_warnings(result.warnings)

    with tabs[3]:
        horizon = int(st.number_input("Horizonte de pronóstico (meses)", min_value=1, max_value=60, value=12, key="supervised_horizon"))
        exogenous = list(dict.fromkeys([item for item in state["raw_features"] if item != state["target"]] + [item for item in result.configuration.get("lagged_features", []) if item != state["target"]]))
        train_end = pd.to_datetime(result.train_predictions["datetime"], utc=True).max()
        training_history = state["raw_data"][pd.to_datetime(state["raw_data"]["datetime"], utc=True) <= train_end]
        defaults = seasonal_future_defaults(
            training_history,
            exogenous,
            horizon,
            start_after=pd.to_datetime(state["raw_data"]["datetime"], utc=True).max(),
        )
        st.caption("Cada exógena parte del promedio histórico del mismo mes calendario calculado solo con entrenamiento. Puede editar las celdas o pegar una tabla desde Excel.")
        future_inputs = st.data_editor(defaults, hide_index=True, width="stretch", key="future_exogenous_editor")
        if st.button("Pronosticar con el modelo estimado", type="primary", key="supervised_forecast_run"):
            try:
                state["future_inputs"] = future_inputs
                state["future"] = forecast_supervised(result, state["raw_data"], future_inputs)
                st.session_state["model_result"] = state
            except Exception as exc:
                st.error(str(exc))
        if isinstance(state.get("future"), pd.DataFrame):
            future = state["future"]
            st.dataframe(future, hide_index=True, width="stretch")
            forecast_fig = _supervised_plot(_supervised_timeline(state), f"Historia y pronóstico · {result.model_name}")
            st.plotly_chart(forecast_fig, width="stretch")
        if any(column.startswith(f"{state['target']}__lag_") for column in result.feature_columns):
            st.warning("Pronóstico recursivo: desde el segundo periodo se utilizan pronósticos anteriores como entradas; los errores pueden acumularse con el horizonte.")

    with tabs[4]:
        timeline = _supervised_timeline(state)
        export_fig = _supervised_plot(timeline, f"Historia, validación y pronóstico · {result.model_name}")
        additional = {
            "Histórico y pronóstico": timeline,
            "Métricas": result.metrics_by_sample,
            "Residuales": result.residuals,
            "Descriptiva residuales": result.residual_descriptive,
            "Diagnósticos": result.diagnostics,
            "ACF residuales": result.acf,
            "PACF residuales": result.pacf,
            "Efectos": result.feature_effects,
            "Importancia permutación": result.permutation_importance,
            "Matriz de modelo": state["matrix"],
            **result.statsmodels_tables,
        }
        if isinstance(state.get("future_inputs"), pd.DataFrame):
            additional["Exógenas futuras"] = state["future_inputs"]
        export_and_collect(
            module="11. Modelación y pronóstico", title=f"{result.model_name} para {state['target']}",
            data=timeline, indicators=result.metrics, parameters=state["parameters"] | {"Variables": state["features"]},
            methodology=["Partición cronológica; no se mezclan observaciones futuras en entrenamiento.", f"Intervalos: {result.interval_method}.", "Las transformaciones se eligen por variable y los resultados de Y se restituyen a la unidad original."],
            source=f"Base mensual publicada · {monthly.country_label}", unit=state["target"],
            period=f"{state['matrix']['datetime'].min()} a {state['matrix']['datetime'].max()}",
            warnings=result.warnings, figure=export_fig, figures=extra_figures, additional=additional,
            key="laboratorio_modelacion",
        )
        st.subheader("Comparación entre métodos ejecutados")
        _comparison_export(state["target"], "comparacion_modelos_supervisados")


def _transform_time_series(series: pd.Series, kind: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if kind == "none":
        return values
    if kind == "log":
        if (values.dropna() <= 0).any():
            raise ValueError("La serie contiene valores iguales o menores que cero; no puede aplicarse logaritmo natural.")
        return np.log(values)
    return values.diff()


def _inverse_future(values: np.ndarray, kind: str, baseline: float) -> np.ndarray:
    if kind == "none":
        return values
    if kind == "log":
        return np.exp(values)
    return baseline + np.cumsum(values)


def _inverse_fitted(values: np.ndarray, kind: str, original: pd.Series, index: pd.Index) -> np.ndarray:
    if kind == "none":
        return values
    if kind == "log":
        return np.exp(values)
    previous = original.shift(1).reindex(index).to_numpy(dtype=float)
    return previous + values


def _mase(observed: np.ndarray, predicted: np.ndarray, training: np.ndarray, season: int = 1) -> float | None:
    if len(training) <= season:
        return None
    denominator = float(np.mean(np.abs(training[season:] - training[:-season])))
    return float(np.mean(np.abs(observed - predicted)) / denominator) if denominator else None


def _rolling_origin_evaluation(
    original: pd.Series,
    transformed: pd.Series,
    *,
    model_label: str,
    transformation: str,
    order: tuple[int, int, int],
    seasonal_order: tuple[int, int, int, int],
    origins: int,
    diagnostic_lags: int,
) -> tuple[pd.DataFrame, dict[str, float | None]]:
    """Evalúa pronósticos de un paso con varios orígenes cronológicos crecientes."""

    season = 12 if model_label == "Ingenuo estacional" else 1
    minimum = max(20, (seasonal_order[3] + 5) if model_label == "SARIMA" else 20)
    if len(transformed) < minimum + origins:
        raise ValueError(
            f"Se requieren al menos {minimum + origins} observaciones transformadas para "
            f"evaluar {origins} orígenes móviles."
        )
    first_test = len(transformed) - origins
    rows: list[dict[str, Any]] = []
    for test_position in range(first_test, len(transformed)):
        history = transformed.iloc[:test_position]
        test_date = transformed.index[test_position]
        if model_label in {"Ingenuo", "Ingenuo estacional"}:
            predicted_transformed = naive_forecast(
                history,
                1,
                12 if model_label == "Ingenuo estacional" else None,
            )[0]
        else:
            seasonal = seasonal_order if model_label == "SARIMA" else (0, 0, 0, 0)
            estimated = fit_sarima(
                history,
                order=order,
                seasonal_order=seasonal,
                horizon=1,
                diagnostic_lags=diagnostic_lags,
            )
            predicted_transformed = float(estimated.forecast["media"].iloc[0])
        baseline = float(original.loc[history.index[-1]])
        predicted = float(
            _inverse_future(
                np.asarray([predicted_transformed]),
                transformation,
                baseline,
            )[0]
        )
        observed = float(original.loc[test_date])
        rows.append(
            {
                "Fecha": test_date,
                "Origen": history.index[-1],
                "Observado": observed,
                "Pronóstico": predicted,
                "Error": observed - predicted,
            }
        )
    evaluation = pd.DataFrame(rows)
    metrics = regression_metrics(evaluation["Observado"], evaluation["Pronóstico"])
    metrics["MASE"] = _mase(
        evaluation["Observado"].to_numpy(),
        evaluation["Pronóstico"].to_numpy(),
        original.loc[: evaluation["Origen"].min()].to_numpy(dtype=float),
        season,
    )
    return evaluation, metrics


def _time_series_plot(timeline: pd.DataFrame, title: str) -> go.Figure:
    renamed = timeline.rename(columns={"Fecha": "datetime", "Histórico real": "real", "Ajustado": "ajustado", "Pronóstico": "pronóstico"})
    fig = go.Figure()
    for column, name in (("real", "Real"), ("ajustado", "Ajustado"), ("pronóstico", "Pronóstico")):
        fig.add_trace(go.Scatter(x=renamed["datetime"], y=renamed[column], name=name, mode="lines"))
    if timeline["Inferior 95 %"].notna().any():
        fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Superior 95 %"], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=timeline["Fecha"], y=timeline["Inferior 95 %"], line=dict(width=0), fill="tonexty", name="Rango 95 %", opacity=0.18))
    fig.update_layout(title=title, xaxis_title="Fecha", yaxis_title="Valor")
    return fig


def _fit_time_series_state(
    series_frame: pd.DataFrame, variable: str, model_label: str, horizon: int, reserve_test: bool,
    train_fraction: float, transformation: str, order: tuple[int, int, int], seasonal_order: tuple[int, int, int, int], diagnostic_lags: int,
    rolling_origins: int = 0,
) -> dict[str, Any]:
    original = pd.Series(series_frame[variable].to_numpy(dtype=float), index=pd.DatetimeIndex(series_frame["datetime"]))
    transformed = _transform_time_series(original, transformation).dropna()
    split = int(len(transformed) * train_fraction) if reserve_test else len(transformed)
    if reserve_test and (split < 20 or len(transformed) - split < 2):
        raise ValueError("Se requieren al menos 20 meses de entrenamiento y dos de prueba.")
    train = transformed.iloc[:split]
    test = transformed.iloc[split:]
    full_model = None
    summary_text = ""
    parameters: dict[str, Any] = {"Transformación": TRANSFORMATION_LABELS[transformation], "Reserva de prueba": reserve_test}
    if model_label in {"Ingenuo", "Ingenuo estacional"}:
        season = 12 if model_label == "Ingenuo estacional" else 1
        fitted_transformed = transformed.shift(season).dropna()
        fitted_original = _inverse_fitted(fitted_transformed.to_numpy(), transformation, original, fitted_transformed.index)
        fitted = pd.DataFrame({"datetime": fitted_transformed.index, "observado": original.reindex(fitted_transformed.index).to_numpy(), "estimado": fitted_original})
        if reserve_test:
            validation_transformed = naive_forecast(train, len(test), 12 if model_label == "Ingenuo estacional" else None)
            validation_original = _inverse_future(validation_transformed, transformation, float(original.loc[train.index[-1]]))
        future_transformed = naive_forecast(transformed, horizon, 12 if model_label == "Ingenuo estacional" else None)
        future_original = _inverse_future(future_transformed, transformation, float(original.iloc[-1]))
        parameters["Periodo estacional"] = 12 if model_label == "Ingenuo estacional" else None
    else:
        seasonal = seasonal_order if model_label == "SARIMA" else (0, 0, 0, 0)
        if reserve_test:
            validation_model = fit_sarima(train, order=order, seasonal_order=seasonal, horizon=len(test), diagnostic_lags=diagnostic_lags)
            validation_transformed = validation_model.forecast["media"].to_numpy()
            validation_original = _inverse_future(validation_transformed, transformation, float(original.loc[train.index[-1]]))
        full_model = fit_sarima(transformed, order=order, seasonal_order=seasonal, horizon=horizon, diagnostic_lags=diagnostic_lags)
        fitted_transformed = full_model.fitted["estimado"]
        fitted_original = _inverse_fitted(fitted_transformed.to_numpy(), transformation, original, fitted_transformed.index)
        fitted = pd.DataFrame({"datetime": fitted_transformed.index, "observado": original.reindex(fitted_transformed.index).to_numpy(), "estimado": fitted_original})
        future_original = _inverse_future(full_model.forecast["media"].to_numpy(), transformation, float(original.iloc[-1]))
        parameters |= {"order": order, "seasonal_order": seasonal, "AIC": full_model.aic, "BIC": full_model.bic, "HQIC": full_model.hqic, "Convergencia": full_model.converged}
        summary_text = full_model.summary_text

    validation = pd.DataFrame()
    if reserve_test:
        validation = pd.DataFrame({"datetime": test.index, "observado": original.reindex(test.index).to_numpy(), "estimado": validation_original})
    evaluation = validation if reserve_test else fitted.dropna()
    metrics = regression_metrics(evaluation["observado"], evaluation["estimado"])
    metrics["MASE"] = _mase(evaluation["observado"].to_numpy(), evaluation["estimado"].to_numpy(), original.reindex(train.index).to_numpy(), 12 if model_label == "Ingenuo estacional" else 1)
    metric_rows = metrics_table({"Prueba" if reserve_test else "Ajuste": (evaluation["observado"], evaluation["estimado"])})
    metric_rows = pd.concat([metric_rows, pd.DataFrame([{"Muestra": "Prueba" if reserve_test else "Ajuste", "Indicador": "MASE", "Valor": metrics["MASE"], "Explicación": "Compara con el error ingenuo; menos de 1 indica una mejora frente al referente."}])], ignore_index=True)
    residuals = fitted.copy()
    residuals["residual"] = residuals["observado"] - residuals["estimado"]
    residuals["muestra"] = "Residuales del modelo"
    if reserve_test:
        validation["residual"] = validation["observado"] - validation["estimado"]
        validation["muestra"] = "Errores de prueba"
        residuals_all = pd.concat([residuals, validation], ignore_index=True)
    else:
        residuals_all = residuals
    diagnostic_values = residuals["residual"].dropna()
    acf, pacf, _ = correlation_diagnostics(diagnostic_values, diagnostic_lags)
    diagnostics = residual_diagnostics(diagnostic_values, ljung_box_lag=diagnostic_lags)
    descriptive = residual_descriptive(diagnostic_values)
    residual_sd = float(diagnostic_values.std(ddof=1))
    future_dates = pd.date_range(original.index.max() + pd.offsets.MonthBegin(), periods=horizon, freq="MS", tz="UTC")
    future = pd.DataFrame({"datetime": future_dates, "media": future_original})
    if full_model is not None:
        for column in ("inferior_80", "superior_80", "inferior_95", "superior_95"):
            future[column] = _inverse_future(full_model.forecast[column].to_numpy(), transformation, float(original.iloc[-1]))
    else:
        for level, z in ((80, 1.2815515655), (95, 1.9599639845)):
            future[f"inferior_{level}"] = future["media"] - z * residual_sd
            future[f"superior_{level}"] = future["media"] + z * residual_sd
    timeline = pd.DataFrame({"Fecha": original.index, "Tipo de dato": "Histórico", "Histórico real": original.to_numpy(), "Ajustado": np.nan, "Pronóstico": np.nan, "Inferior 80 %": np.nan, "Superior 80 %": np.nan, "Inferior 95 %": np.nan, "Superior 95 %": np.nan, "Residual": np.nan})
    fitted_map = fitted.set_index("datetime")
    timeline.loc[timeline["Fecha"].isin(fitted_map.index), "Ajustado"] = timeline.loc[timeline["Fecha"].isin(fitted_map.index), "Fecha"].map(fitted_map["estimado"])
    if reserve_test:
        validation_map = validation.set_index("datetime")
        mask = timeline["Fecha"].isin(validation_map.index)
        timeline.loc[mask, "Tipo de dato"] = "Prueba"
        timeline.loc[mask, "Pronóstico"] = timeline.loc[mask, "Fecha"].map(validation_map["estimado"])
    future_rows = pd.DataFrame({"Fecha": future["datetime"], "Tipo de dato": "Pronóstico futuro", "Histórico real": np.nan, "Ajustado": np.nan, "Pronóstico": future["media"], "Inferior 80 %": future["inferior_80"], "Superior 80 %": future["superior_80"], "Inferior 95 %": future["inferior_95"], "Superior 95 %": future["superior_95"], "Residual": np.nan})
    timeline = pd.concat([timeline, future_rows], ignore_index=True)
    rolling = pd.DataFrame()
    rolling_metrics: dict[str, float | None] = {}
    if rolling_origins:
        rolling, rolling_metrics = _rolling_origin_evaluation(
            original,
            transformed,
            model_label=model_label,
            transformation=transformation,
            order=order,
            seasonal_order=seasonal_order,
            origins=rolling_origins,
            diagnostic_lags=diagnostic_lags,
        )
        parameters["Orígenes móviles"] = rolling_origins
    warnings: list[str] = []
    if not reserve_test:
        warnings.append("No se reservó prueba: las métricas principales son de ajuste dentro de muestra.")
    if parameters.get("Convergencia") is False:
        warnings.append("Statsmodels no confirmó convergencia; pruebe una especificación más parsimoniosa.")
    ljung_box = diagnostics[diagnostics["Prueba"].eq("Ljung-Box")]
    if not ljung_box.empty and float(ljung_box["p-valor"].iloc[0]) < 0.05:
        warnings.append("Ljung-Box detecta autocorrelación residual; la dinámica del modelo puede estar incompleta.")
    return {
        "validation": validation,
        "future": future,
        "metrics": metrics,
        "metrics_table": metric_rows,
        "model": model_label,
        "variable": variable,
        "parameters": parameters,
        "series": series_frame,
        "timeline": timeline,
        "residuals": residuals_all,
        "descriptive": descriptive,
        "diagnostics": diagnostics,
        "acf": acf,
        "pacf": pacf,
        "summary_text": summary_text,
        "rolling": rolling,
        "rolling_metrics": rolling_metrics,
        "warnings": warnings,
    }


def _page_time_series_forecast(data: pd.DataFrame, numeric: list[str], monthly: ModelingData) -> None:
    variable = st.selectbox("Serie objetivo", numeric, key="forecast_variable")
    model_label = st.selectbox("Modelo temporal", list(TIME_SERIES_GUIDES), key="forecast_model")
    _model_explanation(model_label, TIME_SERIES_GUIDES[model_label])
    transformation_label = st.selectbox("Transformación de la serie", list(TRANSFORMATION_LABELS.values()), key="forecast_transformation")
    transformation = {label: code for code, label in TRANSFORMATION_LABELS.items()}[transformation_label]
    horizon = st.slider("Horizonte futuro (meses)", 1, 36, 12, key="forecast_horizon")
    reserve_test = st.checkbox("Reservar datos para prueba", value=True, key="forecast_reserve_test")
    train_fraction = st.slider("Proporción para entrenamiento cronológico", 0.50, 0.95, 0.80, 0.05, key="forecast_train_fraction", disabled=not reserve_test)
    rolling_enabled = st.checkbox(
        "Validación adicional con origen móvil",
        value=False,
        key="forecast_rolling_enabled",
        help="Reestima el método varias veces y evalúa pronósticos de un paso sin usar información futura.",
    )
    rolling_origins = int(
        st.number_input(
            "Cantidad de orígenes móviles",
            min_value=3,
            max_value=12,
            value=4,
            disabled=not rolling_enabled,
            key="forecast_rolling_origins",
        )
    )
    p = d = q = 0
    seasonal = (0, 0, 0, 0)
    if model_label in {"ARIMA", "SARIMA"}:
        st.markdown("**p**: rezagos autorregresivos · **d**: diferencias internas · **q**: errores pasados.")
        cols = st.columns(3)
        p = int(cols[0].number_input("p", 0, 5, 1, key="forecast_p"))
        d = int(cols[1].number_input("d", 0, 2, 0 if transformation == "difference" else 1, key="forecast_d", disabled=transformation == "difference"))
        q = int(cols[2].number_input("q", 0, 5, 1, key="forecast_q"))
        if transformation == "difference":
            d = 0
            st.info("La serie ya usa primera diferencia; se fija d=0 para evitar una doble diferenciación.")
    if model_label == "SARIMA":
        st.markdown("**P, D y Q** son los componentes estacionales; **s** es la longitud de la temporada.")
        cols = st.columns(4)
        seasonal = (int(cols[0].number_input("P", 0, 3, 0, key="forecast_P")), int(cols[1].number_input("D", 0, 2, 1, key="forecast_D")), int(cols[2].number_input("Q", 0, 3, 1, key="forecast_Q")), int(cols[3].number_input("s", 2, 24, 12, key="forecast_s")))
    diagnostic_lags = int(st.number_input("Rezagos para ACF, PACF y Ljung-Box", 1, 36, 12, key="forecast_diagnostic_lags"))
    series_frame = data[["datetime", variable]].dropna().sort_values("datetime")
    with st.expander("Control de calidad previo"):
        st.dataframe(_quality_control(series_frame, [variable]), hide_index=True, width="stretch")
    if st.button("Validar y pronosticar", type="primary", key="forecast_run"):
        try:
            calculated = _fit_time_series_state(
                series_frame,
                variable,
                model_label,
                horizon,
                reserve_test,
                train_fraction,
                transformation,
                (p, d, q),
                seasonal,
                diagnostic_lags,
                rolling_origins if rolling_enabled else 0,
            )
            st.session_state["forecast_result"] = calculated
            _remember_comparison(
                family="Serie temporal",
                model=calculated["model"],
                target=variable,
                metrics=calculated["metrics"],
            )
        except Exception as exc:
            st.error(str(exc))
    state = st.session_state.get("forecast_result")
    if not state:
        st.info("La aplicación respeta el orden temporal. Si desmarca test, las métricas serán de ajuste dentro de muestra.")
        return
    show_indicators(state["metrics"], precision=3)
    tabs = st.tabs(["Pronóstico", "Residuales y pruebas", "Reporte del modelo", "Descargas"])
    main_fig = _time_series_plot(state["timeline"], f"Historia y pronóstico · {state['model']}")
    with tabs[0]:
        st.plotly_chart(main_fig, width="stretch")
        st.dataframe(state["metrics_table"], hide_index=True, width="stretch")
        st.dataframe(state["future"], hide_index=True, width="stretch")
        st.caption("MASE menor que 1 indica que el modelo supera al referente ingenuo correspondiente.")
        if not state["rolling"].empty:
            st.subheader("Validación con origen móvil")
            show_indicators(state["rolling_metrics"], precision=3)
            rolling_fig = px.line(
                state["rolling"],
                x="Fecha",
                y=["Observado", "Pronóstico"],
                markers=True,
                title="Pronósticos de un paso con origen móvil",
            )
            st.plotly_chart(rolling_fig, width="stretch")
            st.dataframe(state["rolling"], hide_index=True, width="stretch")
    residual_named, residual_figs = _residual_figures(state["residuals"], state["acf"], state["pacf"])
    with tabs[1]:
        st.plotly_chart(residual_figs[0], width="stretch")
        cols = st.columns(2)
        cols[0].plotly_chart(residual_figs[1], width="stretch")
        cols[1].plotly_chart(residual_figs[2], width="stretch")
        cols = st.columns(2)
        cols[0].plotly_chart(residual_figs[3], width="stretch")
        cols[1].plotly_chart(residual_figs[4], width="stretch")
        st.dataframe(state["descriptive"], hide_index=True, width="stretch")
        st.dataframe(state["diagnostics"], hide_index=True, width="stretch")
        st.info("En ARIMA/SARIMA, los residuales del modelo estimado se distinguen de los errores del periodo de prueba.")
    with tabs[2]:
        _model_explanation(state["model"], TIME_SERIES_GUIDES[state["model"]])
        if state["summary_text"]:
            st.code(state["summary_text"], language="text")
        else:
            st.info("Los modelos ingenuos no estiman parámetros y por ello no tienen reporte de Statsmodels; se presentan fórmula, métricas y diagnósticos.")
        show_warnings(state["warnings"])
    with tabs[3]:
        export_and_collect(
            module="11. Modelación y pronóstico", title=f"{state['model']} para {state['variable']}",
            data=state["timeline"], indicators=state["metrics"], parameters=state["parameters"],
            methodology=[TIME_SERIES_GUIDES[state["model"]]["qué_es"], "El orden temporal se conserva en entrenamiento y prueba.", "El Excel integra historia, ajuste, prueba, pronóstico y rangos disponibles."],
            source=f"Base mensual publicada · {monthly.country_label}", unit=state["variable"],
            period=f"{state['series']['datetime'].min()} a {state['series']['datetime'].max()}",
            warnings=state["warnings"], figure=main_fig, figures=residual_named,
            additional={"Histórico y pronóstico": state["timeline"], "Validación": state["validation"], "Origen móvil": state["rolling"], "Métricas origen móvil": pd.DataFrame([state["rolling_metrics"]]), "Residuales": state["residuals"], "Indicadores": state["metrics_table"], "Parámetros": pd.DataFrame(list(state["parameters"].items()), columns=["Parámetro", "Valor"]), "Diagnósticos": state["diagnostics"], "Descriptiva residuales": state["descriptive"], "ACF residuales": state["acf"], "PACF residuales": state["pacf"], "Reporte Statsmodels": pd.DataFrame({"Reporte": state["summary_text"].splitlines() or ["No aplica"]})},
            key="pronostico_series_temporales",
        )
        st.subheader("Comparación entre métodos ejecutados")
        _comparison_export(state["variable"], "comparacion_modelos_series_temporales")


def page_modeling() -> None:
    page_header(11, "Laboratorio de modelación y pronóstico", "Estima, valida, diagnostica y pronostica con explicaciones visibles, transformaciones por variable y reportes reproducibles.", "Base mensual publicada del país seleccionado")
    monthly = _integrated_or_message(key="modeling")
    if monthly is None:
        return
    data = monthly.wide
    numeric = [column for column in data.select_dtypes(include=np.number).columns if column != "Tiempo"]
    mode = st.radio("Familia de modelos", ["Supervisados", "Series temporales"], horizontal=True)
    if mode == "Series temporales":
        _page_time_series_forecast(data, numeric, monthly)
    else:
        _page_supervised(data, numeric, monthly)
