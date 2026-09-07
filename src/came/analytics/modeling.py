"""Modelos pedagógicos con transformaciones por variable y validación temporal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor, export_text

from came.analytics.diagnostics import (
    correlation_diagnostics,
    residual_descriptive,
    residual_diagnostics,
)
from came.errors import DataQualityError, ModelError

TRANSFORMATION_LABELS = {
    "none": "Sin transformar",
    "log": "Logaritmo natural",
    "difference": "Primera diferencia",
}

TRANSFORMATION_ALIASES = {
    "sin transformar": "none",
    "nivel": "none",
    "none": "none",
    "logaritmo natural": "log",
    "log": "log",
    "ln": "log",
    "primera diferencia": "difference",
    "diferencia": "difference",
    "difference": "difference",
}

METRIC_EXPLANATIONS = {
    "MAE": "Error absoluto promedio; conserva la unidad de la variable.",
    "MSE": "Promedio de errores al cuadrado; penaliza más los errores grandes.",
    "RMSE": "Raíz del MSE; vuelve a la unidad original y penaliza errores grandes.",
    "MAPE_pct": "Error porcentual absoluto medio; no se calcula sobre valores reales iguales a cero.",
    "R2": "Proporción de variabilidad explicada; puede ser negativa fuera de muestra.",
    "U_Theil": "Error relativo de Theil; cuanto más cercano a cero, mejor.",
}

MODEL_GUIDES = {
    "linear": {
        "nombre": "Regresión lineal",
        "qué_es": "Estima una combinación lineal de las variables explicativas.",
        "cálculo": r"\widehat{Y}_t=\widehat{\beta}_0+\sum_{j=1}^{k}\widehat{\beta}_jX_{j,t}",
        "uso": "Es útil cuando se busca una relación interpretable y aproximadamente lineal.",
        "limitación": "Puede representar mal relaciones no lineales y es sensible a observaciones influyentes.",
    },
    "tree": {
        "nombre": "Árbol de regresión",
        "qué_es": "Divide los datos mediante reglas sucesivas y asigna una predicción a cada hoja.",
        "cálculo": r"\widehat{Y}(x)=\frac{1}{|R_m|}\sum_{i:x_i\in R_m}Y_i",
        "uso": "Captura relaciones no lineales y reglas fáciles de expresar.",
        "limitación": "Un árbol profundo puede sobreajustar y cambiar mucho ante pequeñas variaciones.",
    },
    "knn": {
        "nombre": "KNN",
        "qué_es": "Pronostica con los k casos históricos más parecidos.",
        "cálculo": r"\widehat{Y}(x)=\frac{\sum_{i\in N_k(x)}w_iY_i}{\sum_{i\in N_k(x)}w_i}",
        "uso": "Es útil cuando observaciones cercanas tienden a tener resultados parecidos.",
        "limitación": "Depende de la escala, de k y de que el futuro sea comparable con la historia.",
    },
    "random_forest": {
        "nombre": "Random Forest",
        "qué_es": "Promedia muchos árboles construidos con muestras y subconjuntos de variables.",
        "cálculo": r"\widehat{Y}(x)=\frac{1}{B}\sum_{b=1}^{B}\widehat{Y}_b(x)",
        "uso": "Suele capturar relaciones no lineales con menor inestabilidad que un solo árbol.",
        "limitación": "Es menos interpretable y no extrapola bien más allá del rango histórico.",
    },
}

HYPERPARAMETER_GUIDE = pd.DataFrame(
    [
        ("Periodo de evaluación", "Tramo inicial usado para calibrar el modelo evaluado; el bloque final queda fuera de muestra.", "Todos, si se evalúa"),
        ("Estandarizar", "Centra y divide por la desviación calculada solo con entrenamiento.", "Especialmente KNN"),
        ("Profundidad máxima", "Número máximo de niveles de cada árbol; más profundidad aumenta flexibilidad y riesgo de sobreajuste.", "Árbol y Random Forest"),
        ("Número de vecinos", "Cantidad de observaciones cercanas utilizadas en cada predicción.", "KNN"),
        ("Número de árboles", "Cantidad de árboles promediados; más árboles estabilizan a costa de tiempo.", "Random Forest"),
        ("Semilla", "Fija los sorteos internos para que el resultado sea reproducible.", "Árbol y Random Forest"),
        ("Rezagos", "Valores pasados usados como explicativas; permiten incorporar memoria temporal.", "Todos"),
    ],
    columns=["Hiperparámetro", "Significado", "Métodos"],
)


@dataclass
class SupervisedResult:
    model_name: str
    estimator: object
    predictions: pd.DataFrame
    metrics: dict[str, float | None]
    feature_effects: pd.DataFrame
    residuals: pd.DataFrame
    interval_method: str
    warnings: list[str] = field(default_factory=list)
    tree_rules: str | None = None
    train_predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    test_predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    metrics_by_sample: pd.DataFrame = field(default_factory=pd.DataFrame)
    permutation_importance: pd.DataFrame = field(default_factory=pd.DataFrame)
    residual_descriptive: pd.DataFrame = field(default_factory=pd.DataFrame)
    diagnostics: pd.DataFrame = field(default_factory=pd.DataFrame)
    acf: pd.DataFrame = field(default_factory=pd.DataFrame)
    pacf: pd.DataFrame = field(default_factory=pd.DataFrame)
    equation_general_latex: str = ""
    equation_estimated_latex: str = ""
    statsmodels_summary: str = ""
    statsmodels_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    model_code: str = ""
    target: str = ""
    feature_columns: list[str] = field(default_factory=list)
    reserve_test: bool = True
    configuration: dict[str, Any] = field(default_factory=dict)
    prepared_data: pd.DataFrame = field(default_factory=pd.DataFrame)


LAG_LABELS = {"anterior": "1", "seis_meses": "6", "un_ano": "12"}
LAG_PERIODS = {"anterior": 1, "seis_meses": 6, "un_ano": 12}
ORIGINAL_TARGET_COLUMN = "__objetivo_original__"


def select_historical_window(
    frame: pd.DataFrame,
    start: object,
    end: object,
) -> pd.DataFrame:
    """Selecciona inclusivamente el histórico que podrá calibrarse y evaluarse."""

    if "datetime" not in frame:
        raise DataQualityError("La base debe contener la columna datetime.")
    data = frame.copy()
    dates = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    start_timestamp = pd.Timestamp(start)
    end_timestamp = pd.Timestamp(end)
    start_timestamp = (
        start_timestamp.tz_localize("UTC")
        if start_timestamp.tzinfo is None
        else start_timestamp.tz_convert("UTC")
    )
    end_timestamp = (
        end_timestamp.tz_localize("UTC")
        if end_timestamp.tzinfo is None
        else end_timestamp.tz_convert("UTC")
    )
    # Una fecha final sin hora representa el día completo.
    if end_timestamp == end_timestamp.normalize():
        end_timestamp = end_timestamp + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    selected = data.loc[dates.between(start_timestamp, end_timestamp)].copy()
    selected["datetime"] = dates.loc[selected.index]
    selected = selected.sort_values("datetime").drop_duplicates("datetime").reset_index(drop=True)
    if selected.empty:
        raise DataQualityError("El periodo histórico seleccionado no contiene observaciones.")
    return selected


def evaluation_split_index(
    dates: object,
    *,
    test_periods: int | None = None,
    test_start: object | None = None,
    minimum_training: int = 5,
    minimum_test: int = 2,
) -> int:
    """Devuelve el primer índice de prueba para una separación cronológica exacta."""

    ordered = pd.Series(pd.to_datetime(dates, errors="coerce", utc=True)).dropna()
    if ordered.empty:
        raise DataQualityError("No hay fechas válidas para definir la evaluación.")
    if not ordered.is_monotonic_increasing:
        raise DataQualityError("Las fechas deben estar ordenadas para separar la prueba.")
    if test_start is not None:
        start = pd.Timestamp(test_start)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        positions = np.flatnonzero((ordered >= start).to_numpy())
        if not len(positions):
            raise DataQualityError("La fecha inicial de prueba queda después del histórico.")
        split = int(positions[0])
    elif test_periods is not None:
        if int(test_periods) < minimum_test:
            raise DataQualityError(
                f"La prueba debe contener al menos {minimum_test} periodos."
            )
        split = len(ordered) - int(test_periods)
    else:
        raise DataQualityError("Defina la prueba mediante fecha inicial o número de periodos.")
    if split < minimum_training:
        raise DataQualityError(
            f"La calibración para evaluación debe conservar al menos {minimum_training} observaciones."
        )
    if len(ordered) - split < minimum_test:
        raise DataQualityError(f"La prueba debe contener al menos {minimum_test} observaciones.")
    return split


def normalize_transformation(value: object) -> str:
    key = str(value or "none").strip().casefold()
    if key not in TRANSFORMATION_ALIASES:
        raise DataQualityError(f"Transformación no reconocida: {value}.")
    return TRANSFORMATION_ALIASES[key]


def _lag_offset(frequency: str, lag: str) -> pd.DateOffset:
    periods = LAG_PERIODS.get(lag)
    if periods is None:
        raise ValueError(f"Rezago no reconocido: {lag}")
    if frequency == "monthly":
        return pd.DateOffset(months=periods)
    if frequency == "daily":
        return pd.DateOffset(days=periods)
    if frequency == "hourly":
        return pd.DateOffset(hours=periods)
    if frequency == "annual":
        return pd.DateOffset(years=periods)
    raise ValueError(f"Frecuencia no reconocida: {frequency}")


def _transform_series(series: pd.Series, kind: str, variable: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if kind == "none":
        return values
    if kind == "log":
        invalid = values.notna() & values.le(0)
        if invalid.any():
            raise DataQualityError(
                f"{variable} contiene {int(invalid.sum())} valores iguales o menores que cero; no puede aplicarse logaritmo natural."
            )
        return np.log(values)
    if kind == "difference":
        return values.diff()
    raise DataQualityError(f"Transformación no soportada para {variable}: {kind}.")


def prepare_model_matrix(
    frame: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    selected_lags: list[str] | None = None,
    lagged_features: list[str] | None = None,
    include_time: bool = False,
    frequency: str = "monthly",
    transformations: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Alinea fechas, aplica una transformación por variable y agrega rezagos elegidos."""

    if "datetime" not in frame or target not in frame:
        raise DataQualityError("La base debe contener datetime y la variable objetivo.")
    selected_lags = selected_lags or []
    lagged_features = lagged_features if lagged_features is not None else list(features)
    requested = list(dict.fromkeys([target] + features + lagged_features))
    missing = [column for column in requested if column not in frame]
    if missing:
        raise DataQualityError(f"Variables no encontradas: {missing}")

    data = frame[["datetime"] + requested].copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    data = data.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates("datetime")
    original_target = pd.to_numeric(data[target], errors="coerce")
    applied = {column: normalize_transformation((transformations or {}).get(column, "none")) for column in requested}
    for column in requested:
        data[column] = _transform_series(data[column], applied[column], column)
    data[ORIGINAL_TARGET_COLUMN] = original_target

    feature_columns = list(features)
    indexed = data.set_index("datetime")
    for feature in lagged_features:
        for lag in selected_lags:
            label = LAG_LABELS[lag]
            new_column = f"{feature}__lag_{label}"
            lookup_dates = data["datetime"] - _lag_offset(frequency, lag)
            data[new_column] = indexed[feature].reindex(lookup_dates).to_numpy()
            feature_columns.append(new_column)
    if include_time:
        data["Tiempo"] = np.arange(1, len(data) + 1, dtype=float)
        feature_columns.append("Tiempo")

    feature_columns = list(dict.fromkeys(feature_columns))
    if not feature_columns:
        raise DataQualityError("Seleccione al menos una variable explicativa, un rezago o Tiempo.")
    output = data[["datetime", target, ORIGINAL_TARGET_COLUMN] + feature_columns].dropna().reset_index(drop=True)
    if len(output) < 10:
        raise DataQualityError("Después de transformar y alinear fechas quedan menos de 10 observaciones completas.")
    output.attrs.update(
        {
            "transformations": applied,
            "raw_features": list(features),
            "lagged_features": list(lagged_features),
            "selected_lags": list(selected_lags),
            "include_time": include_time,
            "frequency": frequency,
            "target": target,
        }
    )
    return output, feature_columns


def _theil_u(observed: np.ndarray, predicted: np.ndarray) -> float | None:
    denominator = np.sqrt(np.mean(observed**2)) + np.sqrt(np.mean(predicted**2))
    return float(np.sqrt(np.mean((observed - predicted) ** 2)) / denominator) if denominator else None


def regression_metrics(observed: object, predicted: object) -> dict[str, float | None]:
    y = np.asarray(observed, dtype=float)
    y_hat = np.asarray(predicted, dtype=float)
    mse = float(mean_squared_error(y, y_hat))
    nonzero = y != 0
    return {
        "MAE": float(mean_absolute_error(y, y_hat)),
        "MSE": mse,
        "RMSE": float(np.sqrt(mse)),
        "MAPE_pct": float(np.mean(np.abs((y[nonzero] - y_hat[nonzero]) / y[nonzero])) * 100) if nonzero.any() else None,
        "R2": float(r2_score(y, y_hat)) if len(y) > 1 else None,
        "U_Theil": _theil_u(y, y_hat),
    }


def metrics_table(samples: dict[str, tuple[object, object]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sample, (observed, predicted) in samples.items():
        for metric, value in regression_metrics(observed, predicted).items():
            rows.append(
                {
                    "Muestra": sample,
                    "Indicador": metric,
                    "Valor": value,
                    "Explicación": METRIC_EXPLANATIONS[metric],
                }
            )
    return pd.DataFrame(rows)


def _estimator(model: str, *, standardize: bool, random_state: int, max_depth: int, n_neighbors: int, n_estimators: int) -> tuple[str, object]:
    if model == "tree":
        estimator: object = DecisionTreeRegressor(max_depth=max_depth, random_state=random_state)
    elif model == "knn":
        estimator = KNeighborsRegressor(n_neighbors=n_neighbors, weights="distance")
    elif model == "random_forest":
        estimator = RandomForestRegressor(n_estimators=n_estimators, max_depth=max_depth if max_depth > 0 else None, random_state=random_state, n_jobs=-1)
    else:
        raise ValueError(f"Modelo no soportado por scikit-learn: {model}")
    if standardize:
        estimator = Pipeline([("scale", StandardScaler()), ("model", estimator)])
    return MODEL_GUIDES[model]["nombre"], estimator


def _base_estimator(estimator: object) -> object:
    return estimator.named_steps["model"] if isinstance(estimator, Pipeline) else estimator


def _inverse_path(predicted: np.ndarray, transformation: str, observed_original: np.ndarray, observed_transformed: np.ndarray) -> np.ndarray:
    if transformation == "none":
        return predicted
    if transformation == "log":
        return np.exp(predicted)
    baseline = float(observed_original[0] - observed_transformed[0])
    return baseline + np.cumsum(predicted)


def _inverse_interval(values: np.ndarray, transformation: str, observed_original: np.ndarray, observed_transformed: np.ndarray) -> np.ndarray:
    return _inverse_path(values, transformation, observed_original, observed_transformed)


def _prediction_frame(
    subset: pd.DataFrame,
    transformed_prediction: np.ndarray,
    *,
    target: str,
    target_transformation: str,
    sample: str,
    lower_80: np.ndarray | None = None,
    upper_80: np.ndarray | None = None,
    lower_95: np.ndarray | None = None,
    upper_95: np.ndarray | None = None,
) -> pd.DataFrame:
    observed_transformed = subset[target].to_numpy(dtype=float)
    observed_original = subset.get(ORIGINAL_TARGET_COLUMN, subset[target]).to_numpy(dtype=float)
    estimated_original = _inverse_path(transformed_prediction, target_transformation, observed_original, observed_transformed)
    result = pd.DataFrame(
        {
            "datetime": subset["datetime"].to_numpy(),
            "muestra": sample,
            "observado": observed_original,
            "estimado": estimated_original,
            "observado_transformado": observed_transformed,
            "estimado_transformado": transformed_prediction,
        }
    )
    for label, values in (("inferior_80", lower_80), ("superior_80", upper_80), ("inferior_95", lower_95), ("superior_95", upper_95)):
        if values is not None:
            result[label] = _inverse_interval(values, target_transformation, observed_original, observed_transformed)
    result["residual"] = result["observado"] - result["estimado"]
    result["residual_transformado"] = result["observado_transformado"] - result["estimado_transformado"]
    sd = result["residual"].std(ddof=1)
    result["residual_estandarizado"] = result["residual"] / sd if sd and np.isfinite(sd) else np.nan
    return result


def _statsmodels_tables(fitted: Any) -> dict[str, pd.DataFrame]:
    coefficients = pd.DataFrame(
        {
            "Coeficiente": fitted.params.index.astype(str),
            "Estimación": fitted.params.to_numpy(dtype=float),
            "Error estándar": fitted.bse.to_numpy(dtype=float),
            "t": fitted.tvalues.to_numpy(dtype=float),
            "p-valor": fitted.pvalues.to_numpy(dtype=float),
            "IC 95 % inferior": fitted.conf_int().iloc[:, 0].to_numpy(dtype=float),
            "IC 95 % superior": fitted.conf_int().iloc[:, 1].to_numpy(dtype=float),
        }
    )
    fit = pd.DataFrame(
        {
            "Indicador": ["R²", "R² ajustado", "Prueba F", "p-valor F", "AIC", "BIC", "Durbin-Watson"],
            "Valor": [fitted.rsquared, fitted.rsquared_adj, fitted.fvalue, fitted.f_pvalue, fitted.aic, fitted.bic, __import__("statsmodels.stats.stattools", fromlist=["durbin_watson"]).durbin_watson(fitted.resid)],
        }
    )
    return {"Coeficientes OLS": coefficients, "Ajuste OLS": fit}


def _equations(fitted: Any, target: str, features: list[str]) -> tuple[str, str]:
    general = rf"\widehat{{{target}}}_t=\widehat{{\beta}}_0+" + "+".join(rf"\widehat{{\beta}}_{{{i}}}{name}_t" for i, name in enumerate(features, 1))
    terms = [f"{float(fitted.params.get('const', 0.0)):.6g}"]
    for feature in features:
        coefficient = float(fitted.params.get(feature, 0.0))
        sign = "+" if coefficient >= 0 else "-"
        terms.append(f" {sign} {abs(coefficient):.6g}" + r"\," + f"{feature}_t")
    return general, rf"\widehat{{{target}}}_t=" + "".join(terms)


def fit_supervised(
    data: pd.DataFrame,
    *,
    target: str,
    feature_columns: list[str],
    model: str,
    train_fraction: float = 0.80,
    reserve_test: bool = True,
    split_index: int | None = None,
    standardize: bool | None = None,
    random_state: int = 42,
    max_depth: int = 4,
    n_neighbors: int = 5,
    n_estimators: int = 300,
    diagnostic_lags: int | None = None,
) -> SupervisedResult:
    """Estima un modelo; si no hay test, las métricas se identifican como ajuste."""

    import statsmodels.api as sm

    if reserve_test and not 0.50 <= train_fraction <= 0.95:
        raise DataQualityError("La proporción de entrenamiento debe estar entre 50 % y 95 %.")
    if len(data) < 10:
        raise DataQualityError("Se requieren al menos 10 observaciones completas.")
    attrs = dict(data.attrs)
    if reserve_test and split_index is not None:
        split = int(split_index)
        if split < 5 or len(data) - split < 2:
            raise DataQualityError(
                "La separación debe conservar al menos cinco observaciones de calibración y dos de prueba."
            )
    else:
        split = int(np.floor(len(data) * train_fraction)) if reserve_test else len(data)
        split = min(max(split, 5), len(data) - 2) if reserve_test else len(data)
    train = data.iloc[:split].copy()
    test = data.iloc[split:].copy()
    use_standardize = model == "knn" if standardize is None else bool(standardize)
    x_train = train[feature_columns]
    y_train = train[target]
    stats_result = None

    try:
        if model == "linear":
            name = MODEL_GUIDES[model]["nombre"]
            stats_result = sm.OLS(y_train, sm.add_constant(x_train, has_constant="add"), missing="drop").fit()
            estimator: object = stats_result
            train_prediction = np.asarray(stats_result.predict(sm.add_constant(x_train, has_constant="add")), dtype=float)
        else:
            name, estimator = _estimator(
                model,
                standardize=use_standardize,
                random_state=random_state,
                max_depth=max_depth,
                n_neighbors=min(n_neighbors, len(train)),
                n_estimators=n_estimators,
            )
            estimator.fit(x_train, y_train)
            train_prediction = np.asarray(estimator.predict(x_train), dtype=float)
    except Exception as exc:
        raise ModelError(f"No fue posible estimar {MODEL_GUIDES.get(model, {}).get('nombre', model)}: {exc}") from exc

    target_transformation = attrs.get("transformations", {}).get(target, "none")
    train_bounds: dict[str, np.ndarray] = {}
    if stats_result is not None:
        prediction = stats_result.get_prediction(sm.add_constant(x_train, has_constant="add"))
        for level, alpha in ((80, 0.20), (95, 0.05)):
            interval = np.asarray(prediction.conf_int(alpha=alpha), dtype=float)
            train_bounds[f"lower_{level}"] = interval[:, 0]
            train_bounds[f"upper_{level}"] = interval[:, 1]
    train_frame = _prediction_frame(
        train,
        train_prediction,
        target=target,
        target_transformation=target_transformation,
        sample="Entrenamiento" if reserve_test else "Ajuste con 100 %",
        lower_80=train_bounds.get("lower_80"),
        upper_80=train_bounds.get("upper_80"),
        lower_95=train_bounds.get("lower_95"),
        upper_95=train_bounds.get("upper_95"),
    )

    test_frame = pd.DataFrame()
    if reserve_test:
        x_test = test[feature_columns]
        if stats_result is not None:
            test_prediction_result = stats_result.get_prediction(sm.add_constant(x_test, has_constant="add"))
            test_prediction = np.asarray(test_prediction_result.predicted_mean, dtype=float)
            bounds = {}
            for level, alpha in ((80, 0.20), (95, 0.05)):
                interval = np.asarray(test_prediction_result.conf_int(alpha=alpha), dtype=float)
                bounds[f"lower_{level}"] = interval[:, 0]
                bounds[f"upper_{level}"] = interval[:, 1]
        else:
            test_prediction = np.asarray(estimator.predict(x_test), dtype=float)
            bounds = {}
        test_frame = _prediction_frame(
            test,
            test_prediction,
            target=target,
            target_transformation=target_transformation,
            sample="Prueba",
            lower_80=bounds.get("lower_80"),
            upper_80=bounds.get("upper_80"),
            lower_95=bounds.get("lower_95"),
            upper_95=bounds.get("upper_95"),
        )

    metric_samples = {
        "Entrenamiento" if reserve_test else "Ajuste final (100 %)": (
            train_frame["observado"],
            train_frame["estimado"],
        )
    }
    if reserve_test:
        metric_samples["Prueba"] = (test_frame["observado"], test_frame["estimado"])
    metrics_by_sample = metrics_table(metric_samples)
    primary = test_frame if reserve_test else train_frame
    metrics = regression_metrics(primary["observado"], primary["estimado"])

    base = _base_estimator(estimator)
    if stats_result is not None:
        feature_effects = pd.DataFrame({"variable": feature_columns, "coeficiente": [float(stats_result.params.get(column, np.nan)) for column in feature_columns]})
    elif hasattr(base, "feature_importances_"):
        feature_effects = pd.DataFrame({"variable": feature_columns, "importancia_interna": base.feature_importances_}).sort_values("importancia_interna", ascending=False)
    else:
        feature_effects = pd.DataFrame({"variable": feature_columns})

    permutation = pd.DataFrame()
    if model == "random_forest":
        sample = test if reserve_test else train
        sample_y = sample[target]
        if len(sample) >= 3:
            perm = permutation_importance(estimator, sample[feature_columns], sample_y, n_repeats=10, random_state=random_state, scoring="neg_mean_squared_error")
            permutation = pd.DataFrame({"variable": feature_columns, "importancia_permutación": perm.importances_mean, "desviación_permutación": perm.importances_std}).sort_values("importancia_permutación", ascending=False)

    tree_rules = export_text(base, feature_names=feature_columns) if model == "tree" else None
    diagnostic_residuals = train_frame["residual"]
    influence = stats_result.get_influence() if stats_result is not None else None
    diagnostic_exog = sm.add_constant(x_train, has_constant="add") if stats_result is not None else None
    diagnostics = residual_diagnostics(diagnostic_residuals, exog=diagnostic_exog, influence=influence, ljung_box_lag=diagnostic_lags)
    acf_frame, pacf_frame, used_lags = correlation_diagnostics(diagnostic_residuals, diagnostic_lags)
    residuals = pd.concat(
        [train_frame[["datetime", "muestra", "residual", "residual_estandarizado", "residual_transformado"]], test_frame[["datetime", "muestra", "residual", "residual_estandarizado", "residual_transformado"]] if not test_frame.empty else pd.DataFrame()],
        ignore_index=True,
    )
    warnings: list[str] = []
    if use_standardize:
        warnings.append("Las explicativas se estandarizaron con parámetros calculados únicamente en entrenamiento.")
    if not reserve_test:
        warnings.append("No se reservaron datos de prueba: las métricas describen ajuste dentro de muestra, no desempeño predictivo fuera de muestra.")
    if model != "linear":
        warnings.append("Árbol, KNN y Random Forest entregan pronósticos puntuales; no se presentan rangos analíticos.")
    if target_transformation == "difference":
        warnings.append("Las predicciones de primeras diferencias se acumularon desde el último nivel conocido para volver a la unidad original.")

    general = estimated = summary = ""
    tables: dict[str, pd.DataFrame] = {}
    if stats_result is not None:
        general, estimated = _equations(stats_result, target, feature_columns)
        summary = stats_result.summary().as_text()
        tables = _statsmodels_tables(stats_result)
    configuration = {
        **attrs,
        "model": model,
        "standardize": use_standardize,
        "random_state": random_state,
        "max_depth": max_depth,
        "n_neighbors": n_neighbors,
        "n_estimators": n_estimators,
        "diagnostic_lags": used_lags,
        "split_index": split if reserve_test else None,
        "calibration_start": str(train["datetime"].min()),
        "calibration_end": str(train["datetime"].max()),
        "test_start": str(test["datetime"].min()) if reserve_test else None,
        "test_end": str(test["datetime"].max()) if reserve_test else None,
        "observations_calibration": len(train),
        "observations_test": len(test),
    }
    return SupervisedResult(
        model_name=name,
        estimator=estimator,
        predictions=primary,
        metrics=metrics,
        feature_effects=feature_effects.reset_index(drop=True),
        residuals=residuals,
        interval_method="Intervalos analíticos OLS de Statsmodels" if model == "linear" else "Pronóstico puntual",
        warnings=warnings,
        tree_rules=tree_rules,
        train_predictions=train_frame,
        test_predictions=test_frame,
        metrics_by_sample=metrics_by_sample,
        permutation_importance=permutation.reset_index(drop=True),
        residual_descriptive=residual_descriptive(diagnostic_residuals),
        diagnostics=diagnostics,
        acf=acf_frame,
        pacf=pacf_frame,
        equation_general_latex=general,
        equation_estimated_latex=estimated,
        statsmodels_summary=summary,
        statsmodels_tables=tables,
        model_code=model,
        target=target,
        feature_columns=feature_columns,
        reserve_test=reserve_test,
        configuration=configuration,
        prepared_data=data.copy(),
    )


def naive_forecast(series: pd.Series, horizon: int, seasonal_period: int | None = None) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        raise DataQualityError("No hay valores para el modelo ingenuo.")
    if seasonal_period and seasonal_period > 0:
        if len(values) < seasonal_period:
            raise DataQualityError("La serie es más corta que el periodo estacional.")
        return np.resize(values[-seasonal_period:], horizon)
    return np.repeat(values[-1], horizon)


def seasonal_future_defaults(
    frame: pd.DataFrame,
    variables: list[str],
    horizon: int,
    *,
    start_after: object | None = None,
) -> pd.DataFrame:
    """Crea exógenas futuras con el promedio histórico del mismo mes calendario."""

    data = frame[["datetime"] + variables].copy().sort_values("datetime")
    data["datetime"] = pd.to_datetime(data["datetime"], utc=True)
    last = pd.Timestamp(start_after) if start_after is not None else data["datetime"].max()
    last = last.tz_localize("UTC") if last.tzinfo is None else last.tz_convert("UTC")
    future = pd.DataFrame({"datetime": pd.date_range(last + pd.offsets.MonthBegin(), periods=horizon, freq="MS", tz="UTC")})
    month_means = data.assign(mes=data["datetime"].dt.month).groupby("mes")[variables].mean(numeric_only=True)
    overall = data[variables].mean(numeric_only=True)
    for variable in variables:
        future[variable] = [month_means[variable].get(month, overall.get(variable, np.nan)) for month in future["datetime"].dt.month]
    return future


def forecast_supervised(result: SupervisedResult, history: pd.DataFrame, future_original: pd.DataFrame) -> pd.DataFrame:
    """Pronostica recursivamente con el mismo método y las exógenas editadas por el usuario."""

    import statsmodels.api as sm

    cfg = result.configuration
    transformations = cfg.get("transformations", {})
    raw_features = list(cfg.get("raw_features", []))
    lagged_features = list(cfg.get("lagged_features", []))
    selected_lags = list(cfg.get("selected_lags", []))
    target = result.target
    requested = list(dict.fromkeys([target] + raw_features + lagged_features))
    history_work = history[["datetime"] + [column for column in requested if column in history]].copy()
    history_work["datetime"] = pd.to_datetime(history_work["datetime"], utc=True)
    history_work = history_work.sort_values("datetime").reset_index(drop=True)
    future = future_original.copy()
    future["datetime"] = pd.to_datetime(future["datetime"], utc=True)
    for column in requested:
        if column not in future:
            future[column] = np.nan
    combined = pd.concat([history_work, future[["datetime"] + requested]], ignore_index=True)
    history_length = len(history_work)

    if result.reserve_test:
        full_result = fit_supervised(
            result.prepared_data,
            target=target,
            feature_columns=result.feature_columns,
            model=result.model_code,
            reserve_test=False,
            standardize=cfg.get("standardize"),
            random_state=int(cfg.get("random_state", 42)),
            max_depth=int(cfg.get("max_depth", 4)),
            n_neighbors=int(cfg.get("n_neighbors", 5)),
            n_estimators=int(cfg.get("n_estimators", 300)),
        )
        estimator = full_result.estimator
    else:
        estimator = result.estimator
    rows: list[dict[str, Any]] = []

    def transformed_value(column: str, position: int) -> float:
        kind = transformations.get(column, "none")
        value = float(combined.at[position, column])
        if kind == "none":
            return value
        if kind == "log":
            if value <= 0:
                raise DataQualityError(f"La exógena futura {column} debe ser positiva para aplicar logaritmo.")
            return float(np.log(value))
        if position == 0 or pd.isna(combined.at[position - 1, column]):
            raise DataQualityError(f"No existe un valor anterior para calcular la primera diferencia de {column}.")
        return value - float(combined.at[position - 1, column])

    for position in range(history_length, len(combined)):
        feature_values: dict[str, float] = {}
        for feature in raw_features:
            if feature in result.feature_columns:
                feature_values[feature] = transformed_value(feature, position)
        for feature in lagged_features:
            for lag in selected_lags:
                offset = LAG_PERIODS[lag]
                lookup = position - offset
                if lookup < 0:
                    raise DataQualityError(f"No hay historia suficiente para el rezago {offset} de {feature}.")
                feature_values[f"{feature}__lag_{LAG_LABELS[lag]}"] = transformed_value(feature, lookup)
        if "Tiempo" in result.feature_columns:
            feature_values["Tiempo"] = float(position + 1)
        x = pd.DataFrame([[feature_values[column] for column in result.feature_columns]], columns=result.feature_columns)
        bounds: dict[str, float] = {}
        if result.model_code == "linear":
            prediction = estimator.get_prediction(sm.add_constant(x, has_constant="add"))
            predicted_transformed = float(np.asarray(prediction.predicted_mean)[0])
            for level, alpha in ((80, 0.20), (95, 0.05)):
                interval = np.asarray(prediction.conf_int(alpha=alpha), dtype=float)[0]
                bounds[f"inferior_{level}_transformado"] = float(interval[0])
                bounds[f"superior_{level}_transformado"] = float(interval[1])
        else:
            predicted_transformed = float(np.asarray(estimator.predict(x))[0])
        kind = transformations.get(target, "none")
        if kind == "none":
            predicted_original = predicted_transformed
        elif kind == "log":
            predicted_original = float(np.exp(predicted_transformed))
        else:
            predicted_original = float(combined.at[position - 1, target]) + predicted_transformed
        combined.at[position, target] = predicted_original
        row: dict[str, Any] = {"datetime": combined.at[position, "datetime"], "pronóstico": predicted_original}
        for key, value in bounds.items():
            label = key.replace("_transformado", "")
            if kind == "none":
                row[label] = value
            elif kind == "log":
                row[label] = float(np.exp(value))
            else:
                row[label] = float(combined.at[position - 1, target]) + value
        rows.append(row)
    return pd.DataFrame(rows)
